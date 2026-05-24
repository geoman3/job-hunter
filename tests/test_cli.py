"""Smoke tests for the interactive CLI's continuation router and helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.events.event import Event
from google.genai import types

from job_hunter.cli import _continuation_nudge, _find_local_resume


def _tool_response_event(name: str) -> Event:
    return Event(
        author="agent",
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=f"call-{name}",
                        name=name,
                        response={"ok": True},
                    )
                )
            ],
        ),
    )


def _agent_text_event(text: str) -> Event:
    return Event(
        author="agent",
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


def test_continuation_nudge_returns_none_with_no_tool_calls() -> None:
    assert _continuation_nudge([_agent_text_event("hi")]) is None


def test_continuation_nudge_returns_none_when_agent_replied_after_tool() -> None:
    events = [_tool_response_event("list_files"), _agent_text_event("found x")]
    assert _continuation_nudge(events) is None


@pytest.mark.parametrize(
    ("tool_name", "expected_substring"),
    [
        ("GoogleDrive_DownloadFile", "decode_file"),
        ("decode_file", "decoded resume"),
        ("Firecrawl_Scrape", "scrape results"),
        ("GoogleSearch_Search", "job search results"),
        ("read_file", "complete the current workflow"),
        ("write_file", "next workflow step"),
        ("list_files", "proceed with"),
    ],
)
def test_continuation_nudge_dispatches_by_tool_name(
    tool_name: str, expected_substring: str
) -> None:
    nudge = _continuation_nudge([_tool_response_event(tool_name)])
    assert nudge is not None
    assert expected_substring.lower() in nudge.lower()


def test_continuation_nudge_falls_back_to_generic_message() -> None:
    nudge = _continuation_nudge([_tool_response_event("SomeUnknownTool")])
    assert nudge is not None
    assert "continue" in nudge.lower()


def test_find_local_resume_returns_none_without_profile(tmp_path: Path) -> None:
    assert _find_local_resume(tmp_path) is None


def test_find_local_resume_returns_none_when_profile_empty(tmp_path: Path) -> None:
    (tmp_path / "profile").mkdir()
    assert _find_local_resume(tmp_path) is None


def test_find_local_resume_finds_extension(tmp_path: Path) -> None:
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "resume.md").write_text("hi")
    result = _find_local_resume(tmp_path)
    assert result is not None
    assert result.as_posix() == "profile/resume.md"


def test_find_local_resume_picks_first_sorted_match(tmp_path: Path) -> None:
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "resume.pdf").write_text("a")
    (tmp_path / "profile" / "resume.md").write_text("b")
    result = _find_local_resume(tmp_path)
    assert result is not None
    assert result.suffix == ".md"
