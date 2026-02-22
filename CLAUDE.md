# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`claude-ticket-wrangler` (`ctw`) is a Python CLI that bridges Linear and GitHub Issues with Claude Code worktrees. It
captures tangential bugs as tickets without breaking flow, fetches ticket context into `TASK.md` files, and integrates
with `wt` (worktrunk) for worktree lifecycle management.

The installed entry point is `ctw`. Slash commands (`/push-ticket`, `/pull-ticket`) in `ctw/commands/` are symlinked
into `~/.claude/commands/` via `ctw install-commands`.

## Commands

```bash
uv sync                    # Install deps
uv tool install -e .       # Install ctw globally

ruff check .               # Lint
ruff format .              # Format (line-length = 119)

pytest -q                  # All tests
pytest tests/test_cli.py   # Single file
pytest tests/providers/    # Provider-specific
pytest -k "test_slug"      # Single test by name

ctw --help                 # CLI reference
ctw init                   # Interactive setup wizard
```

## Architecture

```
ctw/
├── main.py          # All CLI commands (Typer), render_context(), make_slug()
├── models.py        # 4 frozen Pydantic models: Issue, Team, CreatedIssue, IssueContext
├── settings.py      # 5-step config precedence → CtwSettings
└── providers/
    ├── base.py      # TicketProvider ABC
    ├── linear.py    # GraphQL → api.linear.app
    └── github.py    # REST → api.github.com
```

**Request flow:** CLI command → `get_provider(tracker)` → `LinearProvider` or `GitHubProvider` → normalized
`Issue`/`Team` models → rendered markdown or Rich table output.

**Config file** lives at `~/.config/ctw/config.toml`. Config resolution uses a 5-step precedence chain:
`--tracker` CLI flag > `CTW_DEFAULT_TRACKER` env var > `default_tracker` in config.toml > `CTW_PROVIDER` in `.env` >
first profile in config.toml.

## Key Implementation Details

- **Line length is 119**, not the default 88. Set in `pyproject.toml`.
- **tomlkit** is used everywhere TOML is read or written — it preserves comments on round-trip. Don't swap it for
  `tomllib`/`tomli`.
- **All Pydantic models are frozen** (immutable after construction).
- **GitHub `list_my_issues()`** fetches only page 1 (50 issues). No pagination.
- **`make_slug()`** prints without a trailing newline — designed for `$(ctw slug ENG-123)` shell substitution.
- **`configure-wt`** injects a `[post-create]` hook into `.config/wt.toml` that auto-generates `TASK.md` when a
  branch matching a ticket identifier is checked out.

## Testing

- HTTP is mocked with `pytest-httpx` (no patching). Don't use `unittest.mock` for HTTP calls.
- `typer.testing.CliRunner` for CLI command tests.
- `monkeypatch` for env vars and filesystem paths.
- `subprocess.run` is mocked for `gh auth token` calls in GitHub tests.
- Shared fixtures (issues, teams) are in `tests/conftest.py`.

## Providers

Adding a new tracker: subclass `TicketProvider` in `ctw/providers/base.py` and implement `get_issue()`,
`list_my_issues()`, `list_teams()`, and `create_issue()`. Register it in `get_provider()` in `main.py`.
