"""Smoke tests for workspace path resolution and text truncation."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter.tools.workspace_utils import (
    MAX_OUTPUT_CHARS,
    resolve_workspace_path,
    truncate_text,
)


def test_resolve_workspace_path_simple(tmp_path: Path) -> None:
    target = resolve_workspace_path(tmp_path, "profile/resume.md")
    assert target == (tmp_path / "profile" / "resume.md").resolve()


def test_resolve_workspace_path_allows_root(tmp_path: Path) -> None:
    assert resolve_workspace_path(tmp_path, ".") == tmp_path.resolve()


def test_resolve_workspace_path_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes workspace"):
        resolve_workspace_path(tmp_path, "../etc/passwd")


def test_resolve_workspace_path_rejects_absolute_outside(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes workspace"):
        resolve_workspace_path(tmp_path, "/etc/passwd")


def test_resolve_workspace_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir()
    link = tmp_path / "escape"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes workspace"):
        resolve_workspace_path(tmp_path, "escape/secrets.txt")


def test_truncate_text_under_limit_returns_original() -> None:
    text = "hello world"
    assert truncate_text(text, limit=100) == text


def test_truncate_text_over_limit_appends_marker() -> None:
    text = "x" * 50
    result = truncate_text(text, limit=10)
    assert result.startswith("x" * 10)
    assert "truncated" in result
    assert "50 total chars" in result


def test_truncate_text_default_limit_is_documented_constant() -> None:
    assert MAX_OUTPUT_CHARS == 100_000
