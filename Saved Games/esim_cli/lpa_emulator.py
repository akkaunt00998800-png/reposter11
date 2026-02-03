from __future__ import annotations

from typing import Any

from .device import VirtualDevice
from .errors import ActivationCodeError, InvalidStateError, NotFoundError
from .profile import EsimProfile
from .smdp_client import ISmdpClient
from .util import now_utc_iso


class LpaEmulator:
    """
    Emulates Local Profile Assistant (LPA) functionality.
    
    Handles profile download, installation, activation, and management
    according to GSMA SGP.22 specifications (simplified).
    """

    def __init__(self, *, state: dict[str, Any], smdp_client: ISmdpClient):
        self._state = state
        self._smdp = smdp_client

    def _get_device(self, device_id: str) -> dict[str, Any]:
        """Get device by ID."""
        devices = self._state.setdefault("devices", {})
        if device_id not in devices:
            raise NotFoundError(f"Device '{device_id}' not found")
        return devices[device_id]

    def _get_current_device(self) -> dict[str, Any]:
        """Get current active device."""
        cur = self._state.get("current_device_id")
        if not cur:
            raise InvalidStateError("No current device; run 'esim init' first")
        return self._get_device(cur)

    def _profiles(self) -> dict[str, Any]:
        """Get profiles dictionary."""
        return self._state.setdefault("profiles", {})

    def _check_activation_code_used(self, activation_code: str, eid: str, imei: str) -> None:
        """
        Check if activation code was already used.
        
        Activation codes are ONE-TIME USE ONLY. If used incorrectly,
        the eSIM profile becomes unusable.
        """
        used_codes = self._state.setdefault("used_activation_codes", {})
        
        if activation_code in used_codes:
            usage = used_codes[activation_code]
            # Check if it was used with different device (security check)
            if usage.get("eid") != eid or usage.get("imei") != imei:
                raise ActivationCodeError(
                    f"Activation code was already used with different device "
                    f"(EID: {usage.get('eid', 'unknown')}, IMEI: {usage.get('imei', 'unknown')}). "
                    f"This code is now INVALID and cannot be reused."
                )
            # Same device - might be retry, but warn
            raise ActivationCodeError(
                f"Activation code was already used at {usage.get('used_at')}. "
                f"Each code can only be used ONCE. If download failed, contact operator."
            )

    def _mark_activation_code_used(self, activation_code: str, eid: str, imei: str) -> None:
        """Mark activation code as used (one-time use enforcement)."""
        used_codes = self._state.setdefault("used_activation_codes", {})
        used_codes[activation_code] = {
            "used_at": now_utc_iso(),
            "eid": eid,
            "imei": imei,
        }

    def add_profile(
        self,
        *,
        smdp_address: str,
        activation_code: str,
        confirmation_code: str | None = None,
        msisdn: str | None = None,
    ) -> EsimProfile:
        """
        Download and install eSIM profile from SM-DP+ server.
        
        CRITICAL: Activation codes are ONE-TIME USE. If this fails,
        the code becomes invalid and cannot be reused.
        
        Args:
            smdp_address: SM-DP+ server address (user-provided)
            activation_code: One-time activation code (LPA activation code)
            confirmation_code: Optional confirmation code from operator
            msisdn: Optional phone number to associate with profile
            
        Returns:
            Installed EsimProfile
            
        Raises:
            ActivationCodeError: If activation code was already used
            InvalidStateError: If no current device
        """
        dev_dict = self._get_current_device()
        dev = VirtualDevice(
            id=dev_dict["id"],
            eid=dev_dict["eid"],
            imei=dev_dict["imei"],
            model=dev_dict.get("model", "VirtualDevice"),
            os_version=dev_dict.get("os_version", "Windows"),
        )

        # CRITICAL: Check if activation code was already used
        self._check_activation_code_used(activation_code, dev.eid, dev.imei)

        try:
            # Download profile from SM-DP+ (this is the critical one-time operation)
            result = self._smdp.download_profile(
                smdp_address=smdp_address,
                activation_code=activation_code,
                eid=dev.eid,
                imei=dev.imei,
                confirmation_code=confirmation_code,
            )
            prof = result.profile
            
            # Mark code as used IMMEDIATELY after successful download
            self._mark_activation_code_used(activation_code, dev.eid, dev.imei)
            
            # Set MSISDN if provided
            if msisdn:
                prof.msisdn = msisdn

        except Exception as e:
            # If download fails, mark code as used anyway (real-world behavior)
            # This prevents retry with same code
            self._mark_activation_code_used(activation_code, dev.eid, dev.imei)
            raise ActivationCodeError(
                f"Profile download failed: {e}. "
                f"Activation code '{activation_code[:8]}...' is now INVALID and cannot be reused. "
                f"Contact your operator for a new activation code."
            ) from e

        # Store profile
        profiles = self._profiles()
        profiles[prof.id] = {
            "id": prof.id,
            "iccid": prof.iccid,
            "operator_name": prof.operator_name,
            "smdp_address": prof.smdp_address,
            "activation_code": prof.activation_code,
            "msisdn": prof.msisdn,
            "created_at": prof.created_at,
            "status": prof.status,
        }

        # Attach to device
        dev_dict.setdefault("profile_ids", [])
        dev_dict["profile_ids"].append(prof.id)
        
        # If this is first profile, make it active by default
        if not dev_dict.get("active_profile_id"):
            dev_dict["active_profile_id"] = prof.id
            profiles[prof.id]["status"] = "active"

        return prof

    def list_profiles(self) -> list[dict[str, Any]]:
        """List all profiles on current device."""
        dev = self._get_current_device()
        profiles = self._profiles()
        ids = dev.get("profile_ids", [])
        return [profiles[pid] for pid in ids if pid in profiles]

    def find_profile_by_msisdn(self, msisdn: str) -> dict[str, Any] | None:
        """
        Find profile by phone number (MSISDN).
        
        Args:
            msisdn: Phone number to search for
            
        Returns:
            Profile dict if found, None otherwise
        """
        profiles = self._profiles()
        for prof in profiles.values():
            if prof.get("msisdn") == msisdn:
                return prof
        return None

    def set_active(self, profile_id: str) -> None:
        """Set profile as active (enable it)."""
        dev = self._get_current_device()
        profiles = self._profiles()
        if profile_id not in profiles:
            raise NotFoundError(f"Profile '{profile_id}' not found")
        if profile_id not in dev.get("profile_ids", []):
            raise InvalidStateError(f"Profile '{profile_id}' is not attached to current device")

        # Disable previous active profile
        prev_id = dev.get("active_profile_id")
        if prev_id and prev_id in profiles:
            profiles[prev_id]["status"] = "installed"

        profiles[profile_id]["status"] = "active"
        dev["active_profile_id"] = profile_id

    def disable(self, profile_id: str) -> None:
        """Disable profile (but keep it installed)."""
        dev = self._get_current_device()
        profiles = self._profiles()
        if profile_id not in profiles:
            raise NotFoundError(f"Profile '{profile_id}' not found")

        profiles[profile_id]["status"] = "disabled"
        if dev.get("active_profile_id") == profile_id:
            dev["active_profile_id"] = None

    def delete(self, profile_id: str) -> None:
        """Delete profile from device (permanent)."""
        dev = self._get_current_device()
        profiles = self._profiles()
        if profile_id not in profiles:
            raise NotFoundError(f"Profile '{profile_id}' not found")

        del profiles[profile_id]
        dev.setdefault("profile_ids", [])
        dev["profile_ids"] = [pid for pid in dev["profile_ids"] if pid != profile_id]
        if dev.get("active_profile_id") == profile_id:
            dev["active_profile_id"] = None

