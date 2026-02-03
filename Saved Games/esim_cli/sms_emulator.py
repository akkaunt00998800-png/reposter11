from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import InvalidStateError
from .util import now_utc_iso


Direction = Literal["outgoing", "incoming"]


@dataclass(slots=True)
class SmsMessage:
    id: str
    direction: Direction
    from_msisdn: str
    to_msisdn: str
    text: str
    timestamp: str = field(default_factory=now_utc_iso)
    profile_id: str | None = None


class SmsEmulator:
    def __init__(self, *, state: dict[str, Any]):
        self._state = state

    def _sms_list(self) -> list[dict[str, Any]]:
        return self._state.setdefault("sms", [])

    def _current_device(self) -> dict[str, Any]:
        cur = self._state.get("current_device_id")
        if not cur:
            raise InvalidStateError("No current device; run 'esim init' first")
        devices = self._state.get("devices", {})
        if cur not in devices:
            raise InvalidStateError("Current device not found in storage")
        return devices[cur]

    def send_sms(self, *, to_msisdn: str, text: str) -> SmsMessage:
        """Send SMS from active profile."""
        dev = self._current_device()
        profile_id = dev.get("active_profile_id")
        
        # Get MSISDN from active profile if available
        from_msisdn = "unknown"
        if profile_id:
            profiles = self._state.get("profiles", {})
            if profile_id in profiles:
                from_msisdn = profiles[profile_id].get("msisdn") or profile_id
        
        msg_id = f"sms-{len(self._sms_list())+1}"
        msg = SmsMessage(
            id=msg_id,
            direction="outgoing",
            from_msisdn=from_msisdn,
            to_msisdn=to_msisdn,
            text=text,
            profile_id=profile_id,
        )
        self._sms_list().append(
            {
                "id": msg.id,
                "direction": msg.direction,
                "from": msg.from_msisdn,
                "to": msg.to_msisdn,
                "text": msg.text,
                "timestamp": msg.timestamp,
                "profile_id": msg.profile_id,
            }
        )
        return msg

    def simulate_incoming(self, *, from_msisdn: str, text: str) -> SmsMessage:
        """Simulate incoming SMS to active profile."""
        dev = self._current_device()
        profile_id = dev.get("active_profile_id")
        
        # Get MSISDN from active profile if available
        to_msisdn = "unknown"
        if profile_id:
            profiles = self._state.get("profiles", {})
            if profile_id in profiles:
                to_msisdn = profiles[profile_id].get("msisdn") or profile_id
        
        msg_id = f"sms-{len(self._sms_list())+1}"
        msg = SmsMessage(
            id=msg_id,
            direction="incoming",
            from_msisdn=from_msisdn,
            to_msisdn=to_msisdn,
            text=text,
            profile_id=profile_id,
        )
        self._sms_list().append(
            {
                "id": msg.id,
                "direction": msg.direction,
                "from": msg.from_msisdn,
                "to": msg.to_msisdn,
                "text": msg.text,
                "timestamp": msg.timestamp,
                "profile_id": msg.profile_id,
            }
        )
        return msg

    def inbox(self) -> list[dict[str, Any]]:
        return [m for m in self._sms_list() if m.get("direction") == "incoming"]

