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
    text_parts = [
        part.text
        for part in event.content.parts
        if part.text and not getattr(part, "thought", False)
    ]
    return "".join(text_parts) if text_parts else None


def _tool_response_names(events: list[Event]) -> list[str]:
    names: list[str] = []
    for event in events:
        for response in event.get_function_responses():
            if response.name:
                names.append(response.name)
    return names


def _last_tool_response_index(events: list[Event]) -> int | None:
    last: int | None = None
    for index, event in enumerate(events):
        if event.get_function_responses():
            last = index
    return last


def _agent_text_after_last_tool(events: list[Event]) -> bool:
    """True if the model produced user-visible text after the last tool result."""
    last_tool_index = _last_tool_response_index(events)
    if last_tool_index is None:
        return False
    for event in events[last_tool_index + 1 :]:
        if _format_event_text(event):
            return True
    return False


def _continuation_nudge(events: list[Event]) -> str | None:
    """Prompt the agent to continue when a tool chain ends without user-visible text."""
    if _collect_pending_function_calls(events):
        return None
    tool_names = _tool_response_names(events)
    if not tool_names:
        return None
    if _agent_text_after_last_tool(events):
        return None

    last_tool = tool_names[-1].lower()
    if "downloadfile" in last_tool:
        return (
            "Continue with my job search: save the resume under profile/ with "
            "write_file if you have not yet, decode it with decode_file, then "
            "suggest job-search criteria from it and offer to run a search (or run "
            "GoogleSearch_Search after I approve)."
        )
    if last_tool == "decode_file":
        return (
            "Continue: read the decoded resume, summarize it if helpful, then "
            "proceed with job search or the next workflow step."
        )
    if "scrape" in last_tool or "firecrawl" in last_tool:
        return (
            "Continue: summarize the scrape results for me, save them with "
            "write_file to the job folder (e.g. research.md or job-description.md) "
            "if you have not yet, then proceed with the workflow."
        )
    if "googlesearch" in last_tool or last_tool.endswith("_search"):
        return (
            "Continue: present the job search results (individual posting URLs "
            "only) and suggest next steps."
        )
    if last_tool == "read_file":
        return (
            "Continue: use what you read to complete the current workflow step "
            "(tailor resume, research, or answer my question)."
        )
    if last_tool == "write_file":
        return (
            "Continue with the next workflow step without waiting for another "
            "message (e.g. research, job search, or summarize what you saved)."
        )
    if last_tool == "list_files":
        return (
            "Continue: read the resume or job files you found and proceed with "
            "the workflow."
        )
    return (
        "Continue the current workflow using the tool results above: tell me "
        "what you found or did, and take the next step without waiting for "
        "another prompt."
    )


_MAX_AUTO_CONTINUES = 5


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


def _find_local_resume(workspace: Path) -> Path | None:
    profile = workspace / "profile"
    if not profile.is_dir():
        return None
    for candidate in sorted(profile.glob("resume.*")):
        if candidate.is_file():
            return candidate.relative_to(workspace)
    return None


def _print_startup_guide(workspace: Path) -> None:
    """Show workflow-oriented prompts before the first user message."""
    local_resume = _find_local_resume(workspace)
    typer.echo("What would you like to do? Try one of these:")
    if local_resume is not None:
        typer.echo(
            f'  • Find jobs — "I want to find a job!" (will use {local_resume.as_posix()})'
        )
        typer.echo('  • Refresh resume — "Sync my resume from Google Drive"')
    else:
        typer.echo('  • Find jobs — "I want to find a job!"')
        typer.echo(
            '  • Get resume — "Find my resume in Google Drive and save it locally"'
        )
    typer.echo(
        '  • Tailor for a role — "Tailor my resume for https://example.com/jobs/123"'
    )
    typer.echo(
        '  • Research employer — "Research the company for my Stripe application"'
    )
    typer.echo(
        "Tool calls require approval (type yes to confirm). Type exit to quit.\n"
    )


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

    typer.echo(f"Job Hunter — workspace: {workspace}\n")
    _print_startup_guide(workspace)

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

            auto_continue_count = 0

            while True:
                collected_events: list[Event] = []
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

                pending = _collect_pending_function_calls(collected_events)
                if pending:
                    parts = []
                    for fc_id, fc_name, args in pending:
                        response = _prompt_for_function_call(fc_id, fc_name, args)
                        parts.extend(response.parts)
                    next_message = types.Content(role="user", parts=parts)
                    resume_invocation_id = invocation_id
                    continue

                nudge = _continuation_nudge(collected_events)
                if nudge and auto_continue_count < _MAX_AUTO_CONTINUES:
                    next_message = types.Content(
                        role="user", parts=[types.Part(text=nudge)]
                    )
                    resume_invocation_id = None
                    auto_continue_count += 1
                    continue

                break

            next_message = None
            resume_invocation_id = None
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
