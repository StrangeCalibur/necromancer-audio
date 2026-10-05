#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create deterministic local source/developer archives. Never uploads or publishes."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import install
import build

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {"src", "tests", "tools", "docs", ".github"}
ALLOWED_TOP = {".gitignore", "AGENTS.md", "README.md", "LICENSE", "VERSION", "Makefile",
               "dependencies.json", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CONTRIBUTING.md"}
PROJECT_ONLY = {"CONTINUUM_AGENT_INSTRUCTIONS.md", ".continuum/.gitignore",
                ".continuum/kanban.project.json", ".continuum/kanban.setup.md",
                ".continuum/agent.onboarding.md", ".continuum/custom-instructions-snippet.md",
                ".continuum/agent_enter.py", ".continuum/install_agent_instructions.py",
                ".continuum/kanban.secret.env.example"}
TEXT_SUFFIXES = {".m", ".mm", ".h", ".hpp", ".c", ".cpp", ".py", ".md", ".json", ".yml", ".yaml"}
DEVELOPER_TOOLS = {"mbox_midi_bridge", "audio_inventory", "mbox_coreaudio_test", "mbox_midi_test", "midi_inventory"}
PRIVATE_PATTERNS = [
    re.compile(rb"/Users/[A-Za-z0-9_.-]+/"),
    re.compile(rb"Boot session " + rb"UUID:|panic\(cpu "),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"(?i)(?:authorization|x-kanban-key)[\s\"':=]+(?:Bearer )?[A-Za-z0-9_-]{24,}"),
]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def scan_bytes(data, name):
    if any(pattern.search(data) for pattern in PRIVATE_PATTERNS):
        raise RuntimeError("Private material pattern found; inspect locally: " + name)


def source_files():
    if git("status", "--porcelain").strip():
        raise RuntimeError("Commit the reviewed source before preparing archives; working tree is dirty.")
    files = []
    for raw in git("ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        name = raw.decode()
        path = Path(name)
        full = ROOT / path
        if name in PROJECT_ONLY:
            if full.is_symlink() or not full.is_file() or full.stat().st_size > 2 * 1024 * 1024:
                raise RuntimeError("Invalid project coordination file: " + name)
            data = full.read_bytes()
            data.decode("utf-8")
            scan_bytes(data, name)
            continue
        if path.parts[0] not in ALLOWED_ROOTS and name not in ALLOWED_TOP:
            raise RuntimeError("Uncurated tracked path: " + name)
        if name not in ALLOWED_TOP and path.suffix not in TEXT_SUFFIXES:
            raise RuntimeError("Unexpected source type: " + name)
        if full.is_symlink() or not full.is_file() or full.stat().st_size > 2 * 1024 * 1024:
            raise RuntimeError("Invalid source file: " + name)
        data = full.read_bytes()
        data.decode("utf-8")
        scan_bytes(data, name)
        if name == "AGENTS.md":
            data = re.sub(rb"<!-- continuum-agent-fast-path:start -->.*?<!-- continuum-agent-fast-path:end -->\s*",
                          b"", data, flags=re.DOTALL)
        files.append((name, data, 0o644))
    return files


def archive(path, prefix, files):
    with path.open("wb") as target, gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as output:
            for name, data, mode in sorted(files):
                info = tarfile.TarInfo(prefix + "/" + name)
                info.size = len(data)
                info.mode = mode
                info.mtime = info.uid = info.gid = 0
                info.uname = info.gname = ""
                output.addfile(info, io.BytesIO(data))


def developer_files(release, manifest, root=ROOT):
    expected = {"payload/" + name for name in manifest["files"]}
    sidecars = {name: root / name for name in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md")}
    sidecars["install.py"] = root / "tools/install.py"
    for path in (root / "docs").rglob("*"):
        if path.is_file():
            if path.is_symlink() or path.suffix != ".md":
                raise RuntimeError("Uncurated documentation sidecar")
            sidecars[path.relative_to(root).as_posix()] = path
    hashes = manifest.get("developer_tools", {})
    if not isinstance(hashes, dict) or set(hashes) != DEVELOPER_TOOLS:
        raise RuntimeError("Exact developer tool manifest required")
    expected |= set(sidecars) | {"manifest.json"} | {"tools/" + name for name in hashes}
    actual = set()
    for path in release.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise RuntimeError("Unexpected release entry")
        if path.is_file():
            actual.add(path.relative_to(release).as_posix())
    if actual != expected:
        raise RuntimeError("Developer archive contains unexpected or missing files")
    for name, original in sidecars.items():
        if (release / name).read_bytes() != original.read_bytes():
            raise RuntimeError("Stale or changed release sidecar: " + name)
    for name, checksum in hashes.items():
        if hashlib.sha256((release / "tools" / name).read_bytes()).hexdigest() != checksum:
            raise RuntimeError("Developer tool hash mismatch: " + name)
    result = []
    for name in sorted(expected):
        path = release / name
        data = path.read_bytes()
        scan_bytes(data, name)
        result.append((name, data, 0o755 if path.stat().st_mode & 0o111 else 0o644))
    return result


def main():
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+", version):
        raise RuntimeError("Expected an explicit experimental alpha version")
    source = source_files()
    release = ROOT / "build/release"
    manifest = install.read_manifest(release / "manifest.json")
    if manifest["version"] != version:
        raise RuntimeError("Prepared payload version differs from source")
    install.verify_files(release / "payload", manifest, exact_payload=True)
    install.verify_launch_plist(release / "payload", manifest)
    # Check signatures locally. Ad-hoc developer archives remain unnotarized.
    for relative in (install.SERVICE, install.DRIVER):
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(release / "payload" / relative)], check=True)
    binaries = developer_files(release, manifest)
    for name in DEVELOPER_TOOLS:
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(release / "tools" / name)], check=True)
    report_path = ROOT / "build/test-results.json"
    tests = json.loads(report_path.read_text())
    if (not tests.get("passed") or tests.get("hardware_access") or tests.get("installation_performed") or
            tests.get("source_sha256") != build.source_fingerprint() or
            manifest.get("source_sha256") != tests.get("source_sha256")):
        raise RuntimeError("Passing offline test report required")
    report_data = report_path.read_bytes()
    scan_bytes(report_data, "offline-test-results.json")
    binaries.append(("offline-test-results.json", report_data, 0o644))
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    prefix = "necromancer-audio-" + version
    source_archive = destination / (prefix + "-source.tar.gz")
    binary_archive = destination / (prefix + "-macos-arm64-developer.tar.gz")
    archive(source_archive, prefix, source)
    archive(binary_archive, prefix + "-macos-arm64-developer", binaries)
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source_archive, binary_archive)}
    (destination / "SHA256SUMS").write_text("".join(checksum + "  " + name + "\n" for name, checksum in sums.items()))
    report = {"version": version, "source_commit": git("rev-parse", "HEAD").decode().strip(),
              "source_file_count": len(source), "developer_archive_file_count": len(binaries),
              "checksums": sums, "privacy_scan": "passed", "source_working_tree": "clean",
              "source_sha256": tests["source_sha256"], "native_contracts_passed": len(tests["native_contracts"]),
              "python_tests_passed": tests["python_tests_passed"],
              "signing": manifest["signing"], "notarized": False, "published": False,
              "hardware_candidate_installed": False, "hardware_qualification": "experimental; packaged candidate hardware acceptance unqualified"}
    (destination / "release-readiness.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
