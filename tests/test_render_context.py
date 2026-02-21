"""Tests for render_context."""

from ctw.main import render_context
from ctw.models import Issue


def test_linear_includes_priority(linear_issue: Issue) -> None:
    rendered = render_context(linear_issue)
    assert "**Priority:**" in rendered
    assert "🟠" in rendered  # priority=2 → High


def test_github_omits_priority(github_issue: Issue) -> None:
    rendered = render_context(github_issue)
    assert "**Priority:**" not in rendered


def test_header_format(linear_issue: Issue) -> None:
    rendered = render_context(linear_issue)
    assert rendered.startswith("# ENG-123: Fix null check in auth middleware")


def test_unassigned_label() -> None:
    issue = Issue(
        id="1",
        identifier="ENG-1",
        title="Test",
        description=None,
        url="https://example.com",
        state="Open",
        provider="linear",
        assignee=None,
    )
    rendered = render_context(issue)
    assert "**Assignee:** Unassigned" in rendered


def test_no_description_placeholder() -> None:
    issue = Issue(
        id="1",
        identifier="ENG-1",
        title="Test",
        description=None,
        url="https://example.com",
        state="Open",
        provider="linear",
    )
    rendered = render_context(issue)
    assert "_No description provided._" in rendered


def test_labels_listed(linear_issue: Issue) -> None:
    rendered = render_context(linear_issue)
    assert "bug" in rendered
    assert "auth" in rendered


def test_no_labels_shows_none() -> None:
    issue = Issue(
        id="1",
        identifier="ENG-1",
        title="Test",
        description="desc",
        url="https://example.com",
        state="Open",
        provider="linear",
        labels=[],
    )
    rendered = render_context(issue)
    assert "**Labels:** none" in rendered


def test_provider_linear_label(linear_issue: Issue) -> None:
    rendered = render_context(linear_issue)
    assert "**Provider:** Linear" in rendered


def test_provider_github_label(github_issue: Issue) -> None:
    rendered = render_context(github_issue)
    assert "**Provider:** GitHub" in rendered
