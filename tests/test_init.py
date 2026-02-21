"""Tests for ctw init wizard."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import tomlkit
from typer.testing import CliRunner

import ctw.settings as settings_module
from ctw.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_lru_cache():
    settings_module._load_toml.cache_clear()
    yield
    settings_module._load_toml.cache_clear()


class TestInitLinear:
    def test_writes_linear_profile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)

        with patch("ctw.main.CONFIG_PATH", config_path):
            with patch("ctw.main.install_commands"):
                with patch("ctw.main.config_show"):
                    result = runner.invoke(
                        app,
                        ["init"],
                        input="linear\nwork\nlin_api_test_key\nn\ny\nn\n",
                    )

        assert result.exit_code == 0, result.output
        assert config_path.exists()
        config = tomlkit.load(config_path.open())
        assert "work" in config
        assert config["work"]["provider"] == "linear"
        assert config["work"]["linear_api_key"] == "lin_api_test_key"


class TestInitGithubGhCli:
    def test_writes_ghcli_profile_no_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("ctw.main.CONFIG_PATH", config_path):
            with patch("subprocess.run", return_value=mock_result):
                with patch("ctw.main.install_commands"):
                    with patch("ctw.main.config_show"):
                        result = runner.invoke(
                            app,
                            ["init"],
                            # provider=github, profile=personal, auth=gh-cli,
                            # repo=blank, set-default=y, install=n
                            input="github\npersonal\ngh-cli\n\ny\nn\n",
                        )

        assert result.exit_code == 0, result.output
        assert config_path.exists()
        config = tomlkit.load(config_path.open())

        assert "personal" in config
        profile = config["personal"]
        assert profile["github_auth"] == "gh-cli"
        # No token must be stored
        assert "github_token" not in profile

    def test_gh_not_authenticated_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("ctw.main.CONFIG_PATH", config_path):
            with patch("subprocess.run", return_value=mock_result):
                result = runner.invoke(
                    app,
                    ["init"],
                    input="github\npersonal\ngh-cli\n",
                )

        assert result.exit_code != 0


class TestInitGithubToken:
    def test_writes_token_profile(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)

        with patch("ctw.main.CONFIG_PATH", config_path):
            with patch("ctw.main.install_commands"):
                with patch("ctw.main.config_show"):
                    result = runner.invoke(
                        app,
                        ["init"],
                        input="github\nquickvm\ntoken\nghp_mytoken\njdoss/quickvm\ny\nn\n",
                    )

        assert result.exit_code == 0, result.output
        config = tomlkit.load(config_path.open())

        assert config["quickvm"]["github_token"] == "ghp_mytoken"
        assert config["quickvm"]["github_auth"] == "token"
        assert config["quickvm"]["github_repo"] == "jdoss/quickvm"
