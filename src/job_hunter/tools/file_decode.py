"""Decode base64-encoded downloads (e.g. Google Drive) into workspace files."""

from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from job_hunter.tools.workspace_utils import (
    resolve_workspace_path,
    truncate_text,
)

_DATA_URL_RE = re.compile(r"^data:[^;]+;base64,", re.IGNORECASE)
_JSON_CONTENT_KEYS = ("content", "data", "file", "base64", "body", "bytes")


def _strip_data_url_prefix(text: str) -> str:
    return _DATA_URL_RE.sub("", text.strip())


def _extract_base64_from_json(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in _JSON_CONTENT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_base64_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("{"):
        extracted = _extract_base64_from_json(text)
        if extracted is not None:
            text = extracted
    text = _strip_data_url_prefix(text)
    return re.sub(r"\s+", "", text)


def decode_base64_payload(raw: str) -> bytes:
    """Decode a base64 string, tolerating data URLs and JSON wrappers."""
    normalized = _normalize_base64_text(raw)
    if not normalized:
        raise ValueError("No base64 content found.")
    try:
        return base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid base64: {exc}") from exc


def _guess_output_path(source: Path, decoded: bytes) -> Path:
    if decoded.startswith(b"%PDF"):
        return source.with_suffix(".pdf")
    return source


def _preview_text(decoded: bytes, limit: int = 500) -> str:
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary, {len(decoded)} bytes>"
    return truncate_text(text, limit)


def build_decode_file_tool(workspace_dir: Path) -> FunctionTool:
    """Build a workspace tool that decodes base64 file contents to plain text or binary."""
    workspace = workspace_dir.resolve()

    def decode_file(
        path: str,
        output_path: str | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """Decode a base64-encoded workspace file into readable text or a binary file.

        Use after GoogleDrive_DownloadFile when the saved file looks like gibberish
        (long alphanumeric text). Supports plain base64, data URLs, and JSON wrappers
        with a \"content\" field.

        Args:
            path: Workspace file containing base64 (e.g. profile/resume.md).
            output_path: Where to write decoded bytes. Defaults to the same path for
                text, or the same stem with a .pdf extension when the payload is a PDF.
        """
        try:
            source = resolve_workspace_path(workspace, path)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        if not source.exists():
            return {"status": "error", "error": f"File not found: {path}"}
        if not source.is_file():
            return {"status": "error", "error": f"Not a file: {path}"}

        try:
            raw = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "status": "error",
                "error": f"Cannot read {path} as UTF-8 text to decode.",
            }

        try:
            decoded = decode_base64_payload(raw)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        dest_rel = output_path
        if dest_rel is None:
            dest = _guess_output_path(source, decoded)
            dest_rel = str(dest.relative_to(workspace))
        else:
            try:
                dest = resolve_workspace_path(workspace, dest_rel)
            except ValueError as exc:
                return {"status": "error", "error": str(exc)}

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if decoded.startswith(b"%PDF") or (
                output_path and dest.suffix.lower() == ".pdf"
            ):
                dest.write_bytes(decoded)
                kind = "pdf"
            else:
                text = decoded.decode("utf-8")
                dest.write_text(text, encoding="utf-8")
                kind = "text"
        except UnicodeDecodeError:
            dest.write_bytes(decoded)
            kind = "binary"
        except OSError as exc:
            return {"status": "error", "error": str(exc)}

        result: dict = {
            "status": "ok",
            "message": f"Decoded {path} -> {dest_rel}",
            "output_path": dest_rel,
            "decoded_bytes": len(decoded),
            "content_kind": kind,
        }
        if kind == "text":
            result["preview"] = _preview_text(decoded)
        elif kind == "pdf":
            result["preview"] = (
                f"PDF ({len(decoded)} bytes). Use read_file only on text paths."
            )
        return result

    return FunctionTool(decode_file, require_confirmation=True)
