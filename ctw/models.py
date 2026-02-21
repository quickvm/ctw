"""Shared pydantic models — the contract between providers and main.py."""

from pydantic import BaseModel, ConfigDict


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str  # provider-native ID
    identifier: str  # ENG-123 or owner/repo#123
    title: str
    description: str | None
    url: str
    state: str
    priority: int | None = None  # None for GitHub (no native priority)
    assignee: str | None = None
    team: str | None = None  # Linear team name or GitHub repo name
    labels: list[str] = []
    provider: str  # "linear" | "github"


class Team(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    key: str  # Linear team key or GitHub "owner/repo"
    provider: str


class CreatedIssue(BaseModel):
    """Returned by create_issue — minimal, just what the caller needs."""

    model_config = ConfigDict(frozen=True)

    identifier: str
    title: str
    url: str
    provider: str


class IssueContext(BaseModel):
    """Rendered TASK.md context block for a ticket."""

    model_config = ConfigDict(frozen=True)

    issue: Issue
    rendered: str  # full markdown string, ready to write
