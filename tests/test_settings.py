"""Tests for ctw.settings — all 5 precedence steps and error paths."""

from pathlib import Path

import click
import pytest
import tomlkit

import ctw.settings as settings_module
from ctw.settings import _list_profiles, get_settings


def _write_config(tmp_path: Path, config: dict) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(tomlkit.dumps(config))
    return config_path


@pytest.fixture(autouse=True)
def reset_lru_cache():
    """Clear the lru_cache before each test."""
    settings_module._load_toml.cache_clear()
    yield
    settings_module._load_toml.cache_clear()


class TestListProfiles:
    def test_returns_section_keys(self) -> None:
        config = {
            "default_tracker": "work",
            "work": {"provider": "linear"},
            "personal": {"provider": "github"},
        }
        assert _list_profiles(config) == ["work", "personal"]

    def test_skips_scalar_keys(self) -> None:
        config = {"default_tracker": "work", "work": {"provider": "linear"}}
        assert _list_profiles(config) == ["work"]

    def test_empty_config(self) -> None:
        assert _list_profiles({}) == []


class TestGetSettings:
    def test_tracker_arg_takes_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "default_tracker": "personal",
                "work": {"provider": "linear", "linear_api_key": "lin_api_work"},
                "personal": {"provider": "linear", "linear_api_key": "lin_api_personal"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)

        s = get_settings(tracker="work")
        assert s.linear_api_key is not None
        assert s.linear_api_key.get_secret_value() == "lin_api_work"

    def test_env_var_takes_precedence_over_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "default_tracker": "personal",
                "work": {"provider": "linear", "linear_api_key": "lin_api_work"},
                "personal": {"provider": "linear", "linear_api_key": "lin_api_personal"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.setenv("CTW_DEFAULT_TRACKER", "work")

        s = get_settings()
        assert s.linear_api_key is not None
        assert s.linear_api_key.get_secret_value() == "lin_api_work"

    def test_toml_default_tracker_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "default_tracker": "work",
                "work": {"provider": "linear", "linear_api_key": "lin_api_work"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)

        s = get_settings()
        assert s.linear_api_key is not None
        assert s.linear_api_key.get_secret_value() == "lin_api_work"

    def test_first_profile_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "work": {"provider": "linear", "linear_api_key": "lin_api_first"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)

        s = get_settings()
        assert s.linear_api_key is not None
        assert s.linear_api_key.get_secret_value() == "lin_api_first"

    def test_missing_profile_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "work": {"provider": "linear", "linear_api_key": "lin_api_work"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_settings(tracker="nonexistent")

    def test_missing_linear_key_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "work": {"provider": "linear"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)
        monkeypatch.delenv("CTW_LINEAR_API_KEY", raising=False)

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_settings(tracker="work")

    def test_missing_github_token_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "personal": {"provider": "github", "github_auth": "token"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)
        monkeypatch.delenv("CTW_GITHUB_TOKEN", raising=False)

        with pytest.raises((SystemExit, click.exceptions.Exit)):
            get_settings(tracker="personal")

    def test_github_ghcli_skips_token_validation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(
            tmp_path,
            {
                "personal": {"provider": "github", "github_auth": "gh-cli"},
            },
        )
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)
        monkeypatch.delenv("CTW_GITHUB_TOKEN", raising=False)

        # Should NOT raise — gh-cli auth doesn't require a stored token
        s = get_settings(tracker="personal")
        assert s.github_auth == "gh-cli"

    def test_no_config_file_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "nonexistent.toml"
        monkeypatch.setattr(settings_module, "CONFIG_PATH", config_path)
        monkeypatch.delenv("CTW_DEFAULT_TRACKER", raising=False)
        monkeypatch.setenv("CTW_PROVIDER", "linear")
        monkeypatch.setenv("CTW_LINEAR_API_KEY", "lin_api_env")

        s = get_settings()
        assert s.provider == "linear"
        assert s.linear_api_key is not None
