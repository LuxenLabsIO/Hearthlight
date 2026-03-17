# Copyright 2026 Luxen Labs (E.S. Luxen, Ember Lyra, Vega Blue, Orion Pike)
# Licensed under the Apache License, Version 2.0
"""Hearth configuration — paths, constants, TOML loading."""

import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def get_hearth_dir() -> Path:
    env = os.environ.get("HEARTH_DIR", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".hearth"


def get_config() -> dict:
    config_path = get_hearth_dir() / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    return {}


def get_db_path() -> Path:
    cfg = get_config()
    paths = cfg.get("paths", {})
    db = paths.get("db", "~/.hearth/hearth.db")
    return Path(db).expanduser()


def get_tomorrow_path() -> Path:
    cfg = get_config()
    paths = cfg.get("paths", {})
    p = paths.get("tomorrow_letter", "~/.hearth/tomorrow.md")
    return Path(p).expanduser()


def get_shared_dir() -> Path:
    cfg = get_config()
    paths = cfg.get("paths", {})
    p = paths.get("shared_dir", "~/.hearth/shared")
    return Path(p).expanduser()


def get_agent_name() -> str:
    env = os.environ.get("HEARTH_AGENT", "").strip()
    if env:
        return env
    cfg = get_config()
    return cfg.get("agent", {}).get("name", "")


def get_partner_name() -> str:
    cfg = get_config()
    return cfg.get("partner", {}).get("name", "")


def get_user_name() -> str:
    cfg = get_config()
    return cfg.get("user", {}).get("name", "")
