# claude-ticket-wrangler (CTW) — Reference Specification

This document describes the CTW system as built. It is a reference for understanding the
implementation, not a build prompt.

---

## 1. Project Overview

CTW is a CLI tool that bridges Linear and GitHub Issues with Claude Code workflows. It fetches
ticket context into TASK.md files, generates git-safe branch names, and integrates with the
`wt` (worktrunk) tool for isolated worktree management.

Core problems solved:

- Fetching ticket context into a TASK.md file without leaving the terminal
- Generating consistent, provider-agnostic git branch names from issue identifiers
- Wiring ticket lookup into the worktree post-create hook so context loads automatically
- Providing Claude Code slash commands (`/push-issue`, `/pull-issue`) for in-session ticket
  operations

The tool supports two providers -- **Linear** (GraphQL) and **GitHub Issues** (REST) -- behind a
common abstract interface. Multiple named profiles can coexist in the configuration file,
making it practical to use different trackers across projects.

---

## 2. Directory Structure

```
ctw/                          # repo root
├── pyproject.toml
├── uv.lock
├── ctw/                      # Python package (included in wheel)
│   ├── __init__.py
│   ├── main.py               # Typer app, all CLI commands
│   ├── models.py             # Pydantic data models
│   ├── settings.py           # Config resolution and CtwSettings
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py           # TicketProvider ABC
│   │   ├── linear.py         # LinearProvider
│   │   └── github.py         # GitHubProvider
│   └── commands/             # Claude Code slash command specs (inside the package)
│       ├── push-issue.md
│       └── pull-issue.md
└── tests/
    ├── __init__.py
    ├── conftest.py            # Shared fixtures
    ├── test_cli.py
    ├── test_init.py
    ├── test_models.py
    ├── test_render_context.py
    ├── test_settings.py
    ├── test_slug.py
    └── providers/
        ├── __init__.py
        ├── test_linear.py
        └── test_github.py
```

The `commands/` directory lives inside the `ctw/` package, not at the repo root. This is
intentional: `hatchling` includes `packages = ["ctw"]`, so `ctw/commands/*.md` is bundled
into the wheel and is available after `uv tool install`. The `install-commands` command
resolves `Path(__file__).parent / "commands"` to locate these files at runtime regardless
of where the package is installed.

---

## 3. pyproject.toml

```toml
[project]
name = "claude-ticket-wrangler"
version = "0.1.0"
description = "Linear + GitHub Issues + worktrunk integration for Claude Code workflows"
requires-python = ">=3.11"
dependencies = [
    "httpx",
    "rich",
    "typer",
    "pydantic",
    "pydantic-settings",
    "tomlkit",
]

[project.scripts]
ctw = "ctw.main:app"

[dependency-groups]
dev = [
    "pytest",
    "pytest-httpx",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ctw"]

[tool.ruff]
line-length = 119

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Key dependency notes:

- `tomlkit` is used for all TOML reads and writes throughout the codebase. It preserves
  comments, key ordering, and formatting on round-trip. `tomllib` (stdlib) and `tomli-w` are
  not used anywhere.
- `pydantic-settings` provides env var and `.env` file integration for `CtwSettings`.
- `pytest-httpx` mocks `httpx` HTTP calls in provider tests without patching internals.
- `hatchling` is the build backend. The wheel includes the full `ctw/` package tree, including
  `ctw/commands/*.md`.

---

## 4. Data Models (`ctw/models.py`)

All four models use `ConfigDict(frozen=True)`, making instances immutable after construction.

### `Issue`

The normalized representation of a ticket from any provider.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Provider-native internal ID (Linear UUID or GitHub integer cast to str) |
| `identifier` | `str` | Human-readable identifier: `ENG-123` for Linear, `owner/repo#123` for GitHub |
| `title` | `str` | Issue title |
| `description` | `str \| None` | Issue body. `None` if absent |
| `url` | `str` | Web URL to the issue |
| `state` | `str` | State name: e.g. `"In Progress"` (Linear) or `"Open"` / `"Closed"` (GitHub) |
| `priority` | `int \| None` | Linear priority 0-4. Always `None` for GitHub (no native priority) |
| `assignee` | `str \| None` | Assignee display name (Linear) or login (GitHub). `None` if unassigned |
| `team` | `str \| None` | Linear team name or GitHub `owner/repo` string |
| `labels` | `list[str]` | Label names. Defaults to `[]` |
| `provider` | `str` | `"linear"` or `"github"` |

### `Team`

Represents a Linear team or a GitHub repository with push access.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Provider-native ID |
| `name` | `str` | Display name |
| `key` | `str` | Linear team key (e.g. `"ENG"`) or GitHub `owner/repo` |
| `provider` | `str` | `"linear"` or `"github"` |

### `CreatedIssue`

Minimal return value from `create_issue`. Contains only what the caller needs after creation.

| Field | Type | Description |
|-------|------|-------------|
| `identifier` | `str` | `ENG-456` or `owner/repo#99` |
| `title` | `str` | Issue title as created |
| `url` | `str` | Web URL |
| `provider` | `str` | `"linear"` or `"github"` |

### `IssueContext`

Pairs a fetched `Issue` with its rendered markdown string, ready to write to TASK.md.

| Field | Type | Description |
|-------|------|-------------|
| `issue` | `Issue` | The source issue |
| `rendered` | `str` | Full markdown string produced by `render_context()` |

---

## 5. Provider Interface (`ctw/providers/base.py`)

```python
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
```

Both `LinearProvider` and `GitHubProvider` implement this interface. The `team_id` parameter
convention differs by provider:

- Linear: `team_id` is the Linear team UUID
- GitHub: `team_id` is the `owner/repo` string

---

## 6. Settings (`ctw/settings.py`)

### `CtwSettings`

Built on `pydantic-settings.BaseSettings` with `env_prefix = "CTW_"` and `env_file = ".env"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_tracker` | `str \| None` | `None` | Active profile name |
| `provider` | `str` | `"linear"` | `"linear"` or `"github"` |
| `linear_api_key` | `SecretStr \| None` | `None` | Linear Personal API Key |
| `linear_team_id` | `str \| None` | `None` | Default Linear team ID for `create-issue` |
| `github_token` | `SecretStr \| None` | `None` | GitHub Personal Access Token |
| `github_auth` | `str` | `"token"` | `"token"` or `"gh-cli"` |
| `github_repo` | `str \| None` | `None` | Default repo (`owner/repo`) for bare issue numbers |

Env var names are derived by uppercasing the field name and prepending `CTW_`:
`CTW_PROVIDER`, `CTW_LINEAR_API_KEY`, `CTW_GITHUB_TOKEN`, etc.

### 5-Step Precedence Chain

`get_settings(tracker=None)` resolves the active tracker profile in this order:

1. `tracker` argument -- the `--tracker` CLI flag value passed by the caller
2. `CTW_DEFAULT_TRACKER` env var -- read from the process environment
3. `default_tracker` key in `~/.config/ctw/config.toml` -- the TOML document top-level key
4. `CTW_PROVIDER` in `.env` in cwd -- read by `_cwd_env_provider()`, which scans the file
   line-by-line without instantiating a full settings object (avoids circular construction)
5. First profile in `~/.config/ctw/config.toml` -- the first key whose value is a `Mapping`

Step 4 reads `.env` manually rather than relying on pydantic-settings to avoid ordering
ambiguity. Step 5 uses `_list_profiles()` to enumerate profiles.

### `_list_profiles(config)`

```python
def _list_profiles(config: Mapping) -> list[str]:
    return [k for k, v in config.items() if isinstance(v, Mapping)]
```

Uses `isinstance(v, Mapping)` rather than `isinstance(v, dict)` because tomlkit `Table`
objects implement `MutableMapping` but are not `dict` instances. This correctly identifies
profile sections while skipping scalar keys like `default_tracker`.

### tomlkit Round-Trip

`_load_toml()` uses `tomlkit.load()`, returning a `TOMLDocument`. This is cached with
`@lru_cache(maxsize=1)`. The cache must be cleared between tests using
`settings_module._load_toml.cache_clear()`.

When `get_settings()` builds `CtwSettings` from a profile, it converts the tomlkit table to
a plain dict first:

```python
profile_defaults = dict(tomlkit_config[active])
settings = CtwSettings(**profile_defaults)
```

This is required because pydantic-settings does not accept tomlkit proxy objects for field
values.

### Credential Validation

After constructing `CtwSettings`, `get_settings()` validates credentials for the resolved
provider and calls `typer.Exit(1)` with a clear message if they are missing:

- `provider == "linear"` and `linear_api_key` is `None`: error, print message with config path
- `provider == "github"` and `github_auth == "token"` and `github_token` is `None`: error
- `provider == "github"` and `github_auth == "gh-cli"`: no token required; gh-cli is called
  at runtime by the provider

### Config File Location

```python
CONFIG_PATH = Path.home() / ".config" / "ctw" / "config.toml"
```

Example config file structure:

```toml
default_tracker = "work"

[work]
provider = "linear"
linear_api_key = "lin_api_..."
linear_team_id = "team_abc123"

[personal]
provider = "github"
github_auth = "token"
github_token = "ghp_..."
github_repo = "jdoss/quickvm"
```

---

## 7. Linear Provider (`ctw/providers/linear.py`)

### Endpoint

```python
ENDPOINT = "https://api.linear.app/graphql"
```

All requests are POST to this single endpoint. The `Authorization` header is the raw API key
(no `Bearer` prefix -- Linear accepts the key directly).

### GraphQL Query Constants

Four module-level string constants define the GraphQL operations:

`_GET_ISSUE` -- `query GetIssue($id: String!)` -- fetches a single issue by its identifier.
Fields: `id`, `identifier`, `title`, `description`, `url`, `priority`,
`state { name type }`, `assignee { name email }`, `team { name key }`,
`labels { nodes { name } }`, `createdAt`, `updatedAt`.

`_LIST_MY_ISSUES` -- `query ListMyIssues` -- fetches issues assigned to the authenticated
user where state type is `started` or `unstarted`, ordered by `updatedAt`. Returns the same
field set as `_GET_ISSUE`.

`_LIST_TEAMS` -- `query ListTeams` -- fetches all teams with `id`, `name`, `key`.

`_CREATE_ISSUE` -- `mutation CreateIssue(...)` -- creates an issue with `title`,
`description`, `teamId`, `priority`. Returns `success` boolean and the created issue's
`id`, `identifier`, `title`, `url`.

### Priority Mapping

```python
PRIORITY_EMOJI = {0: "—", 1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}
```

This is defined in `linear.py` for reference. The display mapping used in `main.py` is:

```python
_PRIORITY_LABEL = {0: "— (No priority)", 1: "🔴 Urgent", 2: "🟠 High", 3: "🟡 Medium", 4: "🟢 Low"}
```

### Methods

`_gql(query, variables)` -- POSTs to the endpoint, raises on HTTP errors, raises
`RuntimeError` if the response body contains an `"errors"` key, returns `data["data"]`.

`_issue_from_node(node)` -- Converts a GraphQL issue node dict to an `Issue`. Sets
`provider="linear"`. Extracts `assignee["name"]`, `team["name"]`, and label names from the
nested nodes structure.

`get_issue(issue_id)` -- Calls `_GET_ISSUE` with `{"id": issue_id}`. Raises `RuntimeError`
if the returned `issue` node is `None` (not found).

`list_my_issues()` -- Calls `_LIST_MY_ISSUES`, returns all nodes from
`viewer.assignedIssues.nodes`.

`create_issue(title, description, team_id, priority)` -- Calls `_CREATE_ISSUE`. Raises
`RuntimeError` if `issueCreate.success` is `False`.

`list_teams()` -- Calls `_LIST_TEAMS`, returns a `Team` for each node with
`provider="linear"`.

---

## 8. GitHub Provider (`ctw/providers/github.py`)

### Endpoint

```python
BASE_URL = "https://api.github.com"
```

Uses GitHub REST API v3. All requests include:

```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
```

### `_resolve_token(settings)`

Called in `__init__`. Two paths:

- `github_auth == "gh-cli"`: runs `subprocess.run(["gh", "auth", "token"], ...)` and strips
  stdout. Raises `RuntimeError("gh auth token failed. Run: gh auth login")` if returncode != 0.
- `github_auth == "token"` (default): returns `settings.github_token.get_secret_value()`.
  Raises `RuntimeError("No GitHub credentials. Run: ctw init")` if token is `None`.

### `_parse_issue_id(issue_id)`

Returns `(owner, repo, number)` as `(str, str, int)`.

Accepts two formats:

- Fully qualified: `"owner/repo#123"` -- splits on `"#"` using `rsplit("#", 1)`, then
  splits the left part on `"/"`.
- Bare number: `"123"` -- uses `self._default_repo` (from `settings.github_repo`). Raises
  `RuntimeError` if no default repo is configured.

### HTTP helpers

`_get(path, params)` -- GET to `BASE_URL + path`. Raises `RuntimeError` with actionable
message on 401. Otherwise calls `raise_for_status()`.

`_post(path, body)` -- POST with JSON body. Same 401 handling.

### `_issue_from_node(node, owner, repo)`

Converts a GitHub REST issue object to an `Issue`:

- `identifier`: `f"{owner}/{repo}#{node['number']}"`
- `state`: `"Open"` if `node["state"] == "open"` else `"Closed"`
- `assignee`: first entry from `node["assignees"]` list, by login. `None` if empty.
- `team`: `f"{owner}/{repo}"`
- `priority`: always `None`
- `provider`: `"github"`

### Methods

`get_issue(issue_id)` -- Calls `_parse_issue_id()`, then GET
`/repos/{owner}/{repo}/issues/{number}`.

`list_my_issues()` -- GET `/issues` with params
`{"filter": "assigned", "state": "open", "per_page": "50"}`. Returns page 1 only (up to 50
results). Extracts `owner` and `repo` from `html_url` by splitting on `"/"` and taking
indices 3 and 4 (format: `https://github.com/{owner}/{repo}/issues/{number}`).

`create_issue(title, description, team_id, priority)` -- `team_id` is `owner/repo`. POSTs
to `/repos/{owner}/{repo}/issues` with `title` and optionally `body`. `priority` is accepted
but silently ignored (GitHub has no native priority field).

`list_teams()` -- GET `/user/repos` with `per_page=100`. Filters to repos where
`permissions.push` is truthy. Returns `Team` objects with `key = repo["full_name"]`.

---

## 9. CLI Commands (`ctw/main.py`)

The Typer app is exposed as `ctw` via the `[project.scripts]` entry point. All commands that
interact with a provider accept `--tracker` / `-k` to select a named config profile.

```python
TrackerOpt = Annotated[
    str | None,
    typer.Option("--tracker", "-k", help="Profile name from ~/.config/ctw/config.toml"),
]
```

### `list-issues`

```
ctw list-issues [--tracker PROFILE]
```

Calls `provider.list_my_issues()` and renders a Rich table with columns: ID, State, Pri,
Title, URL. Priority column uses `_PRIORITY_LABEL` mapping. GitHub issues show `"—"` for
priority.

### `get-issue`

```
ctw get-issue ISSUE_ID [--tracker PROFILE]
```

Calls `provider.get_issue(issue_id)` and renders a two-column Rich table (Field, Value) with
all issue fields. The Priority row is only shown for Linear issues (`issue.provider == "linear"`
and `issue.priority is not None`).

### `create-issue`

```
ctw create-issue TITLE [DESCRIPTION] [--tracker PROFILE] [--team TEAM_ID] [--priority 1-4]
```

Team resolution order: `--team` flag > `settings.linear_team_id` > `settings.github_repo`.
Exits with error if none are set, directing the user to `ctw list-teams`.

Priority defaults to `3` (Medium). For GitHub issues, priority is set to `None` before
calling the provider, and a dim informational message is printed.

Output on success:

```
✓ ENG-456 Fix auth middleware null check
  https://linear.app/...
```

### `list-teams`

```
ctw list-teams [--tracker PROFILE]
```

Calls `provider.list_teams()` and renders a Rich table with columns: Key, Name, ID.

### `context`

```
ctw context ISSUE_ID [--tracker PROFILE] [--output/-o FILE]
```

Fetches the issue and calls `render_context()` to produce a TASK.md-style markdown string.
If `--output` is provided, writes to that file and prints a confirmation. Otherwise prints to
stdout. The output is wrapped in an `IssueContext` model before use.

The rendered format is:

```markdown
# ENG-123: Fix null check in auth middleware

**Provider:** Linear
**State:** In Progress
**Team:** Engineering
**Assignee:** Jane Doe
**Priority:** 🟠 High
**Labels:** bug, auth
**URL:** https://linear.app/...

## Description

The middleware throws when session is None.
```

Priority line is omitted for GitHub issues. Assignee falls back to `"Unassigned"`. Labels
fall back to `"none"`. Missing description renders as `"_No description provided._"`.

### `slug`

```
ctw slug ISSUE_ID [--tracker PROFILE]
```

Fetches the issue and calls `make_slug()`. Prints the result with no trailing newline
(uses `typer.echo(..., nl=False)`), designed for shell substitution:

```sh
git checkout -b $(ctw slug ENG-123)
```

`make_slug()` behavior:

```python
def make_slug(issue: Issue) -> str:
    identifier_slug = _slugify(issue.identifier)
    title_slug = _slugify(issue.title, max_len=40)
    return f"{identifier_slug}-{title_slug}"
```

`_slugify()` lowercases, replaces any non-alphanumeric run with a single `-`, strips leading
and trailing hyphens, and optionally truncates the title portion to `max_len` characters (then
strips any trailing hyphen from truncation).

Examples:
- Linear: `ENG-123` + `"Fix null check in auth middleware"` -> `eng-123-fix-null-check-in-auth-middleware`
- GitHub: `jdoss/quickvm#42` + `"Fix null check"` -> `jdoss-quickvm-42-fix-null-check`

### `set-default`

```
ctw set-default PROFILE_NAME
```

Sets `default_tracker` in `~/.config/ctw/config.toml` using tomlkit round-trip (preserves
existing comments and formatting).

Behavior:

- If the config file does not exist: creates it with only `default_tracker = PROFILE_NAME`.
- If it exists: validates that `PROFILE_NAME` appears as a profile section (`_list_profiles()`
  check). Exits with error if not found, listing available profiles.
- On success: writes the updated document back with `tomlkit.dumps()`.

### `config-show`

```
ctw config-show [--tracker PROFILE]
```

Calls `get_settings()` and renders a Rich table of all settings fields. Credential values are
masked: shows `"***"` for values of 5 chars or fewer, otherwise shows `"...{last5chars}"`.
`None` values render as `"(not set)"` in dim style.

Catches `SystemExit` from `get_settings()` credential validation and returns cleanly.

### `install-commands`

```
ctw install-commands
```

Symlinks all `*.md` files from `ctw/commands/` (resolved relative to `__file__`) into
`~/.claude/commands/`. Creates the destination directory if needed. Replaces any existing
symlinks or files at the destination path before creating the new symlink.

### `configure-wt`

```
ctw configure-wt [--tracker PROFILE] [--force] [--config PATH]
```

Writes a `ctw-context` entry into the `[post-create]` table of a wt config file.

Default config path is `.config/wt.toml` (relative to cwd). Override with `--config`.

Behavior:

1. Warns if `wt` is not on PATH (non-fatal).
2. Loads the existing file with `tomlkit.load()` if it exists, otherwise starts with an empty
   `tomlkit.document()`.
3. Checks for an existing `ctw-context` key in `[post-create]`. If present and `--force` is
   not set: prints a warning and exits with code 0 (no-op). If `--force` is set: overwrites.
4. Ensures `[post-create]` table exists in the document.
5. Sets `doc["post-create"]["ctw-context"]` to the hook value produced by `_wt_hook_value()`.
6. Writes the updated document back with `tomlkit.dumps()`.
7. Prints a reminder to commit the file.

The `--tracker` flag, if provided, is embedded into the hook script as a hardcoded
`--tracker PROFILE` argument to `ctw context`. If omitted, the hook relies on the default
profile resolution at runtime.

#### `_wt_hook_value(tracker)`

Creates a tomlkit multiline string item for the hook:

```python
def _wt_hook_value(tracker: str | None) -> tomlkit.items.Item:
    content = _build_wt_hook(tracker)
    fragment = tomlkit.parse(f'x = """\n{content}\n"""')
    return fragment["x"]
```

The fragment trick parses a minimal TOML document to obtain a properly typed tomlkit
`MultilineString` item, which serializes correctly when assigned to another document's key.

#### Hook Template

The hook script written into `wt.toml` detects issue identifiers in the branch name:

```sh
  # Linear-style: ENG-123
  TICKET=$(echo '{{ branch }}' | grep -oE '[A-Z]+-[0-9]+' | head -1)

  # GitHub-style: owner-repo-42 (requires CTW_GITHUB_REPO or --tracker profile)
  if [ -z "$TICKET" ] && [ -n "$CTW_GITHUB_REPO" ]; then
    NUMBER=$(echo '{{ branch }}' | grep -oE '[0-9]+' | tail -1)
    [ -n "$NUMBER" ] && TICKET="${CTW_GITHUB_REPO}#${NUMBER}"
  fi

  if [ -n "$TICKET" ] && command -v ctw &>/dev/null; then
    ctw context "$TICKET"[--tracker PROFILE] -o TASK.md && echo "Loaded $TICKET -> TASK.md"
  fi
```

`{{ branch }}` is a wt template variable. The `[--tracker PROFILE]` suffix is present only
when `--tracker` was passed to `configure-wt`.

### `init`

```
ctw init
```

Interactive first-time setup wizard. Uses `typer.prompt()` and `typer.confirm()` throughout.
Writes results to `~/.config/ctw/config.toml` using tomlkit round-trip.

Steps:

1. Prompt: provider (`linear` / `github`). Exits if invalid.
2. Prompt: profile name. Exits if empty.
3. Provider-specific auth:
   - **Linear**: prompts for API key (hidden input). Optionally calls `LP(settings).list_teams()`
     to verify the key works. Prints count of teams found or a warning on failure.
   - **GitHub, gh-cli**: runs `gh auth status`. Exits if non-zero. Stores `github_auth = "gh-cli"`.
     No token is stored.
   - **GitHub, token**: prompts for PAT (hidden input). Stores `github_token` and
     `github_auth = "token"`. Prompts for default repo (`owner/repo`, optional).
4. Confirm: set as default tracker?
5. Confirm: symlink slash commands to `~/.claude/commands/`?
6. Writes the profile section to config using tomlkit. If the file already exists, loads it
   first (round-trip preserves existing profiles and comments).
7. If set as default: writes `default_tracker = profile_name` to the document.
8. If install confirmed: calls `install_commands()`.
9. Calls `config_show(tracker=profile_name)` to display the resolved configuration.

---

## 10. Slash Commands

The `commands/` directory contains markdown files that define Claude Code slash command
behavior. They are installed into `~/.claude/commands/` by `ctw install-commands`.

### `/push-issue`

File: `ctw/commands/push-issue.md`

Captures a tangential issue as a ticket without switching context.

**Usage patterns:**
```
/push-issue
/push-issue the logout button throws 500 when session is expired
/push-issue --tracker personal
/push-issue the logout bug --tracker quickvm
```

**Behavior:**

1. Parse `--tracker <profile>` from the invocation first. Strip it from the remaining input.
2. The remainder is the inline description (may be empty).
3. If no description: ask exactly one question -- one-sentence description or `summarize`.
   - If `summarize`: infer title and description from session context (recent edits, errors,
     tool calls). No follow-up questions.
4. Derive a title of 60 chars or fewer from the description.
5. Run: `ctw create-issue "<title>" "<description>" [--tracker <profile>]`
6. After ticket creation, ask one yes/no: "Create a background worktree now? [y/N]"
   - If yes: run `ctw slug <TICKET_ID> [--tracker <profile>]` then
     `wt switch --create <branch-name>`. Do not switch into the new worktree.
7. Output exactly one summary line then stop:
   ```
   ✓ ENG-456 "Fix auth middleware null check" [work] -> branch eng-456-fix-auth-middleware (worktree created)
   Resume what you were doing.
   ```
   Omit `(worktree created)` if declined. `[work]` is the tracker profile used.

**Hard constraints:**
- Never switch worktrees or modify files in the current session.
- Never ask more than one clarifying question total.
- Ticket description must be fully self-contained (file paths, expected vs. actual, error
  messages). A fresh Claude Code session with zero context must be able to act on it.
- If `ctw` is not on PATH, fail immediately:
  ```
  Error: ctw not found. Install with: cd /home/jdoss/src/quickvm/ctw && uv tool install -e .
  ```

### `/pull-issue`

File: `ctw/commands/pull-issue.md`

Loads a ticket into an isolated worktree and begins work immediately.

**Usage patterns:**
```
/pull-issue ENG-456
/pull-issue jdoss/quickvm#42
/pull-issue ENG-456 --tracker work
/pull-issue ENG-456 --no-worktree
```

**Behavior:**

1. Parse `--tracker <profile>` and `--no-worktree` flags, then the ticket ID.
   If no ticket ID: print error with usage and stop.
2. Run `ctw context <TICKET_ID> [--tracker <profile>] -o TASK.md`
3. Unless `--no-worktree`:
   - Run `ctw slug <TICKET_ID> [--tracker <profile>]` to get branch name
   - Run `wt list | grep <branch-name>` to check existence
   - If exists: `wt switch <branch-name>`
   - If not: `wt switch --create <branch-name>`
4. Read `TASK.md` fully.
5. Run `git log --oneline -5` and `git status`
6. If commits exist beyond main: run `git diff main...HEAD`
7. Output this exact briefing:
   ```
   ## <identifier>: <title>

   **Tracker:** <profile name used>
   **Provider:** <Linear | GitHub>
   **What:** <1-2 sentence problem summary>
   **Where:** <likely relevant files/directories inferred from ticket description>
   **State:** <"No prior work" | "X commits ahead of main: <one-line summary>">

   Starting with: <one sentence describing your first action>
   ```
8. Begin work immediately after the briefing. No confirmation prompt.

**Hard constraints:**
- Never ask clarifying questions before starting. TASK.md is the source of truth.
- If `ctw` or `wt` is not on PATH: fail immediately naming what is missing.
- The briefing is for situational awareness only -- do not wait for user confirmation.

---

## 11. wt Integration

### What `configure-wt` Detects

The post-create hook inspects the branch name using two regex patterns:

- **Linear**: `[A-Z]+-[0-9]+` (e.g. `ENG-123`) -- matched with `grep -oE`, takes the first
  match via `head -1`.
- **GitHub**: `[0-9]+` at the end of the branch name -- takes the last numeric segment via
  `tail -1`. Only attempted if the Linear pattern matched nothing and `CTW_GITHUB_REPO` is set
  in the environment. Constructs `owner/repo#NUMBER` using the env var value.

### Hook Location in wt.toml

```toml
[post-create]
ctw-context = """
  # ... hook script ...
"""
```

The hook is keyed as `ctw-context` within the `[post-create]` table. This is also the key
checked for collision detection (`"ctw-context" in post_create`).

### `--tracker` Embedding

When `configure-wt --tracker PROFILE` is used, the profile name is baked into the hook
script:

```sh
ctw context "$TICKET" --tracker PROFILE -o TASK.md
```

Without `--tracker`, the hook uses:

```sh
ctw context "$TICKET" -o TASK.md
```

In the latter case, profile selection at hook runtime follows the normal 5-step precedence
chain (env vars, `CTW_GITHUB_REPO` for GitHub, or the config file default).

### `CTW_GITHUB_REPO` in the Hook

The GitHub branch pattern requires `CTW_GITHUB_REPO` to be set as an environment variable
in the shell that runs the worktree hook. This is separate from the `github_repo` config
field, which is used by CTW's own settings resolution.

---

## 12. Test Suite

Tests live in `tests/` mirroring the package structure. Run with `pytest -q`.

### Test Infrastructure

`tests/conftest.py` -- Shared fixtures available to all test modules:

- `linear_issue` -- a fully populated `Issue` with `provider="linear"`, `priority=2`,
  `labels=["bug", "auth"]`
- `github_issue` -- a fully populated `Issue` with `provider="github"`, `priority=None`,
  `labels=["bug"]`
- `sample_team` -- a `Team` with `provider="linear"`
- `created_issue` -- a `CreatedIssue` with `provider="linear"`

LRU cache reset -- `settings_module._load_toml.cache_clear()` is called as an `autouse`
fixture in `test_cli.py`, `test_settings.py`, and `test_init.py`. Without this, a cached
TOML document from one test would bleed into another.

### Provider Tests (`tests/providers/`)

Both provider test modules use `pytest-httpx` via the `httpx_mock: HTTPXMock` fixture, which
intercepts `httpx` requests without patching internals.

`test_linear.py` covers:

- `TestGetIssue`: happy path returning a populated `Issue`; null node raises `RuntimeError`
- `TestListMyIssues`: list with one node; empty list
- `TestCreateIssue`: success returns `CreatedIssue`; `success=False` raises `RuntimeError`
- `TestListTeams`: two teams returned correctly
- `TestGqlError`: response with `"errors"` key raises `RuntimeError("Linear API error")`

`test_github.py` covers:

- `TestResolveToken`: manual token path; gh-cli path (mocks `subprocess.run`); gh-cli not
  authenticated raises; no credentials raises
- `TestParseIssueId`: fully qualified `owner/repo#N`; bare number with default repo; bare
  number without default repo raises
- `TestGetIssue`: fully qualified ID; bare number with default repo; 401 raises; closed state
  maps to `"Closed"`
- `TestListMyIssues`: single result; empty list
- `TestCreateIssue`: POST returns new issue identifier
- `TestListTeams`: filters to repos with `push` permission

### Settings Tests (`tests/test_settings.py`)

Tests all five precedence steps by monkeypatching `CONFIG_PATH` and environment variables:

- `tracker` arg overrides `default_tracker` from TOML
- `CTW_DEFAULT_TRACKER` env var overrides TOML `default_tracker`
- TOML `default_tracker` used when no arg or env var
- First profile used when no `default_tracker` defined
- Missing profile name exits
- Missing `linear_api_key` exits for `provider=linear`
- Missing `github_token` exits for `provider=github, github_auth=token`
- `github_auth=gh-cli` skips token validation and does not exit
- No config file at all: returns defaults (credentials supplied via env vars)

Uses tomlkit to write fixture config files:

```python
def _write_config(tmp_path: Path, config: dict) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(tomlkit.dumps(config))
    return config_path
```

### CLI Tests (`tests/test_cli.py`)

Uses `typer.testing.CliRunner` to invoke commands. Mocks `get_provider` to return a
`MagicMock` with pre-configured return values, avoiding any network calls or credential
resolution.

Commands covered: `list-issues`, `get-issue` (including GitHub priority omission),
`create-issue` (with team; without team exits), `list-teams`, `context` (stdout and file),
`slug` (no trailing newline), `set-default` (creates file; validates profile exists),
`configure-wt` (five scenarios: new file, merge preserving comments, refuse without force,
force overwrite, tracker embedding), `install-commands`.

### Init Tests (`tests/test_init.py`)

Uses `CliRunner` with the `input=` parameter to simulate interactive prompts. Three scenarios:

- Linear profile: writes `provider`, `linear_api_key`; verifies key value in TOML
- GitHub + gh-cli: verifies `github_auth = "gh-cli"` is written; verifies no `github_token`
  key present; verifies gh-cli failure exits non-zero
- GitHub + token: verifies `github_token`, `github_auth`, and `github_repo` written correctly

### Model Tests (`tests/test_models.py`)

Verifies that all four models are frozen (mutation raises). Verifies `Issue` field defaults.
Verifies GitHub issue has `priority=None`.

### Render Context Tests (`tests/test_render_context.py`)

Tests `render_context()` directly:

- Linear includes `**Priority:**` with emoji; GitHub omits it
- Header format: `# ENG-123: <title>`
- `None` assignee renders as `"Unassigned"`
- `None` description renders as `"_No description provided._"`
- Labels listed as comma-separated string; empty list renders as `"none"`
- Provider label: `"Linear"` or `"GitHub"`

### Slug Tests (`tests/test_slug.py`)

Tests `make_slug()` for both Linear and GitHub identifiers:

- Basic concatenation
- Title truncated at 40 characters
- Special characters (`/`, `#`, `:`, `&`, `(`, `)`) replaced with `-`
- No leading or trailing hyphens
- Empty title edge case
