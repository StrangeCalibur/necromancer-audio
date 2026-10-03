#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline contract tests. Never opens USB, starts audio/MIDI or changes launchd."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    started = time.time()
    source_sha256 = build.source_fingerprint()
    report_path = build.BUILD / "test-results.json"
    report_path.unlink(missing_ok=True)
    dep, library = build.build(build.parse_args(["--jobs", str(args.jobs), *(["--offline"] if args.offline else [])]))
    binaries = build.BUILD / "tests"
    binaries.mkdir(exist_ok=True)
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    results = []
    for name in ("test_mbox_pcm.c", "test_mbox_options.c", "test_mbox_midi.c", "test_mbox_mapping.cpp", "test_mbox_bridge.mm", "test_mbox_midi_transport.m", "test_device_profile.m"):
        source = build.ROOT / "tests" / name
        target = binaries / source.stem
        build.compile_file(source, target, dep, library if name == "test_mbox_bridge.mm" else None, sanitizer=True)
        completed = subprocess.run([str(target)], capture_output=True, text=True, env=env, timeout=120)
        print(completed.stdout.strip(), flush=True)
        if completed.returncode:
            sys.stderr.write(completed.stderr)
            raise RuntimeError(name + " failed")
        results.append({"test": name, "passed": True, "output": completed.stdout.strip()})
    build.run([sys.executable, "-m", "unittest", "discover", "-s", build.ROOT / "tests", "-p", "test_*.py", "-v"])
    python_tests = unittest.defaultTestLoader.discover(str(build.ROOT / "tests"), pattern="test_*.py").countTestCases()
    # Help/version/argument rejection must run without touching USB.
    service = build.BUILD / "bin/mbox_service"
    for arguments, expected in ((["--version"], 0), (["--help"], 0), (["--flash"], 2), (["--serve-capture", "--location-id"], 2)):
        result = subprocess.run([str(service), *arguments], capture_output=True, text=True)
        if result.returncode != expected:
            raise RuntimeError("CLI guard failed: " + str(arguments))
    if source_sha256 != build.source_fingerprint():
        raise RuntimeError("Source changed during verification; rerun tests on a stable checkout.")
    report = {"passed": True, "duration_seconds": round(time.time() - started, 2), "native_contracts": results,
              "source_sha256": source_sha256, "python_tests_passed": python_tests,
              "hardware_access": False, "installation_performed": False, "sanitizers": ["address", "undefined"]}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: offline build, native contracts, installer filesystem transactions and CLI guards")


if __name__ == "__main__":
    main()
