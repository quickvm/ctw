"""Settings resolution with 5-step precedence chain and named profile support."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import tomlkit
import typer
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH = Path.home() / ".config" / "ctw" / "config.toml"


class CtwSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CTW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Tracker selection
    default_tracker: str | None = None  # profile name
    provider: str = "linear"  # "linear" | "github", resolved from active profile

    # Linear
    linear_api_key: SecretStr | None = None
    linear_team_id: str | None = None

    # GitHub
    github_token: SecretStr | None = None
    github_auth: str = "token"  # "token" | "gh-cli"
    github_repo: str | None = None  # default repo for bare issue numbers


@lru_cache(maxsize=1)
def _load_toml() -> tomlkit.TOMLDocument:
    """Load ~/.config/ctw/config.toml, returning empty document if missing."""
    if not CONFIG_PATH.exists():
        return tomlkit.document()
    return tomlkit.load(CONFIG_PATH.open())


def _list_profiles(config: Mapping) -> list[str]:
    # tomlkit Table implements MutableMapping but not dict, so check Mapping
    return [k for k, v in config.items() if isinstance(v, Mapping)]


def _cwd_env_provider() -> str | None:
    """Read CTW_PROVIDER from .env in cwd without full settings instantiation."""
    env_file = Path(".env")
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("CTW_PROVIDER="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


def get_settings(tracker: str | None = None) -> CtwSettings:
    """Resolve active tracker profile and return a fully populated CtwSettings.

    Precedence (highest to lowest):
    1. tracker argument (--tracker CLI flag)
    2. CTW_DEFAULT_TRACKER env var
    3. default_tracker key in ~/.config/ctw/config.toml
    4. CTW_PROVIDER in .env in cwd
    5. First profile defined in ~/.config/ctw/config.toml
    """
    import os

    toml_config = _load_toml()

    # Step 1-3: resolve active tracker name
    active = (
        tracker
        or os.environ.get("CTW_DEFAULT_TRACKER")
        or toml_config.get("default_tracker")
        or _cwd_env_provider()
        or ((_profiles := _list_profiles(toml_config)) and _profiles[0] or None)
    )

    # Step 2: load profile block as base defaults
    profile_defaults: dict = {}
    if active:
        if active in toml_config and isinstance(toml_config[active], Mapping):
            profile_defaults = dict(toml_config[active])
        elif active not in toml_config:
            profiles = _list_profiles(toml_config)
            typer.echo(f"Profile '{active}' not found in {CONFIG_PATH}. Available: {profiles or '(none)'}")
            raise typer.Exit(1)

    # Step 3: construct CtwSettings — env vars + .env always override profile defaults
    settings = CtwSettings(**profile_defaults)

    # Step 4: validate credentials for resolved provider
    if settings.provider == "linear" and not settings.linear_api_key:
        typer.echo(
            "Missing Linear credentials. Set CTW_LINEAR_API_KEY or "
            f"linear_api_key in the [{active or 'profile'}] section of {CONFIG_PATH}"
        )
        raise typer.Exit(1)
    github_needs_token = settings.provider == "github" and settings.github_auth == "token"
    if github_needs_token and not settings.github_token:
        typer.echo(
            "Missing GitHub credentials. Set CTW_GITHUB_TOKEN or "
            f"github_token in the [{active or 'profile'}] section of {CONFIG_PATH}, "
            'or set github_auth = "gh-cli" to use the gh CLI.'
        )
        raise typer.Exit(1)

    return settings
