"""Arcade tool error types"""

from __future__ import annotations

from arcadepy.types.execute_tool_response import ExecuteToolResponse
from arcadepy.types.shared.authorization_response import AuthorizationResponse


class ToolError(ValueError):
    def __init__(self, result: ExecuteToolResponse):
        self.result = result

    @property
    def message(self) -> str:
        if self.result.output and self.result.output.error:
            return self.result.output.error.message
        return "Tool execution failed"

    def __str__(self) -> str:
        name = getattr(self.result, "tool_name", None) or "unknown"
        return f"Tool {name} failed: {self.message}"


class AuthorizationError(PermissionError):
    def __init__(self, result: AuthorizationResponse):
        self.result = result

    @property
    def message(self) -> str:
        url = self.result.url or "(no URL provided)"
        return f"Authorization required: {url}"

    def __str__(self) -> str:
        return self.message
