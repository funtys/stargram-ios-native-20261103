#!/usr/bin/env python3
"""Capture only the launch of a fresh, account-free simulator app."""
import argparse
import json
from pathlib import Path
import plistlib
import signal
import subprocess
import time


def command(*arguments, capture=False):
    if capture:
        return subprocess.check_output(arguments, text=True).strip()
    subprocess.run(arguments, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    bundle_id = plistlib.loads((app / "Info.plist").read_bytes())["CFBundleIdentifier"]
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    runtimes = json.loads(command("xcrun", "simctl", "list", "runtimes", "-j", capture=True))["runtimes"]
    compatible = [item for item in runtimes if item.get("isAvailable") and item["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27")]
    if not compatible:
        raise ValueError("No installed iOS 27 simulator runtime")
    runtime = sorted(compatible, key=lambda value: tuple(map(int, value["version"].split("."))))[-1]
    device = command("xcrun", "simctl", "create", "Stargram account-free preview", "com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro", runtime["identifier"], capture=True)
    # This device was just created. Never select an existing simulator or copy account data.
    command("xcrun", "simctl", "boot", device)
    command("xcrun", "simctl", "bootstatus", device, "-b")
    command("xcrun", "simctl", "install", device, str(app))
    with (output / "recording.log").open("w", encoding="utf-8") as log:
        recorder = subprocess.Popen(["xcrun", "simctl", "io", device, "recordVideo", "--codec=h264", "--force", str(output / "launch.mp4")], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if "Recording started" in (output / "recording.log").read_text(encoding="utf-8"):
                    break
                if recorder.poll() is not None:
                    raise ValueError("Simulator recording failed to start")
                time.sleep(0.2)
            else:
                raise ValueError("Simulator recording startup timed out")
            command("xcrun", "simctl", "launch", device, bundle_id)
            time.sleep(4)
            command("xcrun", "simctl", "io", device, "screenshot", str(output / "welcome.png"))
        finally:
            if recorder.poll() is None:
                recorder.send_signal(signal.SIGINT)
                recorder.wait(timeout=15)
    command("xcrun", "simctl", "shutdown", device)
    (output / "capture.json").write_text(json.dumps({"device": device, "runtime": runtime["version"], "account_seeded": False, "screen": "initial launch only", "chats_tested": False, "all_animations_verified": False}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
