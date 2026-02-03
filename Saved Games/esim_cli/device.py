from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .util import generate_eid, generate_imei, now_utc_iso, validate_eid, validate_imei


DeviceStatus = Literal["ready"]


@dataclass(slots=True)
class VirtualDevice:
    id: str
    eid: str
    imei: str
    model: str = "VirtualDevice"
    os_version: str = "Windows"
    created_at: str = field(default_factory=now_utc_iso)
    status: DeviceStatus = "ready"

    active_profile_id: str | None = None
    profile_ids: list[str] = field(default_factory=list)

    @staticmethod
    def create_new(*, device_id: str, eid: str | None = None, imei: str | None = None,
                   model: str = "VirtualDevice", os_version: str = "Windows") -> "VirtualDevice":
        eid_val = eid or generate_eid()
        imei_val = imei or generate_imei()
        validate_eid(eid_val)
        validate_imei(imei_val)
        return VirtualDevice(id=device_id, eid=eid_val, imei=imei_val, model=model, os_version=os_version)

