"""GitHub REST API v3 provider."""

import subprocess

import httpx

from ctw.models import CreatedIssue, Issue, Team
from ctw.providers.base import TicketProvider
from ctw.settings import CtwSettings

BASE_URL = "https://api.github.com"


class GitHubProvider(TicketProvider):
    def __init__(self, settings: CtwSettings) -> None:
        self._token = self._resolve_token(settings)
        self._default_repo = settings.github_repo
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _resolve_token(self, settings: CtwSettings) -> str:
        if settings.github_auth == "gh-cli":
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError("gh auth token failed. Run: gh auth login")
            return result.stdout.strip()
        if settings.github_token:
            return settings.github_token.get_secret_value()
        raise RuntimeError("No GitHub credentials. Run: ctw init")

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        response = httpx.get(
            f"{BASE_URL}{path}",
            headers=self._headers,
            params=params or {},
            timeout=30,
        )
        if response.status_code == 401:
            raise RuntimeError("GitHub API returned 401. Run ctw init to update credentials for the active profile.")
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, body: dict) -> dict:
        response = httpx.post(
            f"{BASE_URL}{path}",
            headers=self._headers,
            json=body,
            timeout=30,
        )
        if response.status_code == 401:
            raise RuntimeError("GitHub API returned 401. Run ctw init to update credentials for the active profile.")
        response.raise_for_status()
        return response.json()

    def _parse_issue_id(self, issue_id: str) -> tuple[str, str, int]:
        """Parse issue_id into (owner, repo, number).

        Accepts:
        - "owner/repo#123" — fully qualified
        - "123" — bare number, requires self._default_repo
        """
        if "#" in issue_id:
            repo_part, num_str = issue_id.rsplit("#", 1)
            owner, repo = repo_part.split("/", 1)
            return owner, repo, int(num_str)
        # bare number
        if not self._default_repo:
            raise RuntimeError(
                f"Cannot resolve bare issue number '{issue_id}': no default repo set. "
                "Set CTW_GITHUB_REPO or github_repo in your config profile."
            )
        owner, repo = self._default_repo.split("/", 1)
        return owner, repo, int(issue_id)

    def _issue_from_node(self, node: dict, owner: str, repo: str) -> Issue:
        labels = [label["name"] for label in node.get("labels", [])]
        assignees = node.get("assignees", [])
        assignee = assignees[0]["login"] if assignees else None
        state_raw = node.get("state", "open")
        state = "Open" if state_raw == "open" else "Closed"
        return Issue(
            id=str(node["id"]),
            identifier=f"{owner}/{repo}#{node['number']}",
            title=node["title"],
            description=node.get("body"),
            url=node["html_url"],
            state=state,
            priority=None,  # GitHub has no native priority
            assignee=assignee,
            team=f"{owner}/{repo}",
            labels=labels,
            provider="github",
        )

    def get_issue(self, issue_id: str) -> Issue:
        owner, repo, number = self._parse_issue_id(issue_id)
        node = self._get(f"/repos/{owner}/{repo}/issues/{number}")
        return self._issue_from_node(node, owner, repo)  # type: ignore[arg-type]

    def list_my_issues(self) -> list[Issue]:
        # NOTE: fetches page 1 only (up to 50 results). Full pagination not implemented.
        nodes = self._get("/issues", params={"filter": "assigned", "state": "open", "per_page": "50"})
        result = []
        for node in nodes:  # type: ignore[union-attr]
            # /issues returns cross-repo; extract owner/repo from html_url
            # html_url format: https://github.com/owner/repo/issues/123
            parts = node["html_url"].split("/")
            owner, repo = parts[3], parts[4]
            result.append(self._issue_from_node(node, owner, repo))
        return result

    def create_issue(
        self,
        title: str,
        description: str | None,
        team_id: str,  # "owner/repo" for GitHub
        priority: int | None,
    ) -> CreatedIssue:
        owner, repo = team_id.split("/", 1)
        body: dict = {"title": title}
        if description:
            body["body"] = description
        node = self._post(f"/repos/{owner}/{repo}/issues", body)
        return CreatedIssue(
            identifier=f"{owner}/{repo}#{node['number']}",
            title=node["title"],
            url=node["html_url"],
            provider="github",
        )

    def list_teams(self) -> list[Team]:
        # Returns repos where the authenticated user has push access
        repos = self._get("/user/repos", params={"per_page": "100"})
        result = []
        for repo in repos:  # type: ignore[union-attr]
            perms = repo.get("permissions", {})
            if perms.get("push"):
                key = repo["full_name"]
                result.append(
                    Team(
                        id=str(repo["id"]),
                        name=repo["name"],
                        key=key,
                        provider="github",
                    )
                )
        return result
