"""Job hunter root agent definition."""

from __future__ import annotations

from google.adk import Agent
from google.adk.apps.app import App
from google.adk.apps._configs import ResumabilityConfig

from job_hunter.config import Settings, ensure_workspace
from job_hunter.tools import ArcadeTool, build_filesystem_tools

INSTRUCTION = """\

"""


def build_root_agent(
    settings: Settings,
    *,
    arcade_tools: list[ArcadeTool] | None = None,
) -> Agent:
    workspace = ensure_workspace(settings)
    filesystem_tools = build_filesystem_tools(workspace)
    arcade_tools = arcade_tools or []

    agent_kwargs: dict = {
        "name": "job_hunter",
        "description": (
            "Downloads resumes from Google Drive, finds matching jobs, tailors "
            "resumes, and researches employers."
        ),
        "instruction": INSTRUCTION,
        "tools": [*filesystem_tools, *arcade_tools],
    }
    if settings.model:
        agent_kwargs["model"] = settings.model

    return Agent(**agent_kwargs)


def build_app(
    settings: Settings | None = None,
    *,
    arcade_tools: list[ArcadeTool] | None = None,
) -> App:
    settings = settings or Settings.from_env()
    return App(
        name=settings.app_name,
        root_agent=build_root_agent(settings, arcade_tools=arcade_tools),
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
