"""Tests for LinearProvider using pytest-httpx."""

import pytest
from pytest_httpx import HTTPXMock

from ctw.models import Issue, Team
from ctw.providers.linear import ENDPOINT, LinearProvider
from ctw.settings import CtwSettings


def _settings(key: str = "lin_api_test") -> CtwSettings:
    return CtwSettings(  # type: ignore[call-arg]
        provider="linear",
        linear_api_key=key,
    )


_ISSUE_NODE = {
    "id": "issue_abc",
    "identifier": "ENG-123",
    "title": "Fix null check",
    "description": "Desc text",
    "url": "https://linear.app/team/issue/ENG-123",
    "priority": 2,
    "state": {"name": "In Progress", "type": "started"},
    "assignee": {"name": "Jane Doe", "email": "jane@example.com"},
    "team": {"name": "Engineering", "key": "ENG"},
    "labels": {"nodes": [{"name": "bug"}]},
    "createdAt": "2024-01-01T00:00:00Z",
    "updatedAt": "2024-01-02T00:00:00Z",
}


class TestGetIssue:
    def test_returns_issue(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"data": {"issue": _ISSUE_NODE}},
        )
        provider = LinearProvider(_settings())
        issue = provider.get_issue("ENG-123")

        assert isinstance(issue, Issue)
        assert issue.identifier == "ENG-123"
        assert issue.title == "Fix null check"
        assert issue.provider == "linear"
        assert issue.priority == 2
        assert issue.assignee == "Jane Doe"
        assert issue.labels == ["bug"]

    def test_not_found_raises(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"data": {"issue": None}},
        )
        provider = LinearProvider(_settings())
        with pytest.raises(RuntimeError, match="not found"):
            provider.get_issue("ENG-999")


class TestListMyIssues:
    def test_returns_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"data": {"viewer": {"assignedIssues": {"nodes": [_ISSUE_NODE]}}}},
        )
        provider = LinearProvider(_settings())
        issues = provider.list_my_issues()
        assert len(issues) == 1
        assert issues[0].identifier == "ENG-123"

    def test_empty_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"data": {"viewer": {"assignedIssues": {"nodes": []}}}},
        )
        provider = LinearProvider(_settings())
        assert provider.list_my_issues() == []


class TestCreateIssue:
    def test_creates_and_returns(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "new_id",
                            "identifier": "ENG-456",
                            "title": "New bug",
                            "url": "https://linear.app/team/issue/ENG-456",
                        },
                    }
                }
            },
        )
        provider = LinearProvider(_settings())
        created = provider.create_issue("New bug", "desc", "team_id", 3)
        assert created.identifier == "ENG-456"
        assert created.provider == "linear"

    def test_failure_raises(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"data": {"issueCreate": {"success": False, "issue": None}}},
        )
        provider = LinearProvider(_settings())
        with pytest.raises(RuntimeError, match="success=false"):
            provider.create_issue("Fail", None, "team_id", None)


class TestListTeams:
    def test_returns_teams(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={
                "data": {
                    "teams": {
                        "nodes": [
                            {"id": "t1", "name": "Engineering", "key": "ENG"},
                            {"id": "t2", "name": "Design", "key": "DES"},
                        ]
                    }
                }
            },
        )
        provider = LinearProvider(_settings())
        teams = provider.list_teams()
        assert len(teams) == 2
        assert all(isinstance(t, Team) for t in teams)
        assert teams[0].key == "ENG"


class TestGqlError:
    def test_api_error_raises(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            json={"errors": [{"message": "Unauthorized"}]},
        )
        provider = LinearProvider(_settings())
        with pytest.raises(RuntimeError, match="Linear API error"):
            provider.get_issue("ENG-1")
