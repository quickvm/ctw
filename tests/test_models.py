"""Tests for ctw.models."""

import pytest

from ctw.models import CreatedIssue, Issue, IssueContext, Team


def test_issue_frozen(linear_issue: Issue) -> None:
    with pytest.raises(Exception):  # ValidationError or TypeError depending on pydantic version
        linear_issue.title = "changed"  # type: ignore[misc]


def test_issue_defaults() -> None:
    issue = Issue(
        id="1",
        identifier="ENG-1",
        title="Test",
        description=None,
        url="https://example.com",
        state="Open",
        provider="linear",
    )
    assert issue.priority is None
    assert issue.assignee is None
    assert issue.team is None
    assert issue.labels == []


def test_team_frozen(sample_team: Team) -> None:
    with pytest.raises(Exception):
        sample_team.name = "changed"  # type: ignore[misc]


def test_created_issue_frozen(created_issue: CreatedIssue) -> None:
    with pytest.raises(Exception):
        created_issue.title = "changed"  # type: ignore[misc]


def test_issue_context_frozen(linear_issue: Issue) -> None:
    ctx = IssueContext(issue=linear_issue, rendered="# ENG-123")
    with pytest.raises(Exception):
        ctx.rendered = "changed"  # type: ignore[misc]


def test_github_issue_no_priority(github_issue: Issue) -> None:
    assert github_issue.priority is None
    assert github_issue.provider == "github"
