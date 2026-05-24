"""Smoke tests for Settings env loading and workspace bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter import config as config_module
from job_hunter.config import Settings, ensure_workspace


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from the developer's on-disk .env and shell environment."""
    monkeypatch.setattr(config_module, "_load_dotenv_safe", lambda: None)
    for var in (
        "JOB_HUNTER_APP_NAME",
        "JOB_HUNTER_WORKSPACE",
        "JOB_HUNTER_USER_ID",
        "JOB_HUNTER_SESSION_ID",
        "JOB_HUNTER_MODEL",
        "ARCADE_USER_ID",
    ):
        monkeypatch.delenv(var, raising=False)


def test_from_env_uses_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env()

    assert settings.app_name == "job_hunter"
    assert settings.workspace_dir == (tmp_path / "workspace").resolve()
    assert settings.arcade_user_id == "job_hunter_user"
    assert settings.default_user_id == "job_hunter_user"
    assert settings.default_session_id == "default"
    assert settings.model is None


def test_from_env_workspace_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JOB_HUNTER_WORKSPACE", str(tmp_path / "ignored"))
    settings = Settings.from_env(workspace_dir=tmp_path / "explicit")
    assert settings.workspace_dir == (tmp_path / "explicit").resolve()


def test_from_env_reads_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JOB_HUNTER_APP_NAME", "custom_app")
    monkeypatch.setenv("ARCADE_USER_ID", "user@example.com")
    monkeypatch.setenv("JOB_HUNTER_USER_ID", "fallback_user")
    monkeypatch.setenv("JOB_HUNTER_SESSION_ID", "abc-123")
    monkeypatch.setenv("JOB_HUNTER_MODEL", "gemini-2.5-flash")

    settings = Settings.from_env(workspace_dir=tmp_path)

    assert settings.app_name == "custom_app"
    assert settings.arcade_user_id == "user@example.com"
    assert settings.default_user_id == "fallback_user"
    assert settings.default_session_id == "abc-123"
    assert settings.model == "gemini-2.5-flash"


def test_from_env_arcade_user_falls_back_to_job_hunter_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JOB_HUNTER_USER_ID", "fallback_user")
    settings = Settings.from_env(workspace_dir=tmp_path)
    assert settings.arcade_user_id == "fallback_user"


def test_ensure_workspace_creates_profile_dir(tmp_path: Path) -> None:
    settings = Settings.from_env(workspace_dir=tmp_path / "ws")
    root = ensure_workspace(settings)

    assert root == (tmp_path / "ws").resolve()
    assert root.is_dir()
    assert (root / "profile").is_dir()


def test_ensure_workspace_is_idempotent(tmp_path: Path) -> None:
    settings = Settings.from_env(workspace_dir=tmp_path / "ws")
    ensure_workspace(settings)
    (settings.workspace_dir / "profile" / "resume.md").write_text("hello")
    ensure_workspace(settings)
    assert (settings.workspace_dir / "profile" / "resume.md").read_text() == "hello"
