"""Tests for make_slug."""

from ctw.main import make_slug
from ctw.models import Issue


def _issue(identifier: str, title: str, provider: str = "linear") -> Issue:
    return Issue(
        id="1",
        identifier=identifier,
        title=title,
        description=None,
        url="https://example.com",
        state="Open",
        provider=provider,
    )


class TestLinearSlug:
    def test_basic(self) -> None:
        assert make_slug(_issue("ENG-123", "Fix null check in auth middleware")) == (
            "eng-123-fix-null-check-in-auth-middleware"
        )

    def test_title_truncated_at_40(self) -> None:
        long_title = "This is a very long title that exceeds forty characters easily"
        slug = make_slug(_issue("ENG-1", long_title))
        # identifier-slug + "-" + title_slug(<=40)
        title_part = slug[len("eng-1-") :]
        assert len(title_part) <= 40

    def test_special_chars_replaced(self) -> None:
        slug = make_slug(_issue("ENG-99", "Fix: null & undefined (edge case)"))
        assert "/" not in slug
        assert ":" not in slug
        assert "&" not in slug
        assert "(" not in slug
        assert ")" not in slug

    def test_no_leading_trailing_hyphens_in_title(self) -> None:
        slug = make_slug(_issue("ENG-1", "---Fix this---"))
        assert not slug.endswith("-")
        # The identifier slug won't start with a hyphen
        parts = slug.split("-", 2)  # eng, 1, rest
        assert parts[0] == "eng"

    def test_empty_title(self) -> None:
        # Edge case: empty title produces only the identifier slug
        slug = make_slug(_issue("ENG-1", ""))
        # Should at minimum be the identifier slug, trailing hyphen stripped
        assert slug.startswith("eng-1")


class TestGitHubSlug:
    def test_basic(self) -> None:
        issue = _issue("jdoss/quickvm#42", "Fix null check", provider="github")
        assert make_slug(issue) == "jdoss-quickvm-42-fix-null-check"

    def test_slash_and_hash_replaced(self) -> None:
        issue = _issue("owner/repo#100", "My bug fix", provider="github")
        slug = make_slug(issue)
        assert "/" not in slug
        assert "#" not in slug

    def test_title_truncated_at_40(self) -> None:
        issue = _issue(
            "owner/repo#1",
            "A very long title that definitely exceeds forty characters in length",
            provider="github",
        )
        slug = make_slug(issue)
        # title part starts after "owner-repo-1-"
        prefix = "owner-repo-1-"
        title_part = slug[len(prefix) :]
        assert len(title_part) <= 40
