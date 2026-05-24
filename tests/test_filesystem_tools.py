"""Smoke tests for the workspace-scoped filesystem FunctionTools."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter.tools.google_adk_filesystem import build_filesystem_tools


def _tools_by_name(workspace: Path) -> dict[str, object]:
    return {tool.name: tool for tool in build_filesystem_tools(workspace)}


def test_build_filesystem_tools_exposes_expected_names(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    assert set(tools) == {"list_files", "read_file", "write_file", "decode_file"}


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    write_file = tools["write_file"].func  # type: ignore[attr-defined]
    read_file = tools["read_file"].func  # type: ignore[attr-defined]

    written = write_file(path="profile/resume.md", content="Hello\nWorld\n")
    assert written["status"] == "ok"
    assert (tmp_path / "profile" / "resume.md").read_text() == "Hello\nWorld\n"

    read = read_file(path="profile/resume.md")
    assert read["status"] == "ok"
    assert "Hello" in read["content"]
    assert "World" in read["content"]


def test_read_file_with_line_range(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    write_file = tools["write_file"].func  # type: ignore[attr-defined]
    read_file = tools["read_file"].func  # type: ignore[attr-defined]

    write_file(path="notes.md", content="one\ntwo\nthree\nfour\n")
    result = read_file(path="notes.md", start_line=2, end_line=3)

    assert result["status"] == "ok"
    assert "two" in result["content"]
    assert "three" in result["content"]
    assert "one" not in result["content"]
    assert "four" not in result["content"]
    assert result["total_lines"] == 4


def test_read_file_missing_path_returns_error(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    read_file = tools["read_file"].func  # type: ignore[attr-defined]

    result = read_file(path="does-not-exist.md")
    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd"])
def test_write_file_rejects_path_traversal(tmp_path: Path, path: str) -> None:
    tools = _tools_by_name(tmp_path)
    write_file = tools["write_file"].func  # type: ignore[attr-defined]

    result = write_file(path=path, content="bad")
    assert result["status"] == "error"
    assert "escapes workspace" in result["error"]


def test_list_files_non_recursive_returns_top_level(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    write_file = tools["write_file"].func  # type: ignore[attr-defined]
    list_files = tools["list_files"].func  # type: ignore[attr-defined]

    write_file(path="profile/resume.md", content="x")
    write_file(path="jobs/acme/job-description.md", content="y")

    result = list_files(path=".")
    assert result["status"] == "ok"
    paths = {entry["path"] for entry in result["entries"]}
    assert {"profile", "jobs"} <= paths
    assert "profile/resume.md" not in paths


def test_list_files_recursive_includes_nested(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    write_file = tools["write_file"].func  # type: ignore[attr-defined]
    list_files = tools["list_files"].func  # type: ignore[attr-defined]

    write_file(path="profile/resume.md", content="x")

    result = list_files(path=".", recursive=True)
    assert result["status"] == "ok"
    paths = {entry["path"] for entry in result["entries"]}
    assert "profile/resume.md" in paths
