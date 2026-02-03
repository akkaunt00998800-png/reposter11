from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .util import now_utc_iso


ProfileStatus = Literal["installed", "active", "disabled"]


@dataclass(slots=True)
class EsimProfile:
    id: str
    iccid: str
    operator_name: str
    smdp_address: str
    activation_code: str
    msisdn: str | None = None  # Phone number
    created_at: str = field(default_factory=now_utc_iso)
    status: ProfileStatus = "installed"

