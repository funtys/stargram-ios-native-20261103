#!/usr/bin/env python3
"""Recreate the pinned native iPhone source project on its build machine."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OFFICIAL_SOURCE = "https://github.com/TelegramMessenger/Telegram-iOS.git"


def git(directory, *arguments, capture=False):
    command = ["git", "-c", "core.longpaths=true", "-C", str(directory), *arguments]
    if capture:
        return subprocess.check_output(command, text=True).strip()
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("Telegram-iOS-Native"))
    parser.add_argument("--check-only", action="store_true", help="Verify this kit without downloading or changing any source")
    args = parser.parse_args()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    patch = HERE / "patches/native-preview.patch"
    if manifest["repository"] != OFFICIAL_SOURCE:
        raise ValueError("Unexpected source repository")
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Native patch checksum mismatch")
    if args.check_only:
        print(json.dumps({"kit_integrity": "passed", "upstream_commit": manifest["commit"], "submodules": len(manifest["submodules"]), "contains_account_data": False, "compiled_ipa_included": False}, indent=2))
        return
    if shutil.which("git") is None:
        raise ValueError("Git is required to fetch the pinned official source")
    destination = args.destination.expanduser().resolve()
    if destination.exists():
        raise ValueError("Destination already exists; choose a new directory to preserve existing work")
    destination.mkdir(parents=True)
    git(destination, "init")
    git(destination, "remote", "add", "origin", OFFICIAL_SOURCE)
    git(destination, "fetch", "--depth", "1", "--filter=blob:none", "origin", manifest["commit"])
    git(destination, "checkout", "--detach", "FETCH_HEAD")
    if git(destination, "rev-parse", "HEAD", capture=True) != manifest["commit"]:
        raise ValueError("Official source revision mismatch")
    git(destination, "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "4")
    for module in manifest["submodules"]:
        module_path = (destination / module["path"]).resolve()
        if destination not in module_path.parents:
            raise ValueError("Invalid submodule path")
        if git(module_path, "rev-parse", "HEAD", capture=True) != module["commit"]:
            raise ValueError("Pinned submodule revision mismatch: " + module["path"])
    git(destination, "apply", "--check", "--whitespace=error-all", str(patch))
    git(destination, "apply", "--whitespace=error-all", str(patch))
    print("Native iPhone source project prepared at " + str(destination))
    print("No application has been compiled or signed. Read NativePreview/README.md for Xcode setup.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print("Error: " + str(error), file=sys.stderr)
        sys.exit(2)
    except subprocess.CalledProcessError as error:
        print("Source preparation failed; existing directories have not been deleted", file=sys.stderr)
        sys.exit(error.returncode or 1)
