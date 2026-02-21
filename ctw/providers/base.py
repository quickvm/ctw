"""Abstract base class for ticket providers."""

from abc import ABC, abstractmethod

from ctw.models import CreatedIssue, Issue, Team


class TicketProvider(ABC):
    @abstractmethod
    def get_issue(self, issue_id: str) -> Issue: ...

    @abstractmethod
    def list_my_issues(self) -> list[Issue]: ...

    @abstractmethod
    def create_issue(
        self,
        title: str,
        description: str | None,
        team_id: str,
        priority: int | None,
    ) -> CreatedIssue: ...

    @abstractmethod
    def list_teams(self) -> list[Team]: ...
