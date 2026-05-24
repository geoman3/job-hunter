"""CLI for the job hunter agent."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import typer
from google.adk.cli.cli import (
    _collect_pending_function_calls,
    _prompt_for_function_call,
)
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from job_hunter.agent import build_app
from job_hunter.config import Settings, ensure_workspace
from job_hunter.tools import ArcadeTool, authorize_arcade_tools, get_arcade_tools
from job_hunter.tools._arcade_utils import get_arcade_client

def _format_event_text(event: Event) -> str | None:
    if not event.content or not event.content.parts:
        return None
    text_parts = [part.text for part in event.content.parts if part.text]
    return "".join(text_parts) if text_parts else None


app = typer.Typer(
    name="job-hunter",
    help="AI agent: download resume, find jobs, tailor resume, research roles.",
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
)


async def _run_interactive(
    settings: Settings,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    user_id = user_id or settings.default_user_id
    session_id = session_id or settings.default_session_id
    workspace = ensure_workspace(settings)

    arcade_tools: list[ArcadeTool] = []
    if settings.arcade_user_id and os.environ.get("ARCADE_API_KEY"):
        try:
            client = get_arcade_client()
            arcade_tools = await get_arcade_tools(
                client, user_id=settings.arcade_user_id
            )
            typer.echo("Authorizing Arcade toolkits (open any URLs shown)...")
            await authorize_arcade_tools(
                client, arcade_tools, settings.arcade_user_id
            )
        except ValueError:
            pass

    adk_app = build_app(settings, arcade_tools=arcade_tools)
    runner = InMemoryRunner(app=adk_app, app_name=settings.app_name)

    session = await runner.session_service.get_session(
        app_name=settings.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        session = await runner.session_service.create_session(
            app_name=settings.app_name,
            user_id=user_id,
            session_id=session_id,
            state={"user_id": settings.arcade_user_id},
        )
    elif not session.state.get("user_id"):
        session.state["user_id"] = settings.arcade_user_id

    typer.echo(f"Job Hunter — workspace: {workspace}")
    typer.echo("Type your request, or 'exit' to quit. Tool calls require approval.\n")

    next_message: types.Content | None = None
    resume_invocation_id: str | None = None

    try:
        while True:
            if next_message is None:
                query = input("[you]: ").strip()
                if not query:
                    continue
                if query.lower() in ("exit", "quit"):
                    break
                next_message = types.Content(
                    role="user", parts=[types.Part(text=query)]
                )

            collected_events = []
            invocation_id: str | None = None

            async with Aclosing(
                runner.run_async(
                    user_id=user_id,
                    session_id=session.id,
                    new_message=next_message,
                    invocation_id=resume_invocation_id,
                )
            ) as agen:
                async for event in agen:
                    collected_events.append(event)
                    if getattr(event, "invocation_id", None):
                        invocation_id = event.invocation_id
                    text = _format_event_text(event)
                    if text:
                        typer.echo(f"\n[{event.author}]: {text}")

            next_message = None
            resume_invocation_id = None

            pending = _collect_pending_function_calls(collected_events)
            if pending:
                parts = []
                for fc_id, fc_name, args in pending:
                    response = _prompt_for_function_call(fc_id, fc_name, args)
                    parts.extend(response.parts)
                next_message = types.Content(role="user", parts=parts)
                resume_invocation_id = invocation_id
    finally:
        await runner.close()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    user_id: Optional[str] = typer.Option(None, help="ADK session user id."),
    session_id: Optional[str] = typer.Option(None, help="ADK session id."),
) -> None:
    """Run the interactive job hunter agent."""
    if ctx.invoked_subcommand is not None:
        return
    settings = Settings.from_env()
    asyncio.run(
        _run_interactive(settings, user_id=user_id, session_id=session_id)
    )


def run_app() -> None:
    app()
