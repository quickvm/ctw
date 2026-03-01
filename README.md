# claude-ticket-wrangler (ctw)

A CLI that bridges Linear and GitHub Issues with worktrunk (`wt`) worktree management,
exposed as two Claude Code slash commands: `/push-ticket` and `/pull-ticket`.

**The problem:** mid-session you spot a tangential bug. If you fix it now you muddy your
context. If you don't write it down you forget it. CTW captures it as a ticket in two
keystrokes and queues it in an isolated worktree for later — without breaking your flow.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [worktrunk](https://worktrunk.dev) (`wt`) — git worktree manager
- Claude Code with slash command support
- Linear Personal API Key **and/or** GitHub personal access token or `gh` CLI

GitHub token scopes required:
- `repo` — for private repos (full access)
- `read:user` — to fetch assigned issues
- `public_repo` — sufficient for public repos only

---

## Install

```bash
git clone https://github.com/quickvm/ctw
cd ctw
uv tool install -e .
ctw --help
```

---

## Configuration

CTW resolves the active tracker through a five-step precedence chain (highest wins):

1. `--tracker <profile>` flag on any command
2. `CTW_DEFAULT_TRACKER` environment variable
3. `default_tracker` key in `~/.config/ctw/config.toml`
4. `CTW_PROVIDER` in `.env` in the current working directory
5. First profile defined in `~/.config/ctw/config.toml`

### Option 1: Interactive wizard (recommended)

```bash
ctw init
```

Walks through provider selection, auth, and writes `~/.config/ctw/config.toml`. Also offers
to symlink slash commands and configure `wt` for the current repo.

### Option 2: Manual config file

Create `~/.config/ctw/config.toml`:

```toml
default_tracker = "work"

[work]
provider = "linear"
linear_api_key = "lin_api_work_xxx"
linear_team_id = "team_id_here"

[personal]
provider = "github"
github_auth = "gh-cli"          # use gh CLI — token stays fresh as gh rotates it
github_repo = "jdoss/personal"  # default repo for bare issue numbers (e.g. "42")

[quickvm]
provider = "github"
github_token = "ghp_xxx"        # manual PAT
github_repo = "jdoss/quickvm"
```

`github_auth` values:
- `"token"` (default) — reads `github_token` from config or `CTW_GITHUB_TOKEN` env var
- `"gh-cli"` — calls `gh auth token` at runtime; no token stored on disk

### Option 3: Environment variables

```bash
export CTW_PROVIDER=linear
export CTW_LINEAR_API_KEY=lin_api_xxx
export CTW_LINEAR_TEAM_ID=team_id_here
```

Copy `.env.example` → `.env` in any project directory for per-project overrides.

### Verify config

```bash
ctw config-show
```

Shows all resolved values with masked credentials and marks unset fields.

### Set default tracker

```bash
ctw set-default work
```

Updates `default_tracker` in `~/.config/ctw/config.toml`. Comments and formatting in the file are preserved.

---

## Slash command setup

### Option 1: ctw install-commands (recommended)

```bash
ctw install-commands
```

Creates symlinks in `~/.claude/commands/` pointing to the installed package files. Re-run
after `uv tool install` upgrades to refresh symlinks to the new location.

### Option 2: Manual symlinks

```bash
mkdir -p ~/.claude/commands
ln -sf "$(python -c 'import ctw; print(__import__("pathlib").Path(ctw.__file__).parent)')/commands/push-ticket.md" \
  ~/.claude/commands/push-ticket.md
ln -sf "$(python -c 'import ctw; print(__import__("pathlib").Path(ctw.__file__).parent)')/commands/pull-ticket.md" \
  ~/.claude/commands/pull-ticket.md
```

### Allow list for automatic approvals

The slash commands run `ctw`, `wt`, and `git` shell commands. Add these to
`~/.claude/settings.json` so they run without prompting for approval each time:

```json
{
  "permissions": {
    "allow": [
      "Bash(ctw context *)",
      "Bash(ctw create-issue *)",
      "Bash(ctw slug *)",
      "Bash(ctw spawn *)",
      "Bash(wt list*)",
      "Bash(wt switch *)",
      "Bash(git log --oneline*)",
      "Bash(git status*)",
      "Bash(git diff*)"
    ]
  }
}
```

---

## wt integration

### Automatic setup

```bash
ctw configure-wt
```

Reads `.config/wt.toml` in the current repo (creating it if absent), merges in a
`[post-create]` hook, and writes back — preserving all existing comments and hooks.
Commit the result so everyone on the team gets the hook automatically.

```bash
git add .config/wt.toml && git commit -m "Add CTW worktree hook"
```

The hook runs when `wt switch --create <branch>` creates a new worktree. It detects
ticket identifiers in the branch name and fetches `TASK.md` automatically:

- Linear branches: matches `ENG-123` pattern
- GitHub branches: matches trailing number, requires `CTW_GITHUB_REPO` or `--tracker`

```bash
# Embed a specific tracker profile in the hook script
ctw configure-wt --tracker work

# Overwrite an existing hook
ctw configure-wt --force

# Target a different config file
ctw configure-wt --config path/to/wt.toml
```

Safe to re-run — refuses to overwrite an existing hook without `--force`.

### Manual setup

Copy the snippet from `config/wt.toml.example` into your project's `.config/wt.toml`.

---

## End-to-end workflow

### Linear example

You're deep in a refactor. You spot an auth middleware bug.

```
# In your current Claude Code session:
/push-ticket the logout handler throws a 500 when session is None — stack trace in auth/middleware.py:142 --tracker work
# → "Create a background worktree? [y/N]" → y
# ✓ ENG-456 "Fix auth middleware null pointer" [work] → branch eng-456-fix-auth-middleware (worktree created)
# Resume what you were doing.
```

Later, in a fresh terminal:

```
/pull-ticket ENG-456 --tracker work
# Claude fetches the ticket, switches to the worktree, reads TASK.md, briefs you, and starts.
```

### GitHub example

```
/push-ticket logout button sends 500 when cookie is expired --tracker quickvm
# ✓ jdoss/quickvm#42 "Fix logout 500 on expired cookie" [quickvm] → branch 42-fix-logout-500

# Later (tracker inferred from issue ID format):
/pull-ticket 42
```

### With wt hook

If `configure-wt` was run in a repo, the hook fires automatically:

```bash
wt switch --create eng-456-fix-auth-middleware
# → post-create hook runs
# → Loaded ENG-456 → TASK.md
```

The worktree has `TASK.md` waiting before you even open your editor.

---

## Command reference

| Command | Description |
|---------|-------------|
| `ctw init` | Interactive setup wizard |
| `ctw list-issues [--tracker]` | List issues assigned to me |
| `ctw get-issue <id> [--tracker]` | Show full issue details |
| `ctw create-issue <title> [desc] [--tracker] [--team] [--priority]` | Create issue |
| `ctw list-teams [--tracker]` | List teams or repos |
| `ctw context <id> [--tracker] [-o FILE]` | Render TASK.md context block |
| `ctw slug <id> [--tracker]` | Print git-safe branch name (no newline) |
| `ctw spawn <id> [--tracker] [--background] [--prompt]` | Spawn a Claude agent in the ticket's worktree |
| `ctw set-default <tracker>` | Set default tracker in config.toml |
| `ctw config-show [--tracker]` | Show resolved config with masked credentials |
| `ctw install-commands` | Symlink slash commands to ~/.claude/commands/ |
| `ctw configure-wt [--tracker] [--force] [--config PATH]` | Add post-create hook to .config/wt.toml |

All commands that interact with a provider accept `--tracker / -k <profile>` to override the
active tracker for that invocation.

### Tracker inference

When `--tracker` is not given, CTW infers the provider from the issue ID format:

| ID format | Infers |
|-----------|--------|
| `49` | GitHub — repo from current git remote |
| `ENG-123` | Linear — first Linear profile in config |
| `owner/repo#42` | GitHub — first GitHub profile in config |

### `ctw slug` — shell substitution

`slug` prints with no trailing newline, designed for use in shell substitution:

```bash
git checkout -b $(ctw slug ENG-123 --tracker work)
wt switch --create $(ctw slug jdoss/quickvm#42 --tracker quickvm)
```

Branch name format:
- Linear: `eng-123-fix-null-check-in-auth-middleware` (title truncated at 40 chars)
- GitHub (current repo): `42-fix-null-check` (bare number prefix)
- GitHub (other repo): `jdoss-quickvm-42-fix-null-check` (`/` and `#` replaced with `-`)

---

## License

[MIT](LICENSE) © 2026 QuickVM, LLC
