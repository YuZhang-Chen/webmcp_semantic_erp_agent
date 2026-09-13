"""Stable validation diagnostics used by the CLI, tests, and compiler gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.code} {self.path}: {self.message}"


class ModelLoadError(ValueError):
    """Raised when a model or evidence document cannot be decoded."""


class ModelValidationError(ValueError):
    """Raised when a consumer asks for a model that did not pass its gate."""

    def __init__(self, issues: tuple[ValidationIssue, ...]):
        self.issues = issues
        super().__init__("\n".join(issue.render() for issue in issues))

