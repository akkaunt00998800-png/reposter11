from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import APP_DIR_NAME, CONFIG_FILENAME, STATE_FILENAME
from .util import ensure_dir


def _get_app_dir() -> Path:
    """Get application directory in user home."""
    home = Path(os.path.expanduser("~"))
    return home / APP_DIR_NAME


@dataclass(slots=True)
class StoragePaths:
    app_dir: Path
    config_path: Path
    state_path: Path


def get_storage_paths() -> StoragePaths:
    """Get paths for storage files."""
    app_dir = _get_app_dir()
    return StoragePaths(
        app_dir=app_dir,
        config_path=app_dir / CONFIG_FILENAME,
        state_path=app_dir / STATE_FILENAME,
    )


def _ensure_app_dir() -> StoragePaths:
    """Ensure app directory exists and return paths."""
    paths = get_storage_paths()
    ensure_dir(str(paths.app_dir))
    return paths


def load_state() -> dict[str, Any]:
    """Load state from JSON file (no encryption)."""
    paths = _ensure_app_dir()
    if not paths.state_path.exists():
        return {
            "v": 1,
            "current_device_id": None,
            "devices": {},
            "profiles": {},
            "sms": [],
            "used_activation_codes": {},  # Track one-time codes: code -> {used_at, eid, imei}
        }
    
    try:
        with paths.state_path.open(encoding="utf-8") as f:
            state = json.load(f)
        # Ensure backward compatibility
        if "used_activation_codes" not in state:
            state["used_activation_codes"] = {}
        return state
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to load state: {e}") from e


def save_state(state: dict[str, Any]) -> None:
    """Save state to JSON file (no encryption)."""
    paths = _ensure_app_dir()
    # Ensure used_activation_codes exists
    if "used_activation_codes" not in state:
        state["used_activation_codes"] = {}
    
    try:
        with paths.state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to save state: {e}") from e


def load_config() -> dict[str, Any]:
    """Load configuration file."""
    paths = _ensure_app_dir()
    if not paths.config_path.exists():
        return {}
    try:
        with paths.config_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    """Save configuration file."""
    paths = _ensure_app_dir()
    try:
        with paths.config_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to save config: {e}") from e
