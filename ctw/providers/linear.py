"""Linear GraphQL API provider."""

import httpx

from ctw.models import CreatedIssue, Issue, Team
from ctw.providers.base import TicketProvider
from ctw.settings import CtwSettings

ENDPOINT = "https://api.linear.app/graphql"

PRIORITY_EMOJI = {0: "—", 1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}

_GET_ISSUE = """
query GetIssue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    url
    priority
    state { name type }
    assignee { name email }
    team { name key }
    labels { nodes { name } }
    comments(first: 50) { nodes { body user { name } } }
    createdAt
    updatedAt
  }
}
"""

_LIST_MY_ISSUES = """
query ListMyIssues {
  viewer {
    assignedIssues(
      filter: { state: { type: { in: [started, unstarted] } } }
      orderBy: updatedAt
    ) {
      nodes {
        id
        identifier
        title
        description
        url
        priority
        state { name type }
        assignee { name email }
        team { name key }
        labels { nodes { name } }
        createdAt
        updatedAt
      }
    }
  }
}
"""

_LIST_TEAMS = """
query ListTeams {
  teams {
    nodes {
      id
      name
      key
    }
  }
}
"""

_CREATE_ISSUE = """
mutation CreateIssue($title: String!, $description: String, $teamId: String!, $priority: Int) {
  issueCreate(input: {
    title: $title
    description: $description
    teamId: $teamId
    priority: $priority
  }) {
    success
    issue {
      id
      identifier
      title
      url
    }
  }
}
"""


class LinearProvider(TicketProvider):
    def __init__(self, settings: CtwSettings) -> None:
        if not settings.linear_api_key:
            raise RuntimeError("linear_api_key is required")
        self._api_key = settings.linear_api_key.get_secret_value()

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        response = httpx.post(
            ENDPOINT,
            json={"query": query, "variables": variables or {}},
            headers={
                "Authorization": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"Linear API error: {data['errors']}")
        return data["data"]

    def _issue_from_node(self, node: dict) -> Issue:
        raw_comments = node.get("comments", {}).get("nodes", [])
        comments = [f"{c['user']['name']}: {c['body']}" for c in raw_comments if c.get("user")]
        return Issue(
            id=node["id"],
            identifier=node["identifier"],
            title=node["title"],
            description=node.get("description"),
            url=node["url"],
            state=node["state"]["name"],
            priority=node.get("priority"),
            assignee=node["assignee"]["name"] if node.get("assignee") else None,
            team=node["team"]["name"] if node.get("team") else None,
            labels=[label["name"] for label in node.get("labels", {}).get("nodes", [])],
            comments=comments,
            provider="linear",
        )

    def get_issue(self, issue_id: str) -> Issue:
        data = self._gql(_GET_ISSUE, {"id": issue_id})
        node = data["issue"]
        if not node:
            raise RuntimeError(f"Issue '{issue_id}' not found in Linear")
        return self._issue_from_node(node)

    def list_my_issues(self) -> list[Issue]:
        data = self._gql(_LIST_MY_ISSUES)
        nodes = data["viewer"]["assignedIssues"]["nodes"]
        return [self._issue_from_node(n) for n in nodes]

    def create_issue(
        self,
        title: str,
        description: str | None,
        team_id: str,
        priority: int | None,
    ) -> CreatedIssue:
        data = self._gql(
            _CREATE_ISSUE,
            {
                "title": title,
                "description": description,
                "teamId": team_id,
                "priority": priority,
            },
        )
        result = data["issueCreate"]
        if not result["success"]:
            raise RuntimeError("Linear issueCreate returned success=false")
        issue = result["issue"]
        return CreatedIssue(
            identifier=issue["identifier"],
            title=issue["title"],
            url=issue["url"],
            provider="linear",
        )

    def list_teams(self) -> list[Team]:
        data = self._gql(_LIST_TEAMS)
        return [Team(id=n["id"], name=n["name"], key=n["key"], provider="linear") for n in data["teams"]["nodes"]]
