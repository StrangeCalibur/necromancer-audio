# SPDX-License-Identifier: MIT
"""Real filesystem transactions in temporary roots; no launchd, USB or root operations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mbox_install", ROOT / "tools/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Actions:
    def __init__(self):
        self.active = False
        self.fail_start = 0
        self.calls = []

    def running(self):
        return self.active

    def stop(self):
        self.calls.append("stop")
        self.active = False

    def start(self):
        self.calls.append("start")
        if self.fail_start:
            self.fail_start -= 1
            raise RuntimeError("injected bootstrap failure")
        self.active = True

    def restart_audio(self):
        self.calls.append("audio")


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.target = self.base / "mac"
        self.target.mkdir()
        self.actions = Actions()
        self.manager = installer.Installer(self.target, self.actions)
        self.source = self.fixture("old", "0.1.0-alpha.1")

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, name, version):
        source = self.base / name
        payload = source / "payload"
        for relative in installer.FILES:
            path = payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative + ":" + version)
        launch = {"Label": installer.LABEL, "ProgramArguments": ["/" + installer.SERVICE, "--serve-capture"],
                  "MachServices": {installer.LABEL: True}, "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
                  "ThrottleInterval": 10, "ProcessType": "Interactive", "Umask": 0o027,
                  "StandardOutPath": "/" + installer.LOGS + "/mbox2.log",
                  "StandardErrorPath": "/" + installer.LOGS + "/mbox2.err.log"}
        (payload / installer.PLIST).write_bytes(plistlib.dumps(launch))
        files = {p: {"sha256": installer.digest(payload / p), "mode": 0o755 if p in installer.EXECUTABLES else 0o644}
                 for p in installer.FILES}
        manifest = {"schema": 1, "version": version, "architecture": "arm64", "minimum_macos": "26.4",
                    "signing": "ad-hoc", "midi_enabled": False, "files": files}
        (source / "manifest.json").write_text(json.dumps(manifest))
        return source

    def install(self, source=None, replace=False):
        return self.manager.transact(source or self.source, replace=replace, allow_ad_hoc=True)

    def test_install_replace_uninstall_preserves_unrelated_files(self):
        unrelated = self.target / "Library/Audio/Plug-Ins/HAL/Other.driver/keep"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("keep")
        self.install()
        self.assertEqual(self.manager.installed()["version"], "0.1.0-alpha.1")
        new = self.fixture("new", "0.1.0-alpha.2")
        result = self.install(new, replace=True)
        self.assertTrue((Path(result["recovery"]) / "manifest.json").is_file())
        self.assertEqual(self.manager.installed()["version"], "0.1.0-alpha.2")
        self.manager.transact()
        self.assertIsNone(self.manager.installed())
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertFalse(self.actions.active)

    def test_replacement_failure_restores_exact_previous_payload(self):
        self.install()
        previous = self.manager.installed()
        self.actions.fail_start = 1
        with self.assertRaisesRegex(RuntimeError, "prior payload restored"):
            self.install(self.fixture("new", "0.1.0-alpha.2"), replace=True)
        self.assertEqual(self.manager.installed(), previous)
        self.assertTrue(self.actions.active)

    def test_first_install_failure_restores_absence(self):
        self.actions.fail_start = 1
        with self.assertRaisesRegex(RuntimeError, "prior payload restored"):
            self.install()
        self.assertIsNone(self.manager.installed())
        self.assertFalse(self.actions.active)

    def test_plan_has_no_filesystem_or_service_side_effects(self):
        before = list(self.target.rglob("*"))
        self.manager.preflight(self.source)
        self.assertEqual(before, list(self.target.rglob("*")))
        self.assertEqual(self.actions.calls, [])

    def test_requires_explicit_local_signature_acknowledgement(self):
        with self.assertRaisesRegex(RuntimeError, "allow-ad-hoc"):
            self.manager.transact(self.source)
        self.assertEqual(list(self.target.rglob("*")), [])

    def test_changed_source_stops_before_service_actions(self):
        (self.source / "payload" / installer.SERVICE).write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "Payload mismatch"):
            self.install()
        self.assertEqual(self.actions.calls, [])

    def test_extra_payload_stops_before_install(self):
        (self.source / "payload" / "unexpected").write_text("not allowed")
        with self.assertRaisesRegex(RuntimeError, "Unexpected or missing"):
            self.install()

    def test_manifest_cannot_target_another_system_path(self):
        path = self.source / "manifest.json"
        data = json.loads(path.read_text())
        data["files"]["../../private/evil"] = data["files"].pop(installer.SERVICE)
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "exactly the supported"):
            self.install()

    def test_source_and_destination_symlinks_are_rejected(self):
        service = self.source / "payload" / installer.SERVICE
        service.unlink()
        service.symlink_to(self.base / "outside")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.install()
        service.unlink()
        service.write_text("restored")
        (self.target / "Library").symlink_to(self.source / "payload/Library")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.install()

    def test_legacy_installation_is_preserved(self):
        legacy = self.target / installer.SERVICE
        legacy.parent.mkdir(parents=True)
        legacy.write_text("old legacy")
        with self.assertRaisesRegex(RuntimeError, "legacy installation"):
            self.install(replace=True)
        self.assertEqual(legacy.read_text(), "old legacy")
        self.assertEqual(self.actions.calls, [])

    def test_uninstall_refuses_tampered_installation(self):
        self.install()
        service = self.target / installer.SERVICE
        service.write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "Payload mismatch"):
            self.manager.transact()
        self.assertTrue(self.actions.active)

    def test_changed_launch_configuration_is_rejected_even_with_matching_hash(self):
        path = self.source / "payload" / installer.PLIST
        data = plistlib.loads(path.read_bytes())
        data["ProgramArguments"][0] = "/bin/sh"
        path.write_bytes(plistlib.dumps(data))
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][installer.PLIST]["sha256"] = installer.digest(path)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(RuntimeError, "Unexpected launch daemon"):
            self.install()

    def test_directory_access_survives_restrictive_umask(self):
        previous = os.umask(0o077)
        try:
            self.install()
        finally:
            os.umask(previous)
        for relative in (installer.STATE, installer.DRIVER, installer.DRIVER + "/Contents", installer.DRIVER + "/Contents/MacOS"):
            self.assertEqual(stat.S_IMODE((self.target / relative).stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.target / installer.RECEIPT).stat().st_mode), 0o600)

    def test_interrupted_replacement_can_recover_on_next_invocation(self):
        self.install()
        previous = self.manager.installed()
        original_start = self.actions.start
        self.actions.start = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.install(self.fixture("new", "0.1.0-alpha.2"), replace=True)
        with self.assertRaisesRegex(RuntimeError, "Interrupted transaction"):
            self.manager.installed()
        self.actions.start = original_start
        recovered = installer.Installer(self.target, self.actions).recover()
        self.assertTrue(recovered["recovered"])
        self.assertEqual(self.manager.installed(), previous)
        self.assertTrue(self.actions.active)

    def test_interrupted_first_install_recovers_to_absence(self):
        self.actions.start = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.install()
        recovered = self.manager.recover()
        self.assertFalse(recovered["installed"])
        self.assertIsNone(self.manager.installed())

    def test_recovery_refuses_unmanaged_file(self):
        self.install()
        self.actions.start = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.install(self.fixture("new", "0.1.0-alpha.2"), replace=True)
        extra = self.target / installer.DRIVER / "user-file"
        extra.write_text("preserve")
        with self.assertRaisesRegex(RuntimeError, "unmanaged driver contents"):
            self.manager.recover()
        self.assertEqual(extra.read_text(), "preserve")

    def test_orphan_journal_write_recovers_without_touching_service(self):
        self.install()
        previous = self.manager.installed()
        orphan = self.target / (installer.JOURNAL + ".next")
        orphan.write_text('{"schema":')
        before = self.actions.calls[:]
        with self.assertRaisesRegex(RuntimeError, "Incomplete journal"):
            self.manager.installed()
        self.assertTrue(self.manager.recover()["orphan_journal_cleared"])
        self.assertEqual(self.manager.installed(), previous)
        self.assertEqual(self.actions.calls, before)

    def test_unmanaged_fifo_or_directory_blocks_uninstall(self):
        self.install()
        extra = self.target / installer.DRIVER / "unknown"
        for kind in ("fifo", "directory"):
            if kind == "fifo":
                os.mkfifo(extra)
            else:
                extra.mkdir()
            with self.assertRaisesRegex(RuntimeError, "unmanaged contents"):
                self.manager.transact()
            if kind == "fifo":
                extra.unlink()
            else:
                extra.rmdir()


if __name__ == "__main__":
    unittest.main()
