"""CLI for the job hunter agent."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.status import Status
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
from job_hunter.tools.arcade_utils import get_arcade_client


def _format_event_text(event: Event) -> str | None:
    if not event.content or not event.content.parts:
        return None
    text_parts = [part.text for part in event.content.parts if part.text]
    return "".join(text_parts) if text_parts else None


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _use_spinner() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("JOB_HUNTER_NO_SPINNER"):
        return False
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _spinner_label_for_event(event: Event) -> str:
    function_calls = event.get_function_calls()
    if function_calls:
        names = ", ".join(fc.name for fc in function_calls if fc.name)
        return f"Calling {names}…" if names else "Calling tool…"
    function_responses = event.get_function_responses()
    if function_responses:
        names = ", ".join(fr.name for fr in function_responses if fr.name)
        return f"Processing {names}…" if names else "Processing tool result…"
    return "Thinking…"


class _AgentSpinner(AbstractContextManager["_AgentSpinner"]):
    """TTY spinner shown while the agent is working between user-visible output."""

    def __init__(self) -> None:
        self._enabled = _use_spinner()
        self._console = Console(stderr=True) if self._enabled else None
        self._status: Status | None = None

    def __enter__(self) -> _AgentSpinner:
        if self._enabled and self._console is not None:
            self._status = self._console.status("[cyan]Thinking…[/]", spinner="dots")
            self._status.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._status is not None:
            self._status.stop()

    def update(self, event: Event) -> None:
        if self._status is not None:
            self._status.update(f"[cyan]{_spinner_label_for_event(event)}[/]")

    def pause(self) -> None:
        if self._status is not None:
            self._status.stop()

    def resume(self) -> None:
        if self._status is not None:
            self._status.start()


def _echo_agent_message(author: str, text: str) -> None:
    """Print agent text in a subtle color (user input stays default)."""
    if not _use_color():
        typer.echo(f"\n[{author}]: {text}")
        return
    typer.secho(f"\n[{author}]: ", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho(text, fg=typer.colors.BRIGHT_BLUE)


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
            await authorize_arcade_tools(client, arcade_tools, settings.arcade_user_id)
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

            with _AgentSpinner() as spinner:
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
                        spinner.update(event)
                        text = _format_event_text(event)
                        if text:
                            spinner.pause()
                            _echo_agent_message(event.author or "agent", text)
                            spinner.resume()

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
    directory: Annotated[
        Optional[Path],
        typer.Argument(
            help="Workspace directory (e.g. . for the current folder).",
        ),
    ] = None,
    user_id: Optional[str] = typer.Option(None, help="ADK session user id."),
    session_id: Optional[str] = typer.Option(None, help="ADK session id."),
) -> None:
    """Run the interactive job hunter agent."""
    if ctx.invoked_subcommand is not None:
        return
    workspace_dir = directory.expanduser().resolve() if directory is not None else None
    settings = Settings.from_env(workspace_dir=workspace_dir)
    asyncio.run(_run_interactive(settings, user_id=user_id, session_id=session_id))


def run_app() -> None:
    app()
