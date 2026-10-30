# Reads the phone's cellular call state over adb, so the dashboard notices an
# incoming call without any app installed on the phone.
#
# `adb shell dumpsys telephony.registry` prints one block per SIM slot, e.g.
#   Phone Id=0
#     mCallState=1
#     mCallIncomingNumber=+919876543210
# mCallState: 0 = idle, 1 = ringing, 2 = off-hook (answered or dialling).
# Android 12+ often hides the number from adb, so `number` may be None.

import re
import subprocess

_STATES = {"0": "idle", "1": "ringing", "2": "in_call"}
# With two SIMs, report the slot that matters most
_PRIORITY = {"idle": 0, "in_call": 1, "ringing": 2}
# Anything else ("", "null", redacted "***") means the phone didn't share it
_NUMBER = re.compile(r"^\+?\d{3,15}$")


class PhoneNotConnectedError(RuntimeError):
    """adb is missing, or no phone is listed as "device"."""


def parse_telephony_registry(dump: str) -> dict:
    """Pick the call state and caller number out of a telephony.registry dump."""
    best = {"state": "idle", "number": None}
    for block in re.split(r"Phone Id=\d+", dump):
        state_match = re.search(r"mCallState=(\d)", block)
        if not state_match:
            continue
        state = _STATES.get(state_match.group(1), "idle")
        number_match = re.search(r"mCallIncomingNumber=(\S*)", block)
        raw = number_match.group(1) if number_match else ""
        number = raw if _NUMBER.match(raw) else None
        if _PRIORITY[state] > _PRIORITY[best["state"]]:
            best = {"state": state, "number": number}
    return best


def get_call_state() -> dict:
    """Ask the connected phone whether it's idle, ringing or in a call."""
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "telephony.registry"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise PhoneNotConnectedError("adb isn't available") from e
    if result.returncode != 0:
        # e.g. "adb: no devices/emulators found" or "device unauthorized"
        raise PhoneNotConnectedError(result.stderr.strip() or "No phone connected")
    return parse_telephony_registry(result.stdout)
