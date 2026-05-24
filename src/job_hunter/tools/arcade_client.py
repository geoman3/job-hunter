"""Arcade tools for Google ADK, based on example/tools.py."""

from __future__ import annotations

import logging
from typing import Any

from arcadepy import AsyncArcade
from arcadepy.types import ToolDefinition
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools._automatic_function_calling_util import (
    _map_pydantic_type_to_property_schema,
)
from google.genai import types
from typing_extensions import override

from job_hunter.tools._arcade_errors import AuthorizationError, ToolError
from job_hunter.tools._arcade_utils import (
    fetch_arcade_tool_definitions,
    get_arcade_client,
    tool_definition_to_pydantic_model,
)

logger = logging.getLogger(__name__)

# Toolkits used by the job hunter agent (Google Drive, search, web scrape).
DEFAULT_TOOLKITS = ["GoogleDrive", "GoogleSearch", "Firecrawl"]


def _resolve_user_id(tool_context: ToolContext, fallback_user_id: str) -> str:
    user_id = tool_context.state.get("user_id")
    if user_id:
        return str(user_id)
    return fallback_user_id


async def _authorize_tool(
    client: AsyncArcade,
    tool_context: ToolContext,
    tool_name: str,
    fallback_user_id: str,
) -> None:
    user_id = _resolve_user_id(tool_context, fallback_user_id)
    result = await client.tools.authorize(tool_name=tool_name, user_id=user_id)
    if result.status != "completed":
        raise AuthorizationError(result)


async def _async_invoke_arcade_tool(
    *,
    tool_context: ToolContext,
    tool_args: dict[str, Any],
    tool_name: str,
    requires_auth: bool,
    client: AsyncArcade,
    fallback_user_id: str,
) -> Any:
    if requires_auth:
        await _authorize_tool(client, tool_context, tool_name, fallback_user_id)

    logger.info("Executing Arcade tool %s", tool_name)

    result = await client.tools.execute(
        tool_name=tool_name,
        input=tool_args,
        user_id=_resolve_user_id(tool_context, fallback_user_id),
    )

    if not result.success:
        raise ToolError(result)

    if result.output is None:
        return None
    return result.output.value


class ArcadeTool(FunctionTool):
    """ADK FunctionTool backed by a remote Arcade tool definition."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        schema: ToolDefinition,
        client: AsyncArcade,
        requires_auth: bool,
        fallback_user_id: str,
        original_name: str | None = None,
        require_confirmation: bool = True,
    ) -> None:
        arcade_tool_name = original_name or name

        async def func(tool_context: ToolContext, **kwargs: Any) -> Any:
            return await _async_invoke_arcade_tool(
                tool_context=tool_context,
                tool_args=kwargs,
                tool_name=arcade_tool_name,
                requires_auth=requires_auth,
                client=client,
                fallback_user_id=fallback_user_id,
            )

        func.__name__ = name.lower()
        func.__doc__ = description

        super().__init__(func, require_confirmation=require_confirmation)

        json_schema = tool_definition_to_pydantic_model(schema).model_json_schema()
        _map_pydantic_type_to_property_schema(json_schema)

        self._schema = json_schema
        self.name = name
        self.description = description
        self.client = client
        self.requires_auth = requires_auth
        self._arcade_tool_name = arcade_tool_name
        self._fallback_user_id = fallback_user_id

    @override
    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Run with full args dict (bypasses signature filtering) and HITL."""
        if self._require_confirmation:
            if not tool_context.tool_confirmation:
                tool_context.request_confirmation(
                    hint=(
                        f"Approve Arcade tool {self.name} ({self._arcade_tool_name}) "
                        f"with arguments: {args}"
                    ),
                )
                tool_context.actions.skip_summarization = True
                return {
                    "error": (
                        "This Arcade tool call requires user confirmation. "
                        "Approve or reject to continue."
                    )
                }
            if not tool_context.tool_confirmation.confirmed:
                return {"error": f"Arcade tool {self.name} was rejected by the user."}

        return await _async_invoke_arcade_tool(
            tool_context=tool_context,
            tool_args=args,
            tool_name=self._arcade_tool_name,
            requires_auth=self.requires_auth,
            client=self.client,
            fallback_user_id=self._fallback_user_id,
        )

    @override
    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            parameters=types.Schema(
                type="OBJECT",
                properties=self._schema.get("properties", {}),
                required=self._schema.get("required"),
            ),
            description=self.description,
            name=self.name,
        )


async def get_arcade_tools(
    client: AsyncArcade | None = None,
    *,
    user_id: str,
    tools: list[str] | None = None,
    toolkits: list[str] | None = None,
    raise_on_empty: bool = True,
    require_confirmation: bool = True,
    **client_kwargs: Any,
) -> list[ArcadeTool]:
    """Load Arcade tools as ADK FunctionTools."""
    if not client:
        client = get_arcade_client(**client_kwargs)

    toolkits = toolkits if toolkits is not None else DEFAULT_TOOLKITS
    definitions = await fetch_arcade_tool_definitions(
        client,
        tools=tools,
        toolkits=toolkits if not tools else None,
        raise_on_empty=raise_on_empty,
    )

    arcade_tools: list[ArcadeTool] = []
    for tool_def in definitions:
        requires_auth = bool(
            tool_def.requirements and tool_def.requirements.authorization
        )
        sanitized_name = tool_def.qualified_name.replace(".", "_")
        arcade_tools.append(
            ArcadeTool(
                name=sanitized_name,
                description=tool_def.description or tool_def.qualified_name,
                schema=tool_def,
                requires_auth=requires_auth,
                client=client,
                fallback_user_id=user_id,
                original_name=tool_def.qualified_name,
                require_confirmation=require_confirmation,
            )
        )

    return arcade_tools


async def authorize_arcade_tools(
    client: AsyncArcade,
    tools: list[ArcadeTool],
    user_id: str,
) -> None:
    """Pre-authorize Arcade tools that require OAuth (interactive if needed)."""
    for tool in tools:
        if not tool.requires_auth:
            continue
        auth = await client.tools.authorize(
            tool_name=tool._arcade_tool_name,
            user_id=user_id,
        )
        if auth.status == "completed":
            continue
        if auth.url:
            print(f"\nAuthorize {tool._arcade_tool_name}:\n  {auth.url}\n")
        if auth.id:
            auth = await client.auth.status(id=auth.id, wait=45)
        if auth.status != "completed":
            raise AuthorizationError(auth)


