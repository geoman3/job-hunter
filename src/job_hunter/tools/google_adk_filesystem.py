"""Workspace filesystem tools as ADK FunctionTools."""

from __future__ import annotations

from pathlib import Path

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

MAX_OUTPUT_CHARS = 100_000


def _resolve_path(workspace: Path, path: str) -> Path:
    """Resolve *path* relative to *workspace*, rejecting path traversal."""
    root = workspace.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes workspace: {path}")
    return target


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} total chars)"


def build_filesystem_tools(workspace_dir: Path) -> list[FunctionTool]:
    """Build list/read/write FunctionTools scoped to the workspace."""
    workspace = workspace_dir.resolve()

    def list_files(
        path: str = ".",
        recursive: bool = False,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """List files and directories under a workspace path.

        Args:
            path: Directory path relative to the workspace root (default: ".").
            recursive: If True, list all files recursively; otherwise one level.
        """
        try:
            target = _resolve_path(workspace, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        if not target.exists():
            return {"status": "error", "error": f"Path not found: {path}"}
        if not target.is_dir():
            return {
                "status": "ok",
                "entries": [
                    {
                        "path": str(target.relative_to(workspace)),
                        "type": "file",
                        "size_bytes": target.stat().st_size,
                    }
                ],
            }

        entries: list[dict] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        for item in sorted(iterator):
            if item == target:
                continue
            rel = item.relative_to(workspace)
            entry: dict = {
                "path": str(rel),
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size_bytes"] = item.stat().st_size
            entries.append(entry)

        return {"status": "ok", "path": path, "entries": entries}

    def read_file(
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """Read a text file from the workspace with optional line range.

        Args:
            path: File path relative to the workspace root.
            start_line: First line to return, 1-based inclusive (default: 1).
            end_line: Last line to return, 1-based inclusive (default: end of file).
        """
        try:
            target = _resolve_path(workspace, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        if not target.exists():
            return {"status": "error", "error": f"File not found: {path}"}
        if not target.is_file():
            return {"status": "error", "error": f"Not a file: {path}"}

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "status": "error",
                "error": f"File is not UTF-8 text: {path}. Use a text format.",
            }

        lines = text.splitlines(keepends=True)
        total = len(lines)
        start = max(1, start_line)
        end = min(total, end_line or total)

        if start > total:
            return {
                "status": "error",
                "error": f"start_line {start} exceeds file length ({total} lines).",
                "total_lines": total,
            }
        if start > end:
            return {
                "status": "error",
                "error": f"start_line ({start}) is after end_line ({end}).",
                "total_lines": total,
            }

        selected = lines[start - 1 : end]
        numbered = "".join(
            f"{start + i:6d}\t{line}" for i, line in enumerate(selected)
        )
        result: dict = {
            "status": "ok",
            "content": _truncate(numbered),
        }
        if start > 1 or end < total:
            result["total_lines"] = total
        return result

    def write_file(
        path: str,
        content: str,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """Create or overwrite a text file in the workspace.

        Args:
            path: File path relative to the workspace root.
            content: Full file content to write.
        """
        try:
            target = _resolve_path(workspace, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "error": str(exc)}

        return {"status": "ok", "message": f"Wrote {path}", "bytes_written": len(content.encode("utf-8"))}

    return [
        FunctionTool(list_files, require_confirmation=True),
        FunctionTool(read_file, require_confirmation=True),
        FunctionTool(write_file, require_confirmation=True),
    ]
