from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


_EID_RE = re.compile(r"^\d{32}$")
_IMEI_RE = re.compile(r"^\d{15}$")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_sensitive(value: str | None, *, keep_last: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep_last:
        return "*" * len(value)
    return "*" * (len(value) - keep_last) + value[-keep_last:]


def validate_eid(eid: str) -> None:
    if not _EID_RE.match(eid):
        raise ValueError("EID must be exactly 32 digits")


def validate_imei(imei: str) -> None:
    if not _IMEI_RE.match(imei):
        raise ValueError("IMEI must be exactly 15 digits")


def generate_eid() -> str:
    # 32 digits, not a real issued EID, good for emulation.
    return "".join(str(secrets.randbelow(10)) for _ in range(32))


def generate_imei() -> str:
    # 15 digits, not a real issued IMEI. (No Luhn to keep it simple for emu.)
    return "".join(str(secrets.randbelow(10)) for _ in range(15))


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def dumps_pretty(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False, indent=2, sort_keys=True)

