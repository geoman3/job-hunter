"""Smoke tests for base64 decoding helpers used after Drive downloads."""

from __future__ import annotations

import base64
import json

import pytest

from job_hunter.tools.file_decode import (
    _extract_base64_from_json,
    _normalize_base64_text,
    _strip_data_url_prefix,
    decode_base64_payload,
)


def _b64(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return base64.b64encode(data).decode("ascii")


def test_strip_data_url_prefix_removes_mime_header() -> None:
    raw = "data:application/pdf;base64,AAAA"
    assert _strip_data_url_prefix(raw) == "AAAA"


def test_strip_data_url_prefix_is_idempotent_for_plain_input() -> None:
    raw = "AAAABBBB"
    assert _strip_data_url_prefix(raw) == "AAAABBBB"


def test_extract_base64_from_json_picks_content_key() -> None:
    payload = json.dumps({"content": _b64("hello"), "other": "ignored"})
    assert _extract_base64_from_json(payload) == _b64("hello")


def test_extract_base64_from_json_returns_none_for_non_object() -> None:
    assert _extract_base64_from_json("[1, 2, 3]") is None


def test_extract_base64_from_json_returns_none_for_invalid_json() -> None:
    assert _extract_base64_from_json("not json") is None


def test_normalize_base64_text_strips_whitespace_and_data_url() -> None:
    raw = "data:text/plain;base64,  AAAA\n BBBB  \tCCCC  "
    assert _normalize_base64_text(raw) == "AAAABBBBCCCC"


def test_normalize_base64_text_unwraps_json_payload() -> None:
    payload = json.dumps({"data": "  AAAA BBBB  "})
    assert _normalize_base64_text(payload) == "AAAABBBB"


def test_decode_base64_payload_roundtrips_text() -> None:
    encoded = _b64("George's resume\nLine 2")
    assert decode_base64_payload(encoded) == b"George's resume\nLine 2"


def test_decode_base64_payload_handles_json_wrapper() -> None:
    encoded = _b64("hello")
    payload = json.dumps({"content": encoded})
    assert decode_base64_payload(payload) == b"hello"


def test_decode_base64_payload_handles_data_url() -> None:
    encoded = _b64("hello")
    assert decode_base64_payload(f"data:text/plain;base64,{encoded}") == b"hello"


def test_decode_base64_payload_rejects_empty() -> None:
    with pytest.raises(ValueError, match="No base64 content"):
        decode_base64_payload("   \n  ")


def test_decode_base64_payload_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid base64"):
        decode_base64_payload("not_valid_base64!!!")
