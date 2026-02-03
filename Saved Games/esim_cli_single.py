from __future__ import annotations

"""
Single-file eSIM CLI emulator.

Эмулирует устройство с eSIM (EID/IMEI), упрощённый LPA, работу с SM-DP+ и SMS.
Все необходимые компоненты (device/profile/LPA/SMS/storage/CLI) собраны в ОДИН скрипт.

Использование (из папки со скриптом):
  python esim_cli_single.py --help
"""

import argparse
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EsimCliError(RuntimeError):
    """Base error for user-facing failures."""


class NotFoundError(EsimCliError):
    """Resource not found."""


class InvalidStateError(EsimCliError):
    """Invalid application state."""


class ActivationCodeError(EsimCliError):
    """Activation code is invalid or already used (one-time use violation)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "esim"
APP_DIR_NAME = ".esim_cli"
STATE_FILENAME = "state_single.json"
CONFIG_FILENAME = "config_single.json"


# ---------------------------------------------------------------------------
# Storage (JSON, без шифрования)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StoragePaths:
    app_dir: Path
    config_path: Path
    state_path: Path


def _get_app_dir() -> Path:
    """Get application directory in user home."""
    home = Path(os.path.expanduser("~"))
    return home / APP_DIR_NAME


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


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

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
    def create_new(
        *,
        device_id: str,
        eid: str | None = None,
        imei: str | None = None,
        model: str = "VirtualDevice",
        os_version: str = "Windows",
    ) -> "VirtualDevice":
        eid_val = eid or generate_eid()
        imei_val = imei or generate_imei()
        validate_eid(eid_val)
        validate_imei(imei_val)
        return VirtualDevice(id=device_id, eid=eid_val, imei=imei_val, model=model, os_version=os_version)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SM-DP+ client (mock)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DownloadResult:
    profile: EsimProfile


class ISmdpClient:
    """Interface for SM-DP+ client implementations."""

    def download_profile(
        self,
        *,
        smdp_address: str,
        activation_code: str,
        eid: str,
        imei: str,
        confirmation_code: str | None = None,
    ) -> DownloadResult:
        """
        Download profile from SM-DP+ server.

        Args:
            smdp_address: SM-DP+ server address/URL
            activation_code: One-time activation code (LPA activation code)
            eid: Device EID
            imei: Device IMEI
            confirmation_code: Optional confirmation code from operator

        Returns:
            DownloadResult with profile

        Raises:
            ActivationCodeError: If activation code is invalid or already used
        """
        raise NotImplementedError


class MockSmdpClient(ISmdpClient):
    """Mock SM-DP+ client for testing (offline, generates fake profiles)."""

    def __init__(self, *, default_operator: str = "MockOperator"):
        self._default_operator = default_operator

    def download_profile(
        self,
        *,
        smdp_address: str,
        activation_code: str,
        eid: str,
        imei: str,
        confirmation_code: str | None = None,
    ) -> DownloadResult:
        """
        Mock profile download - generates a fake profile.
        In real implementation, this would make HTTPS request to SM-DP+ server.
        """
        # Generate random ICCID (ITU-T E.118 format: 89 + 18 digits)
        iccid = "89" + "".join(str(secrets.randbelow(10)) for _ in range(18))
        profile_id = f"p-{secrets.token_hex(4)}"

        profile = EsimProfile(
            id=profile_id,
            iccid=iccid,
            operator_name=self._default_operator,
            smdp_address=smdp_address,
            activation_code=activation_code,
            msisdn=None,  # Will be set later if provided
        )
        return DownloadResult(profile=profile)


# ---------------------------------------------------------------------------
# LPA Emulator
# ---------------------------------------------------------------------------


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

        except Exception as e:  # noqa: BLE001 - intentionally broad to emulate real-world failure
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
        """Find profile by phone number (MSISDN)."""
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


# ---------------------------------------------------------------------------
# SMS Emulator
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description="eSIM CLI emulator (single file) - эмулятор устройства с eSIM (EID/IMEI, LPA, SMS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python esim_cli_single.py init\n"
            "  python esim_cli_single.py device show\n"
            "  python esim_cli_single.py profile add --smdp https://smdp.example.com "
            "--activation-code LPA:1$smdp.example.com$ABC123\n"
            "  python esim_cli_single.py profile find-by-phone +1234567890\n"
            '  python esim_cli_single.py sms send --to +1234567890 --text "Hello"\n'
        ),
    )
    p.add_argument("--version", action="store_true", help="Show version and exit")

    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    # Device commands
    init_p = sub.add_parser("init", help="Initialize a new virtual device")
    init_p.add_argument("--device-id", default="dev1", help="Virtual device id (default: dev1)")
    init_p.add_argument("--eid", help="32-digit EID (optional, auto-generated if omitted)")
    init_p.add_argument("--imei", help="15-digit IMEI (optional, auto-generated if omitted)")
    init_p.add_argument("--model", default="VirtualDevice", help="Device model label")
    init_p.add_argument("--os", dest="os_version", default="Windows", help="OS version label")

    dev_p = sub.add_parser("device", help="Device operations")
    dev_sub = dev_p.add_subparsers(dest="device_cmd", required=True, metavar="SUBCOMMAND")
    dev_sub.add_parser("show", help="Show current device")
    dev_sub.add_parser("list", help="List all devices")

    # Profile commands
    prof_p = sub.add_parser("profile", help="eSIM profile operations")
    prof_sub = prof_p.add_subparsers(dest="profile_cmd", required=True, metavar="SUBCOMMAND")

    prof_add = prof_sub.add_parser(
        "add",
        help="Download and install eSIM profile from SM-DP+ server",
        description=(
            "CRITICAL: Activation codes are ONE-TIME USE ONLY. "
            "If download fails, code becomes invalid. User must provide SM-DP+ address and activation code."
        ),
    )
    prof_add.add_argument("--smdp", required=True, help="SM-DP+ server address (e.g., https://smdp.example.com)")
    prof_add.add_argument("--activation-code", required=True, help="One-time activation code (LPA activation code)")
    prof_add.add_argument("--confirmation-code", help="Optional confirmation code from operator")
    prof_add.add_argument("--msisdn", help="Phone number (MSISDN) to associate with profile")

    prof_sub.add_parser("list", help="List all profiles on current device")

    prof_find = prof_sub.add_parser("find-by-phone", help="Find profile by phone number")
    prof_find.add_argument("msisdn", help="Phone number (MSISDN) to search for")

    prof_set = prof_sub.add_parser("set-active", help="Set profile as active")
    prof_set.add_argument("profile_id", help="Profile ID")

    prof_disable = prof_sub.add_parser("disable", help="Disable profile")
    prof_disable.add_argument("profile_id", help="Profile ID")

    prof_del = prof_sub.add_parser("delete", help="Delete profile")
    prof_del.add_argument("profile_id", help="Profile ID")

    # SMS commands
    sms_p = sub.add_parser("sms", help="SMS emulator operations")
    sms_sub = sms_p.add_subparsers(dest="sms_cmd", required=True, metavar="SUBCOMMAND")

    sms_send = sms_sub.add_parser("send", help="Send SMS (logged locally)")
    sms_send.add_argument("--to", required=True, help="Destination MSISDN")
    sms_send.add_argument("--text", required=True, help="Message text")

    sms_sub.add_parser("inbox", help="Show incoming SMS messages")

    sms_sim = sms_sub.add_parser("simulate-incoming", help="Simulate incoming SMS")
    sms_sim.add_argument("--from", dest="from_msisdn", required=True, help="Source MSISDN")
    sms_sim.add_argument("--text", required=True, help="Message text")

    return p


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("esim-cli-single 1.0.0")
        return 0

    if not args.cmd:
        parser.print_help()
        return 2

    try:
        # Initialize device
        if args.cmd == "init":
            state = load_state()

            # Check if device already exists
            if args.device_id in state.get("devices", {}):
                print(f"Error: Device '{args.device_id}' already exists", file=sys.stderr)
                return 1

            dev = VirtualDevice.create_new(
                device_id=args.device_id,
                eid=args.eid,
                imei=args.imei,
                model=args.model,
                os_version=args.os_version,
            )
            state.setdefault("devices", {})
            state["devices"][dev.id] = {
                "id": dev.id,
                "eid": dev.eid,
                "imei": dev.imei,
                "model": dev.model,
                "os_version": dev.os_version,
                "created_at": dev.created_at,
                "status": dev.status,
                "active_profile_id": dev.active_profile_id,
                "profile_ids": list(dev.profile_ids),
            }
            state["current_device_id"] = dev.id
            save_state(state)
            print(f"[OK] Initialized device '{dev.id}'")
            print(f"  EID : {mask_sensitive(dev.eid)}")
            print(f"  IMEI: {mask_sensitive(dev.imei)}")
            return 0

        # Device operations
        if args.cmd == "device":
            state = load_state()

            if args.device_cmd == "list":
                devices = state.get("devices", {})
                if not devices:
                    print("No devices. Run: init")
                    return 0
                current_id = state.get("current_device_id")
                for dev_id, dev in devices.items():
                    marker = "*" if dev_id == current_id else " "
                    print(
                        f"{marker} {dev_id:10}  "
                        f"EID={mask_sensitive(dev.get('eid', ''))}  "
                        f"IMEI={mask_sensitive(dev.get('imei', ''))}"
                    )
                return 0

            if args.device_cmd == "show":
                cur = state.get("current_device_id")
                if not cur:
                    print("No current device. Run: init", file=sys.stderr)
                    return 1
                dev = state["devices"][cur]
                safe = dict(dev)
                safe["eid"] = mask_sensitive(str(safe.get("eid", "")))
                safe["imei"] = mask_sensitive(str(safe.get("imei", "")))
                print(dumps_pretty(safe))
                return 0

        # Profile operations
        if args.cmd == "profile":
            state = load_state()
            lpa = LpaEmulator(state=state, smdp_client=MockSmdpClient())

            if args.profile_cmd == "add":
                print(f"Downloading profile from SM-DP+ server: {args.smdp}")
                print(f"Using activation code: {mask_sensitive(args.activation_code)}")
                if args.confirmation_code:
                    print(f"Confirmation code: {mask_sensitive(args.confirmation_code)}")
                print()

                try:
                    prof = lpa.add_profile(
                        smdp_address=args.smdp,
                        activation_code=args.activation_code,
                        confirmation_code=args.confirmation_code,
                        msisdn=args.msisdn,
                    )
                    save_state(state)
                    print("[OK] Profile downloaded and installed successfully")
                    print(f"  ID     : {prof.id}")
                    print(f"  ICCID  : {mask_sensitive(prof.iccid)}")
                    print(f"  Operator: {prof.operator_name}")
                    if prof.msisdn:
                        print(f"  Phone  : {prof.msisdn}")
                    return 0
                except ActivationCodeError as e:
                    print(f"[ERROR] {e}", file=sys.stderr)
                    print(
                        "\n[CRITICAL] Activation code is now INVALID and cannot be reused.",
                        file=sys.stderr,
                    )
                    print("  Contact your operator for a new activation code.", file=sys.stderr)
                    return 1

            if args.profile_cmd == "list":
                profiles = lpa.list_profiles()
                if not profiles:
                    print("No profiles on current device")
                    return 0
                print(f"{'Status':<10} {'ID':<15} {'Operator':<20} {'Phone':<15} {'ICCID'}")
                print("-" * 80)
                for pinfo in profiles:
                    mark = "ACTIVE" if pinfo["status"] == "active" else pinfo["status"].upper()
                    print(
                        f"{mark:<10} {pinfo['id']:<15} {pinfo['operator_name']:<20} "
                        f"{pinfo.get('msisdn', 'N/A'):<15} {mask_sensitive(pinfo['iccid'])}"
                    )
                return 0

            if args.profile_cmd == "find-by-phone":
                prof = lpa.find_profile_by_msisdn(args.msisdn)
                if not prof:
                    print(f"No profile found with phone number: {args.msisdn}", file=sys.stderr)
                    return 1
                print("Found profile:")
                print(f"  ID     : {prof['id']}")
                print(f"  ICCID  : {mask_sensitive(prof['iccid'])}")
                print(f"  Operator: {prof['operator_name']}")
                print(f"  Phone  : {prof.get('msisdn', 'N/A')}")
                print(f"  Status : {prof['status']}")
                return 0

            if args.profile_cmd == "set-active":
                lpa.set_active(args.profile_id)
                save_state(state)
                print(f"[OK] Profile '{args.profile_id}' set as active")
                return 0

            if args.profile_cmd == "disable":
                lpa.disable(args.profile_id)
                save_state(state)
                print(f"[OK] Profile '{args.profile_id}' disabled")
                return 0

            if args.profile_cmd == "delete":
                lpa.delete(args.profile_id)
                save_state(state)
                print(f"[OK] Profile '{args.profile_id}' deleted")
                return 0

        # SMS operations
        if args.cmd == "sms":
            state = load_state()
            sms = SmsEmulator(state=state)

            if args.sms_cmd == "send":
                msg = sms.send_sms(to_msisdn=args.to, text=args.text)
                save_state(state)
                print(f"[OK] Sent SMS id={msg.id} to={msg.to_msisdn}")
                return 0

            if args.sms_cmd == "inbox":
                inbox = sms.inbox()
                if not inbox:
                    print("Inbox is empty")
                    return 0
                print(f"{'Timestamp':<25} {'From':<15} {'Text'}")
                print("-" * 80)
                for m in inbox:
                    print(f"{m['timestamp']:<25} {m['from']:<15} {m['text']}")
                return 0

            if args.sms_cmd == "simulate-incoming":
                msg = sms.simulate_incoming(from_msisdn=args.from_msisdn, text=args.text)
                save_state(state)
                print(f"[OK] Simulated incoming SMS id={msg.id} from={msg.from_msisdn}")
                return 0

        parser.print_help()
        return 2

    except EsimCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

