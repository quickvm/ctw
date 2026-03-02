"""Tests for GitHubProvider using pytest-httpx."""

from unittest.mock import MagicMock, patch

import pytest
from pytest_httpx import HTTPXMock

from ctw.models import Issue, Team
from ctw.providers.github import BASE_URL, GitHubProvider, _repo_from_git_remote
from ctw.settings import CtwSettings


def _settings(**kwargs) -> CtwSettings:
    defaults = {"provider": "github", "github_token": "ghp_test", "github_auth": "token"}
    defaults.update(kwargs)
    return CtwSettings(**defaults)  # type: ignore[call-arg]


_ISSUE_NODE = {
    "id": 987654321,
    "number": 42,
    "title": "Fix null check",
    "body": "Null pointer in logout handler.",
    "html_url": "https://github.com/jdoss/quickvm/issues/42",
    "state": "open",
    "labels": [{"name": "bug"}],
    "assignees": [{"login": "jdoss"}],
}


class TestResolveToken:
    def test_manual_token(self) -> None:
        s = _settings(github_token="ghp_mytoken")
        provider = GitHubProvider(s)
        assert provider._token == "ghp_mytoken"

    def test_ghcli_token(self) -> None:
        s = _settings(github_token=None, github_auth="gh-cli")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ghp_from_cli\n"
        with patch("subprocess.run", return_value=mock_result):
            provider = GitHubProvider(s)
        assert provider._token == "ghp_from_cli"

    def test_ghcli_not_authenticated_raises(self) -> None:
        s = _settings(github_token=None, github_auth="gh-cli")
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="gh auth token failed"):
                GitHubProvider(s)

    def test_no_credentials_raises(self) -> None:
        s = _settings(github_token=None, github_auth="token")
        with pytest.raises(RuntimeError, match="No GitHub credentials"):
            GitHubProvider(s)


class TestParseIssueId:
    def test_fully_qualified(self) -> None:
        provider = GitHubProvider(_settings())
        owner, repo, num = provider._parse_issue_id("jdoss/quickvm#42")
        assert owner == "jdoss"
        assert repo == "quickvm"
        assert num == 42

    def test_bare_number_with_default_repo(self) -> None:
        provider = GitHubProvider(_settings(github_repo="jdoss/quickvm"))
        owner, repo, num = provider._parse_issue_id("42")
        assert owner == "jdoss"
        assert repo == "quickvm"
        assert num == 42

    def test_bare_number_without_default_repo_or_remote_raises(self) -> None:
        provider = GitHubProvider(_settings(github_repo=None))
        no_remote = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=no_remote):
            with pytest.raises(RuntimeError, match="no default repo"):
                provider._parse_issue_id("42")

    def test_bare_number_infers_from_git_remote(self) -> None:
        provider = GitHubProvider(_settings(github_repo=None))
        git_remote = MagicMock(returncode=0, stdout="https://github.com/jdoss/quickvm.git\n")
        with patch("subprocess.run", return_value=git_remote):
            owner, repo, num = provider._parse_issue_id("42")
        assert owner == "jdoss"
        assert repo == "quickvm"
        assert num == 42


class TestRepoFromGitRemote:
    def test_https_github_url(self) -> None:
        m = MagicMock(returncode=0, stdout="https://github.com/jdoss/quickvm.git\n")
        with patch("subprocess.run", return_value=m):
            assert _repo_from_git_remote() == "jdoss/quickvm"

    def test_ssh_github_url(self) -> None:
        m = MagicMock(returncode=0, stdout="git@github.com:jdoss/quickvm.git\n")
        with patch("subprocess.run", return_value=m):
            assert _repo_from_git_remote() == "jdoss/quickvm"

    def test_non_github_remote_returns_none(self) -> None:
        m = MagicMock(returncode=0, stdout="https://gitlab.com/jdoss/quickvm.git\n")
        with patch("subprocess.run", return_value=m):
            assert _repo_from_git_remote() is None

    def test_no_remote_returns_none(self) -> None:
        m = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", return_value=m):
            assert _repo_from_git_remote() is None


def _mock_comments(httpx_mock: HTTPXMock, comments: list | None = None) -> None:
    # No url= — query params (?per_page=50) would cause exact-match failures.
    # Responses are consumed in registration order, so this always matches the
    # second request (comments) after the issue response has been consumed.
    httpx_mock.add_response(json=comments or [])


class TestGetIssue:
    def test_returns_issue_fully_qualified(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json=_ISSUE_NODE)
        _mock_comments(httpx_mock)
        provider = GitHubProvider(_settings())
        issue = provider.get_issue("jdoss/quickvm#42")

        assert isinstance(issue, Issue)
        assert issue.identifier == "jdoss/quickvm#42"
        assert issue.title == "Fix null check"
        assert issue.provider == "github"
        assert issue.priority is None
        assert issue.state == "Open"
        assert issue.labels == ["bug"]

    def test_returns_issue_bare_number(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json=_ISSUE_NODE)
        _mock_comments(httpx_mock)
        provider = GitHubProvider(_settings(github_repo="jdoss/quickvm"))
        issue = provider.get_issue("42")
        assert issue.identifier == "jdoss/quickvm#42"

    def test_returns_issue_bare_number_via_git_remote(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json=_ISSUE_NODE)
        _mock_comments(httpx_mock)
        provider = GitHubProvider(_settings(github_repo=None))
        git_remote = MagicMock(returncode=0, stdout="https://github.com/jdoss/quickvm.git\n")
        with patch("subprocess.run", return_value=git_remote):
            issue = provider.get_issue("42")
        assert issue.identifier == "jdoss/quickvm#42"

    def test_401_raises_with_message(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42",
            status_code=401,
            json={"message": "Bad credentials"},
        )
        provider = GitHubProvider(_settings())
        with pytest.raises(RuntimeError, match="401"):
            provider.get_issue("jdoss/quickvm#42")

    def test_closed_issue_state(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json={**_ISSUE_NODE, "state": "closed"})
        _mock_comments(httpx_mock)
        provider = GitHubProvider(_settings())
        issue = provider.get_issue("jdoss/quickvm#42")
        assert issue.state == "Closed"

    def test_comments_included(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json=_ISSUE_NODE)
        _mock_comments(httpx_mock, [{"user": {"login": "alice"}, "body": "Looks good to me."}])
        provider = GitHubProvider(_settings())
        issue = provider.get_issue("jdoss/quickvm#42")
        assert issue.comments == ["alice: Looks good to me."]

    def test_no_comments_returns_empty(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/repos/jdoss/quickvm/issues/42", json=_ISSUE_NODE)
        _mock_comments(httpx_mock, [])
        provider = GitHubProvider(_settings())
        issue = provider.get_issue("jdoss/quickvm#42")
        assert issue.comments == []


class TestListMyIssues:
    def test_returns_issues(self, httpx_mock: HTTPXMock) -> None:
        # No url= — match any request (query params vary by per_page etc.)
        httpx_mock.add_response(json=[_ISSUE_NODE])
        provider = GitHubProvider(_settings())
        issues = provider.list_my_issues()
        assert len(issues) == 1
        assert issues[0].provider == "github"

    def test_empty(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        provider = GitHubProvider(_settings())
        assert provider.list_my_issues() == []


class TestCreateIssue:
    def test_creates_issue(self, httpx_mock: HTTPXMock) -> None:
        created_node = {
            "number": 99,
            "title": "New bug",
            "html_url": "https://github.com/jdoss/quickvm/issues/99",
        }
        httpx_mock.add_response(
            url=f"{BASE_URL}/repos/jdoss/quickvm/issues",
            json=created_node,
        )
        provider = GitHubProvider(_settings())
        created = provider.create_issue("New bug", "desc", "jdoss/quickvm", None)
        assert created.identifier == "jdoss/quickvm#99"
        assert created.provider == "github"


class TestListTeams:
    def test_returns_repos_with_push(self, httpx_mock: HTTPXMock) -> None:
        # No url= — query params (per_page=100) cause exact URL mismatch
        httpx_mock.add_response(
            json=[
                {
                    "id": 1,
                    "name": "quickvm",
                    "full_name": "jdoss/quickvm",
                    "permissions": {"push": True},
                },
                {
                    "id": 2,
                    "name": "private",
                    "full_name": "jdoss/private",
                    "permissions": {"push": False},
                },
            ],
        )
        provider = GitHubProvider(_settings())
        teams = provider.list_teams()
        assert len(teams) == 1
        assert teams[0].key == "jdoss/quickvm"
        assert isinstance(teams[0], Team)
