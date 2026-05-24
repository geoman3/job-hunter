"""Shared helpers for workspace-scoped tools."""

from __future__ import annotations

from pathlib import Path

MAX_OUTPUT_CHARS = 100_000


def resolve_workspace_path(workspace: Path, path: str) -> Path:
    """Resolve *path* relative to *workspace*, rejecting path traversal."""
    root = workspace.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes workspace: {path}")
    return target


def truncate_text(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} total chars)"
