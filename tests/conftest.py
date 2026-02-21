"""Shared test fixtures."""

import pytest

from ctw.models import CreatedIssue, Issue, Team


@pytest.fixture
def linear_issue() -> Issue:
    return Issue(
        id="issue_abc123",
        identifier="ENG-123",
        title="Fix null check in auth middleware",
        description="The middleware throws when session is None.",
        url="https://linear.app/team/issue/ENG-123",
        state="In Progress",
        priority=2,
        assignee="Jane Doe",
        team="Engineering",
        labels=["bug", "auth"],
        provider="linear",
    )


@pytest.fixture
def github_issue() -> Issue:
    return Issue(
        id="987654321",
        identifier="jdoss/quickvm#42",
        title="Fix null check",
        description="Null pointer in logout handler.",
        url="https://github.com/jdoss/quickvm/issues/42",
        state="Open",
        priority=None,
        assignee="jdoss",
        team="jdoss/quickvm",
        labels=["bug"],
        provider="github",
    )


@pytest.fixture
def sample_team() -> Team:
    return Team(id="team_xyz", name="Engineering", key="ENG", provider="linear")


@pytest.fixture
def created_issue() -> CreatedIssue:
    return CreatedIssue(
        identifier="ENG-456",
        title="New issue",
        url="https://linear.app/team/issue/ENG-456",
        provider="linear",
    )
