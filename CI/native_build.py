#!/usr/bin/env python3
"""Keep the allocated builder for bounded retries after source fixes on main."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def verify_patch(manifest, patch, original):
    if manifest["repository"] != original["repository"] or manifest["commit"] != original["commit"]:
        raise ValueError("Live retries must keep the pinned official source revision")
    if hashlib.sha256(patch).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Updated patch checksum mismatch")


def replace_patch(source, old_path, new_path):
    private = source / "NativePreview/configuration.local.json"
    before = private.read_bytes() if private.is_file() else None
    git(source, "apply", "--reverse", "--check", str(old_path))
    git(source, "apply", "--reverse", str(old_path))
    try:
        git(source, "apply", "--check", str(new_path))
        git(source, "apply", str(new_path))
    except Exception:
        git(source, "apply", str(old_path))
        raise
    after = private.read_bytes() if private.is_file() else None
    if before != after:
        raise ValueError("Private API configuration changed during patch replacement")


def redact(line):
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        value = os.environ.get(key)
        if value:
            for variant in {value, value.lower(), value.upper()}:
                line = line.replace(variant, "[redacted]")
    return line


def build_once(root, build_number, attempt):
    output = root / "native-output"
    output.mkdir(exist_ok=True)
    log = output / f"native-attempt-{attempt}.log"
    command = [sys.executable, str(root / "source/NativePreview/manage.py"), "build", "--target", "iphone", "--unsigned", "--build-number", str(build_number)]
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in process.stdout:
            line = redact(line)
            handle.write(line)
            handle.flush()
            print(line, end="", flush=True)
        return process.wait()


def wait_for_revision(current, fetch, seconds, poll=20, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + seconds
    while clock() < deadline:
        candidate = fetch()
        if candidate is not None and candidate != current:
            return candidate
        sleep(min(poll, max(0, deadline - clock())))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-number", type=int, required=True)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--update-wait-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.max_attempts <= 3 or not 0 <= args.update_wait_seconds <= 600:
        raise ValueError("Retry limits exceeded")
    root = Path(__file__).resolve().parents[1]
    source = root / "source"
    original = json.loads((root / "manifest.json").read_text())
    old_path = root / "patches/native-preview.patch"
    verify_patch(original, old_path.read_bytes(), original)
    current = git(root, "rev-parse", "HEAD").decode().strip()
    if git(source, "rev-parse", "HEAD").decode().strip() != original["commit"]:
        raise ValueError("Builder source revision does not match the manifest")
    output = root / "native-output"
    output.mkdir(exist_ok=True)

    def fetch():
        try:
            subprocess.run(["git", "-C", str(root), "fetch", "--no-tags", "--depth=1", "origin", "main"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=45)
            return git(root, "rev-parse", "FETCH_HEAD").decode().strip()
        except (subprocess.SubprocessError, OSError):
            print("[native-ci] Repository update check unavailable; retrying within the bounded window", flush=True)
            return None

    for attempt in range(1, args.max_attempts + 1):
        (output / "effective-source.json").write_text(json.dumps({"cloud_commit": current, "upstream_commit": original["commit"], "attempt": attempt}, indent=2) + "\n")
        print(f"[native-ci] Attempt {attempt}/{args.max_attempts}; source {current}", flush=True)
        status = build_once(root, args.build_number, attempt)
        if status == 0:
            return 0
        if attempt == args.max_attempts:
            return status
        print(f"[native-ci] Build failed ({status}). Keeping this machine for up to {args.update_wait_seconds}s for a source fix on main", flush=True)
        candidate = wait_for_revision(current, fetch, args.update_wait_seconds)
        if candidate is None:
            print("[native-ci] No source update received; ending this build", flush=True)
            return status
        manifest = json.loads(git(root, "show", candidate + ":manifest.json"))
        patch = git(root, "show", candidate + ":patches/native-preview.patch")
        verify_patch(manifest, patch, original)
        if patch == old_path.read_bytes():
            print("[native-ci] New revision has no native source changes; ending this build", flush=True)
            return status
        new_path = output / "source-update.patch"
        new_path.write_bytes(patch)
        replace_patch(source, old_path, new_path)
        old_path.write_bytes(patch)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        current = candidate
        print("[native-ci] Source updated; retrying on the same allocated machine", flush=True)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("[native-ci] Build driver stopped: " + redact(str(error)), file=sys.stderr)
        sys.exit(1)
