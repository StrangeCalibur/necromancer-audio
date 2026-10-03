#!/usr/bin/env python3
"""Plan, install, replace or remove the experimental Mbox 2 audio payload.

Planning is read-only. Install/uninstall require root and restart CoreAudio.
This alpha installer requires Python 3.10+; it does not change firmware or security settings.
"""
# SPDX-License-Identifier: MIT
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import uuid

LABEL = "audio.necromancer.mbox2.transport"
STATE = "Library/Application Support/Necromancer Audio/Mbox2"
SERVICE = STATE + "/mbox_service"
DRIVER = "Library/Audio/Plug-Ins/HAL/NecromancerMbox2.driver"
PLIST = "Library/LaunchDaemons/" + LABEL + ".plist"
RECEIPT = STATE + "/install-receipt.json"
JOURNAL = STATE + "/pending-transaction.json"
LOGS = "Library/Logs/Necromancer Audio"
EXECUTABLES = {SERVICE, DRIVER + "/Contents/MacOS/NecromancerMbox2"}
FILES = EXECUTABLES | {PLIST, DRIVER + "/Contents/Info.plist", DRIVER + "/Contents/_CodeSignature/CodeResources"}
FILES |= {DRIVER + "/Contents/Resources/" + n for n in ("LICENSE", "libASPL-LICENSE", "libASPL-LICENSE.apple2012", "libASPL-LICENSE.apple2020")}
TARGETS = (SERVICE, DRIVER, PLIST)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_symlinks(path, boundary):
    path = Path(path)
    boundary = Path(boundary)
    if path != boundary and boundary not in path.parents:
        raise RuntimeError("Path escaped its allowed root")
    while True:
        if path.is_symlink():
            raise RuntimeError("Refusing symlink: " + str(path))
        if path == boundary:
            break
        path = path.parent


def read_manifest(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise RuntimeError("Invalid manifest file")
    return validate_manifest(json.loads(path.read_text()))


def validate_manifest(data):
    if not isinstance(data, dict):
        raise RuntimeError("Manifest must be an object")
    if data.get("schema") != 1 or data.get("architecture") != "arm64" or data.get("minimum_macos") != "26.4":
        raise RuntimeError("Unsupported manifest schema or platform")
    if not isinstance(data.get("version"), str) or not data["version"] or data.get("signing") not in ("ad-hoc", "identity-signed"):
        raise RuntimeError("Invalid release metadata")
    if not isinstance(data.get("files"), dict) or set(data["files"]) != FILES:
        raise RuntimeError("Manifest must contain exactly the supported audio payload")
    for name, entry in data["files"].items():
        parts = PurePosixPath(name).parts
        if PurePosixPath(name).is_absolute() or ".." in parts or not isinstance(entry, dict):
            raise RuntimeError("Invalid manifest path")
        expected_mode = 0o755 if name in EXECUTABLES else 0o644
        checksum = entry.get("sha256", "")
        if entry.get("mode") != expected_mode or not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise RuntimeError("Invalid file mode or checksum: " + name)
    return data


def verify_files(base, manifest, exact_payload=False):
    for name, entry in manifest["files"].items():
        path = base / name
        no_symlinks(path, base)
        if not path.is_file() or digest(path) != entry["sha256"]:
            raise RuntimeError("Payload mismatch: " + name)
    if exact_payload:
        actual = set()
        for path in base.rglob("*"):
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                raise RuntimeError("Unexpected payload file type")
            if path.is_file():
                actual.add(path.relative_to(base).as_posix())
        if actual != set(manifest["files"]):
            raise RuntimeError("Unexpected or missing payload files")
    else:
        expected = {p for p in manifest["files"] if p.startswith(DRIVER + "/")}
        allowed_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents}
        actual = set()
        for path in (base / DRIVER).rglob("*"):
            relative = path.relative_to(base).as_posix()
            if path.is_symlink() or (not path.is_dir() and not path.is_file()) or (path.is_dir() and relative not in allowed_dirs):
                raise RuntimeError("Installed driver contains unmanaged contents")
            if path.is_file():
                actual.add(relative)
        if actual != expected:
            raise RuntimeError("Installed driver contains unmanaged files")


def verify_launch_plist(base, manifest):
    data = plistlib.loads((base / PLIST).read_bytes())
    args = data.get("ProgramArguments", [])
    if data.get("Label") != LABEL or args[:2] != ["/" + SERVICE, "--serve-capture"]:
        raise RuntimeError("Unexpected launch daemon")
    tail = args[2:]
    if tail[:1] == ["--location-id"]:
        if len(tail) < 2 or not isinstance(tail[1], str) or not tail[1].isdigit() or not 0 <= int(tail[1]) <= 0xffffffff:
            raise RuntimeError("Invalid USB location pin")
        tail = tail[2:]
    if tail != (["--enable-midi"] if manifest.get("midi_enabled") else []):
        raise RuntimeError("Unexpected daemon arguments")
    allowed = {"Label", "ProgramArguments", "MachServices", "RunAtLoad", "KeepAlive", "ThrottleInterval", "ProcessType", "Umask", "StandardOutPath", "StandardErrorPath"}
    if set(data) != allowed or data.get("MachServices") != {LABEL: True} or data.get("Umask") != 0o027:
        raise RuntimeError("Unexpected daemon configuration")
    for field, leaf in (("StandardOutPath", "mbox2.log"), ("StandardErrorPath", "mbox2.err.log")):
        if data.get(field) != "/" + LOGS + "/" + leaf:
            raise RuntimeError("Unexpected log path")


class SystemActions:
    """Live launchd actions; filesystem tests substitute a recorder."""
    @staticmethod
    def running():
        return subprocess.run(["/bin/launchctl", "print", "system/" + LABEL], capture_output=True).returncode == 0

    @staticmethod
    def stop():
        subprocess.run(["/bin/launchctl", "bootout", "system/" + LABEL], check=True)

    @staticmethod
    def start():
        subprocess.run(["/bin/launchctl", "bootstrap", "system", "/" + PLIST], check=True)

    @staticmethod
    def restart_audio():
        # coreaudiod may not be running yet; launchd starts it when needed.
        subprocess.run(["/usr/bin/killall", "coreaudiod"], check=False, capture_output=True)


class Installer:
    def __init__(self, root=Path("/"), actions=None):
        self.root = Path(root).resolve()
        self.live = self.root == Path("/")
        if not self.live and actions is None:
            raise RuntimeError("Offline filesystem roots require mock service actions")
        self.actions = actions if actions is not None else SystemActions()

    def path(self, relative):
        target = self.root / relative
        no_symlinks(target, self.root)
        return target

    def permissions(self, path):
        if not self.live:
            return
        current = path
        while current != self.root:
            if current.exists():
                st = current.stat()
                if st.st_uid != 0 or st.st_mode & 0o022:
                    raise RuntimeError("Installed path is not protected by root: " + str(current))
            current = current.parent

    def mkdir(self, path, mode=0o755):
        # Only newly created directories are changed. Shared system ancestors
        # are checked, never chmod'd. Explicit modes work with umask 000 or 077.
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        self.permissions(current)
        for directory in reversed(missing):
            directory.mkdir(mode=mode if directory == path else 0o755)
            directory.chmod(mode if directory == path else 0o755)
            if self.live:
                os.chown(directory, 0, 0)

    def installed(self, ignore_orphan=False):
        if self.path(JOURNAL).exists():
            raise RuntimeError("Interrupted transaction found. Run 'recover' before another install or uninstall.")
        if not ignore_orphan and self.path(JOURNAL + ".next").exists():
            raise RuntimeError("Incomplete journal write found. Run 'recover' before another transaction.")
        receipt = self.path(RECEIPT)
        if not receipt.exists():
            if any(self.path(p).exists() for p in TARGETS):
                raise RuntimeError("An unmanaged or legacy installation is present. Preserve it; see docs/INSTALL.md before migration.")
            return None
        self.permissions(receipt)
        old = read_manifest(receipt)
        verify_files(self.root, old)
        for name, entry in old["files"].items():
            target = self.path(name)
            self.permissions(target)
            if stat.S_IMODE(target.stat().st_mode) != entry["mode"]:
                raise RuntimeError("Installed permissions changed: " + name)
        return old

    def preflight(self, source=None, replace=False, allow_ad_hoc=False, mutate=False):
        if mutate:
            self.platform_guard()
        for name in (*TARGETS, RECEIPT, LOGS):
            self.permissions(self.path(name))
        for name in ("mbox2.log", "mbox2.err.log"):
            path = self.path(LOGS + "/" + name)
            if path.exists() and not path.is_file():
                raise RuntimeError("Log target is not a regular file")
            self.permissions(path)
        old = self.installed()
        if source is None:
            if old is None:
                raise RuntimeError("No managed installation found")
            return old, None
        source = Path(source).absolute()
        no_symlinks(source, Path(source.anchor))
        new = read_manifest(source / "manifest.json")
        verify_files(source / "payload", new, exact_payload=True)
        verify_launch_plist(source / "payload", new)
        if old and not replace:
            raise RuntimeError("Managed installation exists; use --replace after reviewing the plan.")
        if mutate and new["signing"] == "ad-hoc" and not allow_ad_hoc:
            raise RuntimeError("Local ad-hoc build: --allow-ad-hoc explicitly acknowledges this developer install.")
        if self.live:
            for relative in (SERVICE, DRIVER):
                command = ["/usr/bin/codesign", "--verify", "--strict"]
                if new["signing"] != "ad-hoc":
                    command += ["-R=anchor apple generic"]
                subprocess.run([*command, str(source / "payload" / relative)], check=True)
        return old, new

    def platform_guard(self):
        if self.live:
            if os.geteuid() != 0:
                raise RuntimeError("Administrator authentication required: run this command with sudo.")
            if platform.system() != "Darwin" or platform.machine() != "arm64":
                raise RuntimeError("Apple silicon macOS required")
            if tuple(int(x) for x in platform.mac_ver()[0].split(".")[:2]) < (26, 4):
                raise RuntimeError("macOS 26.4 or newer required")

    @staticmethod
    def sync_directory(path):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_json(self, relative, data):
        path = self.path(relative)
        temp = self.path(relative + ".next")
        with temp.open("x") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(0o600)
        os.replace(temp, path)
        self.sync_directory(path.parent)

    def clear_journal(self):
        self.path(JOURNAL).unlink(missing_ok=True)
        self.sync_directory(self.path(STATE))

    @contextmanager
    def lock(self):
        path = self.path(STATE + "/.installer.lock")
        self.mkdir(path.parent)
        self.permissions(path)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RuntimeError("Installer lock is not a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def copy_payload(self, source, manifest):
        for name, entry in manifest["files"].items():
            target = self.path(name)
            self.mkdir(target.parent)
            temp = self.path(name + ".next")
            with (source / name).open("rb") as stream, temp.open("xb") as copied:
                shutil.copyfileobj(stream, copied)
                copied.flush()
                os.fsync(copied.fileno())
            temp.chmod(entry["mode"])
            if self.live:
                os.chown(temp, 0, 0)
            os.replace(temp, target)
            self.sync_directory(target.parent)

    def remove_payload(self):
        for name in TARGETS:
            target = self.path(name)
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        self.path(RECEIPT).unlink(missing_ok=True)

    def write_receipt(self, manifest):
        self.write_json(RECEIPT, manifest)

    def recover(self):
        """Restore the previous payload after process death/reboot; never adopt a legacy install."""
        self.platform_guard()
        with self.lock():
            journal = self.path(JOURNAL)
            self.permissions(journal)
            if not journal.exists():
                orphan = self.path(JOURNAL + ".next")
                self.permissions(orphan)
                if not orphan.is_file():
                    raise RuntimeError("No recoverable transaction journal found")
                # No payload modification can precede publication of the journal.
                # Verify that the previous installation (or absence) is intact.
                old = self.installed(ignore_orphan=True)
                orphan.unlink()
                self.sync_directory(orphan.parent)
                return {"recovered": True, "orphan_journal_cleared": True,
                        "installed": old is not None, "version": old["version"] if old else None,
                        "coreaudio_restarted": False, "hardware_audio_verified": False}
            if journal.stat().st_size > 256 * 1024:
                raise RuntimeError("Invalid transaction journal")
            data = json.loads(journal.read_text())
            if not isinstance(data, dict):
                raise RuntimeError("Invalid transaction journal")
            transaction = data.get("transaction", "")
            if (data.get("schema") != 1 or not isinstance(transaction, str) or len(transaction) != 32 or
                    any(c not in "0123456789abcdef" for c in transaction) or
                    type(data.get("had_previous")) is not bool or type(data.get("was_running")) is not bool):
                raise RuntimeError("Invalid transaction journal")
            new = validate_manifest(data["new_manifest"]) if data.get("new_manifest") is not None else None
            recovery = self.path(STATE + "/Recovery/" + transaction)
            old = read_manifest(recovery / "manifest.json") if data["had_previous"] else None
            if old:
                no_symlinks(recovery, self.root)
                self.permissions(recovery)
                verify_files(recovery / "payload", old, exact_payload=True)
            # Interrupted atomic copies leave only known complete files and known
            # .next temporary files in protected directories. Never delete extras.
            allowed = set(FILES) | {p + ".next" for p in FILES}
            allowed_dirs = {str(parent) for name in FILES for parent in PurePosixPath(name).parents}
            for path in self.path(DRIVER).rglob("*"):
                relative = path.relative_to(self.root).as_posix()
                if (path.is_symlink() or (not path.is_file() and not path.is_dir()) or
                        (path.is_file() and relative not in allowed) or (path.is_dir() and relative not in allowed_dirs)):
                    raise RuntimeError("Recovery found unmanaged driver contents")
            for name in FILES:
                path = self.path(name)
                self.permissions(path)
                if path.exists():
                    hashes = [m["files"][name]["sha256"] for m in (old, new) if m]
                    if not path.is_file() or digest(path) not in hashes:
                        raise RuntimeError("Recovery found an unknown installed file: " + name)
                temp = self.path(name + ".next")
                self.permissions(temp)
                if temp.exists() and not temp.is_file():
                    raise RuntimeError("Invalid temporary payload file")
            receipt = self.path(RECEIPT)
            if receipt.exists() and read_manifest(receipt) not in (old, new):
                raise RuntimeError("Recovery found an unknown receipt")
            if self.actions.running():
                self.actions.stop()
            self.remove_payload()
            for name in (*FILES, RECEIPT):
                self.path(name + ".next").unlink(missing_ok=True)
            if old:
                self.copy_payload(recovery / "payload", old)
                self.write_receipt(old)
                verify_files(self.root, old)
                if data["was_running"]:
                    self.actions.start()
            self.actions.restart_audio()
            self.clear_journal()
            staging = self.path(STATE + "/.staging-" + transaction)
            if staging.exists():
                shutil.rmtree(staging)
            return {"recovered": True, "installed": old is not None, "version": old["version"] if old else None,
                    "recovery": str(recovery) if old else None, "hardware_audio_verified": False}

    def transact(self, source=None, replace=False, allow_ad_hoc=False):
        # Check before creating even a lock or staging directory.
        self.preflight(source, replace, allow_ad_hoc, mutate=True)
        with self.lock():
            old, new = self.preflight(source, replace, allow_ad_hoc, mutate=True)
            was_running = self.actions.running()
            if was_running and old is None:
                raise RuntimeError("An unmanaged service already owns the launchd label")
            transaction = uuid.uuid4().hex
            staging = self.path(STATE + "/.staging-" + transaction)
            recovery = self.path(STATE + "/Recovery/" + transaction) if old else None
            staging.mkdir(mode=0o700)
            modified = False
            stopped = False
            try:
                if new:
                    shutil.copytree(Path(source) / "payload", staging / "payload")
                    verify_files(staging / "payload", new, exact_payload=True)
                if old:
                    recovery.mkdir(parents=True, mode=0o700)
                    for name in old["files"]:
                        target = recovery / "payload" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(self.path(name), target)
                    shutil.copy2(self.path(RECEIPT), recovery / "manifest.json")
                    verify_files(recovery / "payload", old, exact_payload=True)
                    for path in recovery.rglob("*"):
                        if path.is_file():
                            with path.open("rb") as stream:
                                os.fsync(stream.fileno())
                    for path in sorted([recovery, *(p for p in recovery.rglob("*") if p.is_dir())], key=lambda p:len(p.parts), reverse=True):
                        self.sync_directory(path)
                    self.sync_directory(recovery.parent)
                self.write_json(JOURNAL, {"schema": 1, "transaction": transaction,
                                          "had_previous": old is not None, "was_running": was_running,
                                          "new_manifest": new})
                if was_running:
                    self.actions.stop()
                    stopped = True
                modified = True
                self.remove_payload()
                if new:
                    self.copy_payload(staging / "payload", new)
                    self.mkdir(self.path(LOGS))
                    for name in ("mbox2.log", "mbox2.err.log"):
                        path = self.path(LOGS + "/" + name)
                        path.touch(exist_ok=True)
                        path.chmod(0o640)
                    verify_files(self.root, new)
                    self.write_receipt(new)
                    self.actions.start()
                self.actions.restart_audio()
                self.clear_journal()
            except Exception as error:
                try:
                    if modified:
                        if self.actions.running():
                            self.actions.stop()
                        self.remove_payload()
                        for name in (*FILES, RECEIPT):
                            self.path(name + ".next").unlink(missing_ok=True)
                        if old:
                            self.copy_payload(recovery / "payload", old)
                            self.write_receipt(old)
                            verify_files(self.root, old)
                    if old and was_running and (modified or stopped):
                        self.actions.start()
                    if modified or stopped:
                        self.actions.restart_audio()
                    self.clear_journal()
                except Exception as rollback_error:
                    raise RuntimeError("Update failed and automatic recovery failed. Retained backup: " + str(recovery)) from rollback_error
                raise RuntimeError("Transaction failed; prior payload restored: " + str(error)) from error
            finally:
                if not self.path(JOURNAL).exists():
                    shutil.rmtree(staging)
            return {"installed": new is not None, "version": new["version"] if new else None,
                    "recovery": str(recovery) if recovery else None, "coreaudio_restarted": True,
                    "hardware_audio_verified": False}


def main(argv=None):
    here = Path(__file__).resolve().parent
    default_source = here if (here / "manifest.json").is_file() else here.parent / "build/release"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "install", "uninstall", "status", "recover"))
    parser.add_argument("--source", type=Path, default=default_source)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--allow-ad-hoc", action="store_true")
    args = parser.parse_args(argv)
    installer = Installer()
    try:
        if args.action == "recover":
            result = installer.recover()
        elif args.action == "status":
            current = installer.installed()
            result = {"installed": current is not None, "version": current["version"] if current else None}
        elif args.action == "plan":
            old, new = installer.preflight(args.source, args.replace)
            result = {"preflight": True, "replaces": old["version"] if old else None,
                      "version": new["version"], "files": len(new["files"]), "targets": ["/" + p for p in TARGETS],
                      "signing": new["signing"], "requires_admin": True, "restarts_coreaudio": True,
                      "initializes_usb_on_start": True, "firmware_write": False}
        else:
            result = installer.transact(args.source if args.action == "install" else None,
                                        args.replace, args.allow_ad_hoc)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Installer stopped: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
