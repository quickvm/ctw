"""Smoke tests for all CLI commands using typer CliRunner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from typer.testing import CliRunner

import ctw.settings as settings_module
from ctw.main import app
from ctw.models import CreatedIssue, Issue, Team

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_lru_cache():
    settings_module._load_toml.cache_clear()
    yield
    settings_module._load_toml.cache_clear()


def _mock_linear_issue() -> Issue:
    return Issue(
        id="issue_1",
        identifier="ENG-1",
        title="Test issue",
        description="A test issue.",
        url="https://linear.app/t/ENG-1",
        state="In Progress",
        priority=3,
        assignee="Test User",
        team="Engineering",
        labels=["bug"],
        provider="linear",
    )


def _mock_github_issue() -> Issue:
    return Issue(
        id="1",
        identifier="jdoss/repo#1",
        title="Test GH issue",
        description="A github issue.",
        url="https://github.com/jdoss/repo/issues/1",
        state="Open",
        priority=None,
        assignee="jdoss",
        team="jdoss/repo",
        labels=[],
        provider="github",
    )


def _mock_provider(issue: Issue | None = None) -> MagicMock:
    provider = MagicMock()
    _issue = issue or _mock_linear_issue()
    provider.list_my_issues.return_value = [_issue]
    provider.get_issue.return_value = _issue
    provider.list_teams.return_value = [Team(id="t1", name="Eng", key="ENG", provider="linear")]
    provider.create_issue.return_value = CreatedIssue(
        identifier="ENG-99",
        title="New",
        url="https://linear.app/t/ENG-99",
        provider="linear",
    )
    return provider


class TestNoArgs:
    def test_shows_help_not_error(self) -> None:
        result = runner.invoke(app, [])
        # no_args_is_help=True: CliRunner exits 2 (known Typer quirk) but shows help
        assert "Missing command" not in result.output
        assert "Commands" in result.output


class TestListIssues:
    def test_renders_table(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["list-issues"])
        assert result.exit_code == 0
        assert "ENG-1" in result.output


class TestGetIssue:
    def test_renders_detail(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["get-issue", "ENG-1"])
        assert result.exit_code == 0
        assert "ENG-1" in result.output

    def test_github_omits_priority(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider(_mock_github_issue())):
            result = runner.invoke(app, ["get-issue", "jdoss/repo#1"])
        assert result.exit_code == 0
        assert "Priority" not in result.output


class TestCreateIssue:
    def test_creates_with_team(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main.get_settings") as mock_settings:
                s = MagicMock()
                s.provider = "linear"
                s.linear_team_id = "t1"
                s.github_repo = None
                mock_settings.return_value = s
                result = runner.invoke(app, ["create-issue", "Test", "Desc"])
        assert result.exit_code == 0
        assert "ENG-99" in result.output

    def test_no_team_exits(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main.get_settings") as mock_settings:
                s = MagicMock()
                s.provider = "linear"
                s.linear_team_id = None
                s.github_repo = None
                mock_settings.return_value = s
                result = runner.invoke(app, ["create-issue", "Test"])
        assert result.exit_code != 0


class TestListTeams:
    def test_renders_table(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["list-teams"])
        assert result.exit_code == 0
        assert "ENG" in result.output


class TestContext:
    def test_outputs_markdown(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["context", "ENG-1"])
        assert result.exit_code == 0
        assert "# ENG-1" in result.output

    def test_writes_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "TASK.md"
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["context", "ENG-1", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "# ENG-1" in content


class TestSlug:
    def test_outputs_slug_no_newline(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            result = runner.invoke(app, ["slug", "ENG-1"])
        assert result.exit_code == 0
        assert result.output == "eng-1-test-issue"


class TestSetDefault:
    def test_creates_config_if_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import tomlkit

        config_path = tmp_path / "config.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        # Also patch the import in main.py
        with patch("ctw.main.CONFIG_PATH", config_path):
            result = runner.invoke(app, ["set-default", "myprofile"])
        assert result.exit_code == 0
        assert config_path.exists()
        config = tomlkit.load(config_path.open())
        assert config["default_tracker"] == "myprofile"

    def test_validates_profile_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import tomlkit

        config_path = tmp_path / "config.toml"
        doc = tomlkit.document()
        doc.add("work", {"provider": "linear"})
        config_path.write_text(tomlkit.dumps(doc))
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        with patch("ctw.main.CONFIG_PATH", config_path):
            result = runner.invoke(app, ["set-default", "nonexistent"])
        assert result.exit_code != 0


class TestConfigureWt:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        import tomlkit

        wt_config = tmp_path / ".config" / "wt.toml"
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])
        assert result.exit_code == 0, result.output
        assert wt_config.exists()
        doc = tomlkit.load(wt_config.open())
        assert "post-create" in doc
        assert "ctw-context" in doc["post-create"]

    def test_merges_into_existing_file_preserving_content(self, tmp_path: Path) -> None:

        wt_config = tmp_path / ".config" / "wt.toml"
        wt_config.parent.mkdir(parents=True)
        # Existing file with a comment and another hook
        wt_config.write_text('# My project hooks\n[post-create]\ndeps = "npm ci"\n')

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])
        assert result.exit_code == 0, result.output

        content = wt_config.read_text()
        assert "# My project hooks" in content  # comment preserved
        assert 'deps = "npm ci"' in content  # existing hook preserved
        assert "ctw-context" in content

    def test_refuses_if_hook_exists_without_force(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"
        wt_config.parent.mkdir(parents=True)
        wt_config.write_text('[post-create]\nctw-context = "old"\n')

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])
        assert result.exit_code == 0
        # Content should be unchanged
        assert 'ctw-context = "old"' in wt_config.read_text()

    def test_force_overwrites_existing_hook(self, tmp_path: Path) -> None:
        import tomlkit

        wt_config = tmp_path / ".config" / "wt.toml"
        wt_config.parent.mkdir(parents=True)
        wt_config.write_text('[post-create]\nctw-context = "old"\n')

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config), "--force"])
        assert result.exit_code == 0, result.output
        doc = tomlkit.load(wt_config.open())
        hook = str(doc["post-create"]["ctw-context"])
        assert hook != "old"
        assert "ctw context" in hook

    def test_tracker_flag_embedded_in_hook(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config), "--tracker", "work"])
        assert result.exit_code == 0, result.output
        content = wt_config.read_text()
        assert "--tracker work" in content

    def test_no_tracker_flag_omitted_from_hook(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])
        assert result.exit_code == 0, result.output
        # The hook comment mentions "--tracker" but the ctw command should not have a flag
        hook = wt_config.read_text()
        assert 'ctw context "$TICKET"' in hook and "--tracker" not in hook.split("ctw context")[1].split("\n")[0]

    def test_auto_approves_hook_when_wt_available(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"

        def fake_run(args, **kwargs):
            m = MagicMock(returncode=0)
            m.stdout = "  main\n"
            return m

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert result.exit_code == 0, result.output
        called = [c.args[0] for c in mock_run.call_args_list]
        assert ["wt", "hook", "approvals", "add", "ctw-context"] in called
        assert "auto-approved" in result.output

    def test_warns_when_approval_fails(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"

        def fake_run(args, **kwargs):
            m = MagicMock()
            m.stdout = "  main\n"
            m.returncode = 1 if args == ["wt", "hook", "approvals", "add", "ctw-context"] else 0
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert result.exit_code == 0, result.output
        assert "Could not auto-approve" in result.output

    def test_warns_when_main_branch_missing(self, tmp_path: Path) -> None:
        wt_config = tmp_path / ".config" / "wt.toml"

        def fake_run(args, **kwargs):
            m = MagicMock(returncode=0)
            if args[:3] == ["git", "branch", "--list"]:
                m.stdout = ""
            elif args[:2] == ["git", "symbolic-ref"]:
                m.stdout = "master"
            else:
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert result.exit_code == 0, result.output
        assert "master" in result.output
        assert "default-branch" in result.output


class TestWtHelpers:
    def test_parse_remote_identifier_https(self) -> None:
        from ctw.main import _parse_remote_identifier

        assert _parse_remote_identifier("https://github.com/quickvm/ctw.git") == "github.com/quickvm/ctw"

    def test_parse_remote_identifier_ssh(self) -> None:
        from ctw.main import _parse_remote_identifier

        assert _parse_remote_identifier("git@github.com:quickvm/ctw.git") == "github.com/quickvm/ctw"

    def test_parse_remote_identifier_no_git_suffix(self) -> None:
        from ctw.main import _parse_remote_identifier

        assert _parse_remote_identifier("https://github.com/quickvm/ctw") == "github.com/quickvm/ctw"

    def test_parse_remote_identifier_unknown_scheme_returns_none(self) -> None:
        from ctw.main import _parse_remote_identifier

        assert _parse_remote_identifier("ftp://example.com/repo.git") is None

    def test_set_worktree_path_creates_new_config(self, tmp_path: Path) -> None:
        import tomlkit

        from ctw.main import _set_worktree_path

        user_config = tmp_path / "worktrunk" / "config.toml"
        result = _set_worktree_path("github.com/quickvm/ctw", user_config)

        assert result is True
        assert user_config.exists()
        doc = tomlkit.load(user_config.open())
        assert doc["projects"]["github.com/quickvm/ctw"]["worktree-path"] == ".worktrees/{{ branch | sanitize }}"

    def test_set_worktree_path_merges_into_existing_config(self, tmp_path: Path) -> None:
        from ctw.main import _set_worktree_path

        user_config = tmp_path / "worktrunk" / "config.toml"
        user_config.parent.mkdir(parents=True)
        user_config.write_text("# existing config\n")

        _set_worktree_path("github.com/quickvm/ctw", user_config)
        content = user_config.read_text()
        assert "# existing config" in content
        assert "worktree-path" in content

    def test_set_worktree_path_skips_if_already_set(self, tmp_path: Path) -> None:
        from ctw.main import _set_worktree_path

        user_config = tmp_path / "worktrunk" / "config.toml"
        user_config.parent.mkdir(parents=True)
        user_config.write_text('[projects."github.com/quickvm/ctw"]\nworktree-path = "custom/path"\n')

        result = _set_worktree_path("github.com/quickvm/ctw", user_config)
        assert result is False
        assert 'worktree-path = "custom/path"' in user_config.read_text()

    def test_configure_wt_sets_worktree_path(self, tmp_path: Path, monkeypatch) -> None:
        import tomlkit

        import ctw.main as ctw_main

        wt_config = tmp_path / ".config" / "wt.toml"
        user_config = tmp_path / "worktrunk" / "config.toml"
        monkeypatch.setattr(ctw_main, "_wt_user_config_path", lambda: user_config)

        def fake_run(args, **kwargs):
            m = MagicMock(returncode=0)
            m.stdout = "https://github.com/quickvm/ctw.git" if args[:3] == ["git", "remote", "get-url"] else "  main\n"
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert result.exit_code == 0, result.output
        assert user_config.exists()
        doc = tomlkit.load(user_config.open())
        assert doc["projects"]["github.com/quickvm/ctw"]["worktree-path"] == ".worktrees/{{ branch | sanitize }}"
        assert "worktrees will be created" in result.output.lower()

    def test_configure_wt_skips_worktree_path_when_no_remote(self, tmp_path: Path, monkeypatch) -> None:
        import ctw.main as ctw_main

        wt_config = tmp_path / ".config" / "wt.toml"
        user_config = tmp_path / "worktrunk" / "config.toml"
        monkeypatch.setattr(ctw_main, "_wt_user_config_path", lambda: user_config)

        def fake_run(args, **kwargs):
            m = MagicMock()
            m.stdout = ""
            m.returncode = 1 if args[:3] == ["git", "remote", "get-url"] else 0
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert result.exit_code == 0, result.output
        assert not user_config.exists()

    def test_configure_wt_no_overwrite_existing_worktree_path(self, tmp_path: Path, monkeypatch) -> None:
        import ctw.main as ctw_main

        wt_config = tmp_path / ".config" / "wt.toml"
        user_config = tmp_path / "worktrunk" / "config.toml"
        user_config.parent.mkdir(parents=True)
        user_config.write_text('[projects."github.com/quickvm/ctw"]\nworktree-path = "custom/path"\n')
        monkeypatch.setattr(ctw_main, "_wt_user_config_path", lambda: user_config)

        def fake_run(args, **kwargs):
            m = MagicMock(returncode=0)
            m.stdout = "https://github.com/quickvm/ctw.git" if args[:3] == ["git", "remote", "get-url"] else "  main\n"
            return m

        with patch("subprocess.run", side_effect=fake_run):
            runner.invoke(app, ["configure-wt", "--config", str(wt_config)])

        assert 'worktree-path = "custom/path"' in user_config.read_text()


class TestSpawn:
    def test_sandbox_missing_blocks_spawn(self) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=False):
                result = runner.invoke(app, ["spawn", "ENG-1"])
        assert result.exit_code == 1
        assert "force-unsandboxed" in result.output

    def test_force_unsandboxed_bypasses_sandbox_check(self, tmp_path: Path) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=False):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.run") as mock_run:
                        result = runner.invoke(app, ["spawn", "ENG-1", "--force-unsandboxed"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_blocking_spawn_invokes_claude(self, tmp_path: Path) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=True):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.run") as mock_run:
                        result = runner.invoke(app, ["spawn", "ENG-1"])
        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in cmd
        assert "--max-turns" in cmd
        assert "-p" in cmd
        assert mock_run.call_args[1]["cwd"] == tmp_path

    def test_background_spawn_prints_pid_and_log_path(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=True):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.Popen", return_value=mock_proc):
                        result = runner.invoke(app, ["spawn", "ENG-1", "--background"])
        assert result.exit_code == 0
        assert "12345" in result.output
        assert "agent.log" in result.output

    def test_writes_task_md_to_worktree(self, tmp_path: Path) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=True):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.run"):
                        runner.invoke(app, ["spawn", "ENG-1"])
        task_md = tmp_path / "TASK.md"
        assert task_md.exists()
        assert "ENG-1" in task_md.read_text()

    def test_prompt_override_passed_to_claude(self, tmp_path: Path) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=True):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.run") as mock_run:
                        runner.invoke(app, ["spawn", "ENG-1", "--prompt", "Fix only the login bug"])
        cmd = mock_run.call_args[0][0]
        assert "Fix only the login bug" in cmd

    def test_default_prompt_contains_ticket_identifier(self, tmp_path: Path) -> None:
        with patch("ctw.main.get_provider", return_value=_mock_provider()):
            with patch("ctw.main._sandbox_available", return_value=True):
                with patch("ctw.main._resolve_worktree_path", return_value=tmp_path):
                    with patch("subprocess.run") as mock_run:
                        runner.invoke(app, ["spawn", "ENG-1"])
        cmd = mock_run.call_args[0][0]
        prompt_text = cmd[cmd.index("-p") + 1]
        assert "ENG-1" in prompt_text


class TestResolveWorktreePath:
    def test_returns_existing_worktree_path(self) -> None:
        from ctw.main import _resolve_worktree_path

        porcelain = (
            "worktree /home/user/project\nHEAD abc123\nbranch refs/heads/main\n\n"
            "worktree /home/user/project/.worktrees/eng-1-test-issue\n"
            "HEAD def456\nbranch refs/heads/eng-1-test-issue\n"
        )

        def fake_run(args, **kwargs):
            m = MagicMock(returncode=0, stdout=porcelain if args[:3] == ["git", "worktree", "list"] else "")
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = _resolve_worktree_path("eng-1-test-issue")
        assert result == Path("/home/user/project/.worktrees/eng-1-test-issue")

    def test_creates_worktree_for_new_branch(self, tmp_path: Path) -> None:
        from ctw.main import _resolve_worktree_path

        main_only_porcelain = "worktree /home/user/project\nHEAD abc123\nbranch refs/heads/main\n"
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            m = MagicMock(returncode=0)
            if args[:3] == ["git", "worktree", "list"]:
                m.stdout = main_only_porcelain
            elif args[:3] == ["git", "rev-parse", "--show-toplevel"]:
                m.stdout = str(tmp_path)
            elif args[:2] == ["git", "branch"]:
                m.stdout = ""  # branch doesn't exist yet
            else:
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = _resolve_worktree_path("new-feature")

        assert result == tmp_path / ".worktrees" / "new-feature"
        worktree_add = next(c for c in calls if len(c) > 2 and c[:3] == ["git", "worktree", "add"])
        assert "-b" in worktree_add

    def test_uses_existing_branch_without_b_flag(self, tmp_path: Path) -> None:
        from ctw.main import _resolve_worktree_path

        main_only_porcelain = "worktree /home/user/project\nHEAD abc123\nbranch refs/heads/main\n"
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            m = MagicMock(returncode=0)
            if args[:3] == ["git", "worktree", "list"]:
                m.stdout = main_only_porcelain
            elif args[:3] == ["git", "rev-parse", "--show-toplevel"]:
                m.stdout = str(tmp_path)
            elif args[:2] == ["git", "branch"]:
                m.stdout = "  existing-branch\n"
            else:
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            result = _resolve_worktree_path("existing-branch")

        assert result == tmp_path / ".worktrees" / "existing-branch"
        worktree_add = next(c for c in calls if len(c) > 2 and c[:3] == ["git", "worktree", "add"])
        assert "-b" not in worktree_add

    def test_exits_when_not_in_git_repo(self) -> None:
        from ctw.main import _resolve_worktree_path

        def fake_run(args, **kwargs):
            m = MagicMock()
            if args[:3] == ["git", "worktree", "list"]:
                m.returncode = 128
                m.stdout = ""
            elif args[:3] == ["git", "rev-parse", "--show-toplevel"]:
                m.returncode = 128
                m.stdout = ""
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(click.exceptions.Exit):
                _resolve_worktree_path("some-branch")

    def test_exits_when_worktree_add_fails(self, tmp_path: Path) -> None:
        from ctw.main import _resolve_worktree_path

        main_only_porcelain = "worktree /home/user/project\nHEAD abc123\nbranch refs/heads/main\n"

        def fake_run(args, **kwargs):
            m = MagicMock()
            if args[:3] == ["git", "worktree", "list"]:
                m.returncode = 0
                m.stdout = main_only_porcelain
            elif args[:3] == ["git", "rev-parse", "--show-toplevel"]:
                m.returncode = 0
                m.stdout = str(tmp_path)
            elif args[:2] == ["git", "branch"]:
                m.returncode = 0
                m.stdout = ""
            elif args[:3] == ["git", "worktree", "add"]:
                m.returncode = 1
                m.stderr = "fatal: already exists"
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(click.exceptions.Exit):
                _resolve_worktree_path("bad-branch")


class TestInferProviderType:
    def test_linear_identifier(self) -> None:
        from ctw.main import _infer_provider_type

        assert _infer_provider_type("ENG-123") == "linear"
        assert _infer_provider_type("INF-1") == "linear"

    def test_bare_number(self) -> None:
        from ctw.main import _infer_provider_type

        assert _infer_provider_type("49") == "github"

    def test_qualified_github(self) -> None:
        from ctw.main import _infer_provider_type

        assert _infer_provider_type("jdoss/quickvm#42") == "github"

    def test_ambiguous_returns_none(self) -> None:
        from ctw.main import _infer_provider_type

        assert _infer_provider_type("something-else") is None


class TestFindProfileForProvider:
    def test_finds_linear_profile(self) -> None:
        from ctw.main import _find_profile_for_provider

        config = {"work": {"provider": "linear", "linear_api_key": "lin_test"}}
        assert _find_profile_for_provider(config, "linear") == "work"

    def test_finds_github_profile(self) -> None:
        from ctw.main import _find_profile_for_provider

        config = {"personal": {"provider": "github", "github_token": "ghp_test"}}
        assert _find_profile_for_provider(config, "github") == "personal"

    def test_defaults_to_linear_when_no_provider_key(self) -> None:
        from ctw.main import _find_profile_for_provider

        config = {"work": {"linear_api_key": "lin_test"}}
        assert _find_profile_for_provider(config, "linear") == "work"

    def test_returns_none_when_no_match(self) -> None:
        from ctw.main import _find_profile_for_provider

        config = {"work": {"provider": "linear"}}
        assert _find_profile_for_provider(config, "github") is None

    def test_skips_non_mapping_entries(self) -> None:
        from ctw.main import _find_profile_for_provider

        config = {"default_tracker": "work", "work": {"provider": "linear"}}
        assert _find_profile_for_provider(config, "linear") == "work"


class TestInstallCommands:
    def test_creates_symlinks(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / ".claude" / "commands"
        # We need real command files to symlink
        src_dir = Path(__file__).parent.parent / "ctw" / "commands"
        if not src_dir.exists():
            pytest.skip("commands/ not yet created")

        with patch("ctw.main.Path.home", return_value=tmp_path):
            result = runner.invoke(app, ["install-commands"])

        assert result.exit_code == 0
        assert dest_dir.exists()
