"""CTW CLI — all commands."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import tomlkit
import typer
from rich import print as rprint
from rich.table import Table

from ctw.models import Issue, IssueContext
from ctw.providers.base import TicketProvider
from ctw.providers.github import GitHubProvider
from ctw.providers.linear import LinearProvider
from ctw.settings import CONFIG_PATH, CtwSettings, _list_profiles, get_settings

app = typer.Typer(help="claude-ticket-wrangler: Linear + GitHub Issues + wt integration", no_args_is_help=True)

TrackerOpt = Annotated[
    str | None,
    typer.Option("--tracker", "-k", help="Profile name from ~/.config/ctw/config.toml"),
]

# Hook written into .config/wt.toml [post-create] by configure-wt.
# Detects Linear identifiers (ENG-123) and GitHub issue numbers from the branch name,
# then fetches ticket context into TASK.md.
_WT_HOOK_TEMPLATE = """\
  # Linear-style: ENG-123
  TICKET=$(echo '{{{{ branch }}}}' | grep -oE '[A-Z]+-[0-9]+' | head -1)

  # GitHub-style: owner-repo-42 (requires CTW_GITHUB_REPO or --tracker profile)
  if [ -z "$TICKET" ] && [ -n "$CTW_GITHUB_REPO" ]; then
    NUMBER=$(echo '{{{{ branch }}}}' | grep -oE '[0-9]+' | tail -1)
    [ -n "$NUMBER" ] && TICKET="${{CTW_GITHUB_REPO}}#${{NUMBER}}"
  fi

  if [ -n "$TICKET" ] && command -v ctw &>/dev/null; then
    ctw context "$TICKET"{tracker_flag} -o TASK.md && echo "Loaded $TICKET → TASK.md"
  fi"""


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def get_provider(tracker: str | None = None) -> TicketProvider:
    settings = get_settings(tracker=tracker)
    match settings.provider:
        case "linear":
            return LinearProvider(settings)
        case "github":
            return GitHubProvider(settings)
        case _:
            rprint(f"[red]Unknown provider '{settings.provider}'. Valid: linear, github[/red]")
            raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 0) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def make_slug(issue: Issue) -> str:
    """Return a git-safe branch name for the issue.

    Linear:  ENG-123 → eng-123-fix-null-check-in-auth-middleware
    GitHub:  jdoss/quickvm#42 → jdoss-quickvm-42-fix-null-check
    """
    identifier_slug = _slugify(issue.identifier)
    title_slug = _slugify(issue.title, max_len=40)
    return f"{identifier_slug}-{title_slug}"


# ---------------------------------------------------------------------------
# Context rendering
# ---------------------------------------------------------------------------

_PRIORITY_LABEL = {0: "— (No priority)", 1: "🔴 Urgent", 2: "🟠 High", 3: "🟡 Medium", 4: "🟢 Low"}


def render_context(issue: Issue) -> str:
    """Render a TASK.md-style markdown block for the issue."""
    provider_label = "Linear" if issue.provider == "linear" else "GitHub"
    assignee = issue.assignee or "Unassigned"
    labels = ", ".join(issue.labels) if issue.labels else "none"
    description = issue.description or "_No description provided._"

    lines = [
        f"# {issue.identifier}: {issue.title}",
        "",
        f"**Provider:** {provider_label}",
        f"**State:** {issue.state}",
        f"**Team:** {issue.team or '—'}",
        f"**Assignee:** {assignee}",
    ]

    if issue.provider == "linear" and issue.priority is not None:
        priority_label = _PRIORITY_LABEL.get(issue.priority, str(issue.priority))
        lines.append(f"**Priority:** {priority_label}")

    lines += [
        f"**Labels:** {labels}",
        f"**URL:** {issue.url}",
        "",
        "## Description",
        "",
        description,
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# wt hook helpers
# ---------------------------------------------------------------------------


def _build_wt_hook(tracker: str | None) -> str:
    tracker_flag = f" --tracker {tracker}" if tracker else ""
    return _WT_HOOK_TEMPLATE.format(tracker_flag=tracker_flag)


def _wt_hook_value(tracker: str | None) -> tomlkit.items.Item:
    """Return a tomlkit multiline string item for the wt post-create hook."""
    content = _build_wt_hook(tracker)
    # Parse a minimal TOML fragment to get a properly typed multiline string item
    fragment = tomlkit.parse(f'x = """\n{content}\n"""')
    return fragment["x"]  # type: ignore[return-value]


def _parse_remote_identifier(url: str) -> str | None:
    """Parse a git remote URL to a worktrunk project identifier like 'github.com/user/repo'."""
    cleaned = url.strip().removesuffix(".git")
    if cleaned.startswith("git@"):
        return cleaned[4:].replace(":", "/", 1)
    for prefix in ("https://", "http://"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :]
    return None


def _wt_user_config_path() -> Path:
    """Return the worktrunk user config path, respecting XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "worktrunk" / "config.toml"


def _set_worktree_path(identifier: str, user_config: Path) -> bool:
    """Write worktree-path under [projects."<identifier>"] in the worktrunk user config.

    Returns True if written, False if already configured (no-op).
    """
    doc = tomlkit.load(user_config.open()) if user_config.exists() else tomlkit.document()

    if "projects" in doc and identifier in doc["projects"]:
        if "worktree-path" in doc["projects"][identifier]:
            return False

    if "projects" not in doc:
        doc.add("projects", tomlkit.table(is_super_table=True))
    if identifier not in doc["projects"]:
        doc["projects"].add(identifier, tomlkit.table())

    doc["projects"][identifier]["worktree-path"] = ".worktrees/{{ branch | sanitize }}"
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text(tomlkit.dumps(doc))
    return True


def _apply_worktree_path(user_config_path: Path) -> None:
    """Detect git remote and configure worktree-path in the worktrunk user config."""
    remote_result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
    if remote_result.returncode != 0 or not isinstance(remote_result.stdout, str):
        return
    identifier = _parse_remote_identifier(remote_result.stdout)
    if not identifier:
        return
    try:
        if _set_worktree_path(identifier, user_config_path):
            rprint(f"[green]✓[/green] Set worktree-path in {user_config_path}")
            rprint("  Worktrees will be created at .worktrees/<branch> instead of alongside the repo")
    except OSError as exc:
        rprint(f"[yellow]Warning:[/yellow] Could not update worktrunk user config: {exc}")


# ---------------------------------------------------------------------------
# Spawn helpers
# ---------------------------------------------------------------------------


def _sandbox_available() -> bool:
    """Return True if bubblewrap (bwrap) is present for OS-level sandbox containment."""
    return shutil.which("bwrap") is not None


def _resolve_worktree_path(branch: str) -> Path:
    """Return the absolute path to the worktree for branch, creating it if absent.

    Checks git worktree list first; creates at .worktrees/<branch> relative to repo
    root if not found.
    """
    list_result = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True)
    if list_result.returncode == 0:
        for chunk in list_result.stdout.strip().split("\n\n"):
            if not chunk.strip():
                continue
            fields: dict[str, str] = {}
            for line in chunk.splitlines():
                if " " in line:
                    k, _, v = line.partition(" ")
                    fields[k] = v
            if fields.get("branch") in (f"refs/heads/{branch}", branch):
                return Path(fields["worktree"])

    # Worktree not found — create it at the conventional path.
    root_result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root_result.returncode != 0:
        typer.echo("error: not inside a git repository", err=True)
        raise typer.Exit(1)

    worktree_path = Path(root_result.stdout.strip()) / ".worktrees" / branch
    branch_check = subprocess.run(["git", "branch", "--list", branch], capture_output=True, text=True)
    if branch in branch_check.stdout:
        create_result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch], capture_output=True, text=True
        )
    else:
        create_result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)], capture_output=True, text=True
        )

    if create_result.returncode != 0:
        typer.echo(f"error: failed to create worktree: {create_result.stderr.strip()}", err=True)
        raise typer.Exit(1)

    return worktree_path


def _build_agent_prompt(issue: Issue) -> str:
    """Return the default agent prompt for implementing a ticket."""
    return (
        f"You are implementing ticket {issue.identifier}: {issue.title}\n\n"
        "Read TASK.md for full context. Then:\n"
        "1. Explore the codebase to understand relevant code\n"
        "2. Implement the changes described\n"
        "3. Run tests (check CLAUDE.md for the test command)\n"
        "4. Commit your changes with a clear commit message\n\n"
        "Stop when: all tests pass AND all changes are committed to this branch.\n"
        "Do not open a PR. Do not ask for clarification — make your best judgment.\n"
        "If you make assumptions, append a brief '## Agent Notes' section to TASK.md."
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("list-issues")
def list_issues(tracker: TrackerOpt = None) -> None:
    """List issues assigned to me."""
    provider = get_provider(tracker)
    issues = provider.list_my_issues()

    table = Table(title="My Issues")
    table.add_column("ID", style="cyan")
    table.add_column("State")
    table.add_column("Pri")
    table.add_column("Title")
    table.add_column("URL", style="dim")

    for issue in issues:
        pri = _PRIORITY_LABEL.get(issue.priority, "—") if issue.priority is not None else "—"
        table.add_row(issue.identifier, issue.state, pri, issue.title, issue.url)

    rprint(table)


@app.command("get-issue")
def get_issue(
    issue_id: Annotated[str, typer.Argument(help="Issue ID (e.g. ENG-123 or owner/repo#42)")],
    tracker: TrackerOpt = None,
) -> None:
    """Show full details for an issue."""
    provider = get_provider(tracker)
    issue = provider.get_issue(issue_id)

    table = Table(title=f"{issue.identifier}: {issue.title}")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Provider", "Linear" if issue.provider == "linear" else "GitHub")
    table.add_row("State", issue.state)
    table.add_row("Team", issue.team or "—")
    table.add_row("Assignee", issue.assignee or "Unassigned")

    if issue.provider == "linear" and issue.priority is not None:
        table.add_row("Priority", _PRIORITY_LABEL.get(issue.priority, str(issue.priority)))

    table.add_row("Labels", ", ".join(issue.labels) if issue.labels else "none")
    table.add_row("URL", issue.url)
    table.add_row("Description", issue.description or "_No description provided._")

    rprint(table)


@app.command("create-issue")
def create_issue(
    title: Annotated[str, typer.Argument(help="Issue title")],
    description: Annotated[str | None, typer.Argument(help="Issue description")] = None,
    tracker: TrackerOpt = None,
    team: Annotated[
        str | None,
        typer.Option("--team", "-t", help="Team ID or owner/repo"),
    ] = None,
    priority: Annotated[
        int,
        typer.Option("--priority", "-p", min=1, max=4, help="Priority 1-4 (Linear only)"),
    ] = 3,
) -> None:
    """Create a new issue."""
    settings = get_settings(tracker=tracker)
    provider = get_provider(tracker)

    # Resolve team ID
    team_id = team or settings.linear_team_id or settings.github_repo
    if not team_id:
        rprint(
            "[red]No team specified. Use --team or set linear_team_id / github_repo "
            "in your config profile. Run 'ctw list-teams' to see available teams.[/red]"
        )
        raise typer.Exit(1)

    effective_priority: int | None = priority
    if settings.provider == "github":
        rprint("[dim](priority not supported for GitHub issues)[/dim]")
        effective_priority = None

    created = provider.create_issue(
        title=title,
        description=description,
        team_id=team_id,
        priority=effective_priority,
    )

    rprint(f"[green]✓[/green] [bold]{created.identifier}[/bold] {created.title}")
    rprint(f"  {created.url}")


@app.command("list-teams")
def list_teams(tracker: TrackerOpt = None) -> None:
    """List available teams or repositories."""
    provider = get_provider(tracker)
    teams = provider.list_teams()

    table = Table(title="Teams")
    table.add_column("Key", style="cyan")
    table.add_column("Name")
    table.add_column("ID", style="dim")

    for t in teams:
        table.add_row(t.key, t.name, t.id)

    rprint(table)


@app.command("context")
def context_cmd(
    issue_id: Annotated[str, typer.Argument(help="Issue ID")],
    tracker: TrackerOpt = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write to file instead of stdout"),
    ] = None,
) -> None:
    """Fetch issue and render TASK.md-style context."""
    provider = get_provider(tracker)
    issue = provider.get_issue(issue_id)
    rendered = render_context(issue)
    ctx = IssueContext(issue=issue, rendered=rendered)

    if output:
        output.write_text(ctx.rendered)
        rprint(f"[green]✓[/green] Wrote context to {output}")
    else:
        rprint(ctx.rendered)


@app.command("slug")
def slug_cmd(
    issue_id: Annotated[str, typer.Argument(help="Issue ID")],
    tracker: TrackerOpt = None,
) -> None:
    """Print a git-safe branch name for the issue (no trailing newline)."""
    provider = get_provider(tracker)
    issue = provider.get_issue(issue_id)
    # No trailing newline — designed for shell substitution: $(ctw slug ENG-123)
    typer.echo(make_slug(issue), nl=False)


@app.command("spawn")
def spawn(
    ticket_id: Annotated[str, typer.Argument(help="Ticket ID (e.g. ENG-123 or owner/repo#42)")],
    tracker: TrackerOpt = None,
    background: Annotated[
        bool, typer.Option("--background", "-b", help="Run agent in background, output to agent.log")
    ] = False,
    force_unsandboxed: Annotated[
        bool, typer.Option("--force-unsandboxed", help="Skip sandbox availability check")
    ] = False,
    prompt_override: Annotated[str | None, typer.Option("--prompt", help="Override the default agent prompt")] = None,
) -> None:
    """Spawn a Claude subagent to implement a ticket in its worktree."""
    if not _sandbox_available() and not force_unsandboxed:
        typer.echo(
            "error: Claude sandbox not detected on this system. Running with\n"
            "--dangerously-skip-permissions without a sandbox grants the agent\n"
            "unrestricted filesystem access. Pass --force-unsandboxed to proceed anyway.",
            err=True,
        )
        raise typer.Exit(1)

    provider = get_provider(tracker)
    issue = provider.get_issue(ticket_id)
    branch = make_slug(issue)
    worktree_path = _resolve_worktree_path(branch)

    (worktree_path / "TASK.md").write_text(render_context(issue))

    prompt = prompt_override if prompt_override else _build_agent_prompt(issue)
    cmd = ["claude", "--dangerously-skip-permissions", "--max-turns", "50", "-p", prompt]

    if background:
        log_path = worktree_path / "agent.log"
        proc = subprocess.Popen(cmd, cwd=worktree_path, stdout=log_path.open("w"), stderr=subprocess.STDOUT)
        typer.echo(f"Agent spawned (PID {proc.pid}). Logs: {log_path}")
    else:
        subprocess.run(cmd, cwd=worktree_path, check=False)


@app.command("set-default")
def set_default(
    tracker: Annotated[str, typer.Argument(help="Profile name to set as default")],
) -> None:
    """Set the default tracker profile in ~/.config/ctw/config.toml."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()
        doc.add("default_tracker", tracker)
        CONFIG_PATH.write_text(tomlkit.dumps(doc))
        rprint(f'[green]✓[/green] Default tracker set to "{tracker}" in {CONFIG_PATH}')
        return

    doc = tomlkit.load(CONFIG_PATH.open())
    profiles = _list_profiles(doc)
    if tracker not in profiles:
        rprint(f"[red]Profile '{tracker}' not found in {CONFIG_PATH}. Available: {profiles or '(none)'}[/red]")
        raise typer.Exit(1)

    doc["default_tracker"] = tracker
    CONFIG_PATH.write_text(tomlkit.dumps(doc))
    rprint(f'[green]✓[/green] Default tracker set to "{tracker}" in {CONFIG_PATH}')


@app.command("config-show")
def config_show(tracker: TrackerOpt = None) -> None:
    """Show resolved configuration (masks credentials)."""
    try:
        settings = get_settings(tracker=tracker)
    except SystemExit:
        return

    def mask(val: str | None, prefix: str = "") -> str:
        if val is None:
            return "[dim](not set)[/dim]"
        if len(val) <= 5:
            return "***"
        return f"{prefix}...{val[-5:]}"

    table = Table(title="CTW Configuration")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("provider", settings.provider)
    table.add_row("default_tracker", settings.default_tracker or "[dim](not set)[/dim]")
    table.add_row(
        "linear_api_key",
        mask(
            settings.linear_api_key.get_secret_value() if settings.linear_api_key else None,
            prefix="lin_api_",
        ),
    )
    table.add_row("linear_team_id", settings.linear_team_id or "[dim](not set)[/dim]")
    table.add_row(
        "github_token",
        mask(
            settings.github_token.get_secret_value() if settings.github_token else None,
            prefix="ghp_",
        ),
    )
    table.add_row("github_auth", settings.github_auth)
    table.add_row("github_repo", settings.github_repo or "[dim](not set)[/dim]")

    rprint(table)


@app.command("install-commands")
def install_commands() -> None:
    """Symlink Claude Code slash commands to ~/.claude/commands/."""
    src_dir = Path(__file__).parent / "commands"
    dest_dir = Path.home() / ".claude" / "commands"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src in src_dir.glob("*.md"):
        link = dest_dir / src.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src.resolve())
        rprint(f"[green]✓[/green] {link} → {src.resolve()}")


@app.command("configure-wt")
def configure_wt(
    tracker: TrackerOpt = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing ctw-context hook")] = False,
    config: Annotated[
        Path,
        typer.Option("--config", help="Path to wt config file"),
    ] = Path(".config/wt.toml"),
) -> None:
    """Add CTW post-create hook to .config/wt.toml.

    Reads the existing file and merges the hook in, preserving all comments and
    formatting. Safe to re-run — refuses to overwrite an existing hook unless
    --force is passed.
    """
    target = config

    # Warn if wt is not on PATH (non-fatal — file may be committed for others)
    wt_found = subprocess.run(["which", "wt"], capture_output=True).returncode == 0
    if not wt_found:
        rprint("[yellow]Warning:[/yellow] wt not found on PATH. Install worktrunk before using this hook.")

    if target.exists():
        doc = tomlkit.load(target.open())
    else:
        doc = tomlkit.document()

    # Check for existing hook
    post_create = doc.get("post-create")
    if post_create is not None and "ctw-context" in post_create:
        if not force:
            rprint(f"[yellow]ctw-context hook already present in {target}.[/yellow] Use --force to overwrite.")
            raise typer.Exit(0)

    # Ensure [post-create] table exists
    if "post-create" not in doc:
        doc.add("post-create", tomlkit.table())

    doc["post-create"]["ctw-context"] = _wt_hook_value(tracker)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tomlkit.dumps(doc))

    action = "Updated" if (post_create is not None and force) else "Wrote"
    rprint(f"[green]✓[/green] {action} {target}")

    _apply_worktree_path(_wt_user_config_path())

    if wt_found:
        approval = subprocess.run(["wt", "hook", "approvals", "add", "ctw-context"], capture_output=True)
        if approval.returncode == 0:
            rprint("[green]✓[/green] Hook auto-approved (wt hook approvals add ctw-context)")
        else:
            rprint("[yellow]Warning:[/yellow] Could not auto-approve hook. Run manually:")
            rprint("  wt hook approvals add ctw-context")

    main_check = subprocess.run(["git", "branch", "--list", "main"], capture_output=True, text=True)
    if not main_check.stdout.strip():
        branch_result = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], capture_output=True, text=True)
        current = branch_result.stdout.strip()
        if current:
            rprint("[yellow]Tip:[/yellow] Branch 'main' not found locally. If wt complains, run:")
            rprint(f"  wt config state default-branch set {current}")

    rprint("")
    rprint(f"[dim]Commit it:[/dim] git add {target} && git commit -m 'Add CTW worktree hook'")


@app.command("init")
def init_cmd() -> None:
    """Interactive first-time setup wizard."""
    rprint("[bold]CTW Setup Wizard[/bold]")
    rprint("")

    # Step 1: provider
    provider = typer.prompt("Provider? [linear/github]", default="linear").strip().lower()
    if provider not in ("linear", "github"):
        rprint("[red]Invalid provider. Choose 'linear' or 'github'.[/red]")
        raise typer.Exit(1)

    # Step 2: profile name
    profile_name = typer.prompt("Profile name (e.g. work, personal)").strip()
    if not profile_name:
        rprint("[red]Profile name cannot be empty.[/red]")
        raise typer.Exit(1)

    profile_config: dict = {"provider": provider}

    # Step 3: auth
    if provider == "linear":
        rprint("Create a Personal API Key at: https://linear.app/settings/api")
        key = typer.prompt("Paste API key", hide_input=True).strip()
        profile_config["linear_api_key"] = key

        # Offer to verify by listing teams
        verify = typer.confirm("Fetch teams to confirm key works?", default=True)
        if verify:
            try:
                settings = CtwSettings(provider="linear", linear_api_key=key)  # type: ignore[call-arg]
                from ctw.providers.linear import LinearProvider as LP

                teams = LP(settings).list_teams()
                rprint(f"[green]✓[/green] Connected. Found {len(teams)} team(s).")
            except Exception as exc:
                rprint(f"[yellow]Warning:[/yellow] Could not fetch teams: {exc}")

    else:  # github
        auth_method = (
            typer.prompt(
                "Authenticate via gh CLI or paste a Personal Access Token? [gh-cli/token]",
                default="token",
            )
            .strip()
            .lower()
        )

        if auth_method == "gh-cli":
            result = subprocess.run(["gh", "auth", "status"], capture_output=True)
            if result.returncode != 0:
                rprint("[red]gh not found or not authenticated. Run: gh auth login[/red]")
                raise typer.Exit(1)
            profile_config["github_auth"] = "gh-cli"
            rprint("[green]✓[/green] gh CLI authenticated.")
        elif auth_method == "token":
            rprint("Create a token at: https://github.com/settings/tokens")
            rprint("Required scopes: repo, read:user  (public_repo for public repos only)")
            token = typer.prompt("Paste token", hide_input=True).strip()
            profile_config["github_token"] = token
            profile_config["github_auth"] = "token"
        else:
            rprint("[red]Invalid auth method. Choose 'gh-cli' or 'token'.[/red]")
            raise typer.Exit(1)

        # Step 4 (GitHub only): default repo
        repo = typer.prompt("Default repo (owner/repo, or leave blank)", default="").strip()
        if repo:
            profile_config["github_repo"] = repo

    # Step 5: set as default?
    set_as_default = typer.confirm(f"Set '{profile_name}' as default tracker?", default=True)

    # Step 6: install commands?
    install = typer.confirm("Symlink Claude Code slash commands to ~/.claude/commands/?", default=True)

    # Step 7: write config (round-trip preserves any existing comments)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.load(CONFIG_PATH.open()) if CONFIG_PATH.exists() else tomlkit.document()

    doc[profile_name] = profile_config
    if set_as_default:
        doc["default_tracker"] = profile_name

    CONFIG_PATH.write_text(tomlkit.dumps(doc))
    rprint(f"[green]✓[/green] Profile '{profile_name}' written to {CONFIG_PATH}")

    if install:
        install_commands()

    # Step 8: show config
    rprint("")
    config_show(tracker=profile_name)
