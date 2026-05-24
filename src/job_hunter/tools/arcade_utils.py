"""Arcade API helpers (from example/_utils.py)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from arcadepy import AsyncArcade
from arcadepy.types import ToolDefinition
from pydantic import BaseModel, Field, create_model

TYPE_MAPPING = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "json": dict,
}


def get_python_type(val_type: str) -> Any:
    _type = TYPE_MAPPING.get(val_type)
    if _type is None:
        raise ValueError(f"Invalid value type: {val_type}")
    return _type


def tool_definition_to_pydantic_model(tool_def: ToolDefinition) -> type[BaseModel]:
    """Convert a ToolDefinition's inputs into a Pydantic model for ADK schemas."""
    try:
        fields: dict[str, Any] = {}
        for param in tool_def.input.parameters or []:
            param_type = get_python_type(param.value_schema.val_type)
            if param_type is list and param.value_schema.inner_val_type:
                inner_type: type[Any] = get_python_type(
                    param.value_schema.inner_val_type
                )
                param_type = list[inner_type]  # type: ignore[valid-type]
            param_description = param.description or "No description provided."
            default = ... if param.required else None
            fields[param.name] = (
                param_type,
                Field(default=default, description=param_description),
            )
        return create_model(f"{tool_def.name}Args", **fields)
    except ValueError as exc:
        raise ValueError(
            f"Error converting {tool_def.name} parameters into pydantic model: {exc}"
        ) from exc


def get_arcade_client(
    *,
    base_url: str = "https://api.arcade.dev",
    api_key: str | None = None,
    **kwargs: Any,
) -> AsyncArcade:
    api_key = api_key or os.getenv("ARCADE_API_KEY")
    if api_key is None:
        raise ValueError("ARCADE_API_KEY is not set")
    return AsyncArcade(base_url=base_url, api_key=api_key, **kwargs)


async def fetch_arcade_tool_definitions(
    client: AsyncArcade,
    *,
    tools: list[str] | None = None,
    toolkits: list[str] | None = None,
    raise_on_empty: bool = True,
) -> list[ToolDefinition]:
    """Fetch tool definitions from Arcade by name and/or toolkit."""
    if not tools and not toolkits:
        if raise_on_empty:
            raise ValueError("No tools or toolkits provided to retrieve tool definitions")
        return []

    all_tools: list[ToolDefinition] = []

    if tools:
        responses = await asyncio.gather(
            *[client.tools.get(name=tool_id) for tool_id in tools]
        )
        all_tools.extend(responses)

    if toolkits:
        responses = await asyncio.gather(
            *[client.tools.list(toolkit=tk) for tk in toolkits]
        )
        for response in responses:
            all_tools.extend(response.items)

    return all_tools
