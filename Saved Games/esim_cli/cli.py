from __future__ import annotations

import argparse
import sys

from .device import VirtualDevice
from .errors import ActivationCodeError, EsimCliError
from .lpa_emulator import LpaEmulator
from .smdp_client import MockSmdpClient
from .sms_emulator import SmsEmulator
from .storage import load_state, save_state
from .util import dumps_pretty, mask_sensitive


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="esim",
        description="eSIM CLI emulator - эмулятор устройства с eSIM (EID/IMEI, LPA, SMS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  esim init
  esim device show
  esim profile add --smdp https://smdp.example.com --activation-code LPA:1$smdp.example.com$ABC123
  esim profile find-by-phone +1234567890
  esim sms send --to +1234567890 --text "Hello"
        """,
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
    dev_show = dev_sub.add_parser("show", help="Show current device")
    dev_list = dev_sub.add_parser("list", help="List all devices")

    # Profile commands
    prof_p = sub.add_parser("profile", help="eSIM profile operations")
    prof_sub = prof_p.add_subparsers(dest="profile_cmd", required=True, metavar="SUBCOMMAND")

    prof_add = prof_sub.add_parser(
        "add",
        help="Download and install eSIM profile from SM-DP+ server",
        description="CRITICAL: Activation codes are ONE-TIME USE ONLY. "
        "If download fails, code becomes invalid. User must provide SM-DP+ address and activation code.",
    )
    prof_add.add_argument("--smdp", required=True, help="SM-DP+ server address (e.g., https://smdp.example.com)")
    prof_add.add_argument("--activation-code", required=True, help="One-time activation code (LPA activation code)")
    prof_add.add_argument("--confirmation-code", help="Optional confirmation code from operator")
    prof_add.add_argument("--msisdn", help="Phone number (MSISDN) to associate with profile")

    prof_list = prof_sub.add_parser("list", help="List all profiles on current device")
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

    sms_inbox = sms_sub.add_parser("inbox", help="Show incoming SMS messages")

    sms_sim = sms_sub.add_parser("simulate-incoming", help="Simulate incoming SMS")
    sms_sim.add_argument("--from", dest="from_msisdn", required=True, help="Source MSISDN")
    sms_sim.add_argument("--text", required=True, help="Message text")

    return p


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    p = build_parser()
    args = p.parse_args(argv)

    if args.version:
        print("esim-cli 1.0.0")
        return 0

    if not args.cmd:
        p.print_help()
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
                    print("No devices. Run: esim init")
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
                    print("No current device. Run: esim init", file=sys.stderr)
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
                current_id = state.get("devices", {}).get(state.get("current_device_id", ""), {}).get("active_profile_id")
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
                print(f"Found profile:")
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

        p.print_help()
        return 2

    except EsimCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
