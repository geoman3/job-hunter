"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv_safe() -> None:
    try:
        load_dotenv()
    except (OSError, PermissionError):
        pass


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the job hunter agent."""

    app_name: str
    workspace_dir: Path
    arcade_user_id: str
    default_user_id: str
    default_session_id: str
    model: str | None

    @classmethod
    def from_env(cls, *, workspace_dir: Path | str | None = None) -> Settings:
        _load_dotenv_safe()
        if workspace_dir is not None:
            workspace = Path(workspace_dir).expanduser()
        else:
            workspace = Path(
                os.environ.get("JOB_HUNTER_WORKSPACE", "workspace")
            ).expanduser()
        return cls(
            app_name=os.environ.get("JOB_HUNTER_APP_NAME", "job_hunter"),
            workspace_dir=workspace.resolve(),
            arcade_user_id=os.environ.get(
                "ARCADE_USER_ID",
                os.environ.get("JOB_HUNTER_USER_ID", "job_hunter_user"),
            ),
            default_user_id=os.environ.get("JOB_HUNTER_USER_ID", "job_hunter_user"),
            default_session_id=os.environ.get("JOB_HUNTER_SESSION_ID", "default"),
            model=os.environ.get("JOB_HUNTER_MODEL"),
        )


def ensure_workspace(settings: Settings) -> Path:
    """Create the agent workspace directory if needed."""
    root = settings.workspace_dir
    root.mkdir(parents=True, exist_ok=True)
    (root / "profile").mkdir(exist_ok=True)
    return root
