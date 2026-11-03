#!/usr/bin/env python3
"""Export validated native artifacts without bundling configurations or account data."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["iphone", "simulator"], required=True)
    parser.add_argument("--unsigned", action="store_true")
    args = parser.parse_args()
    artifact = SOURCE / "NativePreview/build-output" / args.target / "Telegram.ipa"
    output = ROOT / "native-output"
    output.mkdir(exist_ok=True)
    command = [sys.executable, str(SOURCE / "NativePreview/artifact.py"), str(artifact), "--target", args.target, "--output", str(output / "verification.json")]
    if args.unsigned:
        command.append("--unsigned")
    subprocess.run(command, check=True)
    if args.target == "iphone":
        shutil.copyfile(artifact, output / ("Telegram-Native-unsigned.ipa" if args.unsigned else "Telegram-Native.ipa"))
        shutil.copyfile(ROOT / "INSTALL-IPHONE.md", output / "INSTALL-IPHONE.md")
    else:
        with tempfile.TemporaryDirectory(prefix="stargram-native-simulator-") as temporary:
            stage = Path(temporary).resolve()
            expected_parent = Path(tempfile.gettempdir()).resolve()
            assert stage.parent == expected_parent and stage.name.startswith("stargram-native-simulator-")
            subprocess.run(["ditto", "-x", "-k", str(artifact), str(stage)], check=True)
            app = stage / "Payload/Telegram.app"
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(output / "Telegram-Native-Simulator.app.zip")], check=True)
            subprocess.run([sys.executable, str(ROOT / "CI/capture.py"), "--app", str(app), "--output", str(output / "screens")], check=True)


if __name__ == "__main__":
    main()
