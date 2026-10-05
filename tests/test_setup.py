# SPDX-License-Identifier: MIT
"""Exercise the compiled native installer in disposable roots with mock services.

The alternate root and injected failures exist only in a SETUP_TEST build.
No test can invoke launchd, restart CoreAudio or open USB.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import install


class NativeSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = ROOT / "build/tests/setup-helper-test"
        cls.helper.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["xcrun", "swiftc", "-D", "SETUP_TEST", "-O", "-warnings-as-errors",
                        "-target", "arm64-apple-macos26.4", str(ROOT / "src/SetupInstaller.swift"),
                        "-o", str(cls.helper)], check=True)
        cls.shipping_helper = cls.helper.with_name("setup-helper-shipping")
        subprocess.run(["xcrun", "swiftc", "-O", "-warnings-as-errors", "-target", "arm64-apple-macos26.4",
                        str(ROOT / "src/SetupInstaller.swift"), "-o", str(cls.shipping_helper)], check=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.system = self.base / "system"
        self.system.mkdir()
        self.source = self.base / "release"
        self.source.mkdir()
        shutil.copytree(ROOT / "build/release/payload", self.source / "payload")
        shutil.copy2(ROOT / "build/release/manifest.json", self.source / "manifest.json")

    def run_helper(self, action, ok=True, extra=()):
        completed = subprocess.run([str(self.helper), action, "--test-root", str(self.system),
                                    "--source", str(self.source), *extra], capture_output=True, text=True, timeout=15)
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        else:
            self.assertNotEqual(completed.returncode, 0)
        return completed

    def snapshot(self):
        return {p.relative_to(self.system).as_posix(): p.read_bytes()
                for p in self.system.rglob("*") if p.is_file() and "/Recovery/" not in p.as_posix()
                and "/.staging-" not in p.as_posix() and p.name != ".installer.lock"}

    def manifest(self):
        return json.loads((self.source / "manifest.json").read_text())

    def test_read_only_plan(self):
        plan = json.loads(self.run_helper("plan").stdout)
        self.assertTrue(plan["preflight"])
        self.assertFalse(plan["firmware_write"])
        self.assertEqual(list(self.system.iterdir()), [])

    def test_package_verification_does_not_adopt_prototype(self):
        path = self.system / install.SERVICE
        path.parent.mkdir(parents=True); path.write_bytes(b"prototype")
        before = self.snapshot()
        self.assertTrue(json.loads(self.run_helper("verify-package").stdout)["package_verified"])
        self.assertEqual(before, self.snapshot())

    def test_fresh_install_update_uninstall(self):
        self.run_helper("install")
        self.assertTrue(json.loads(self.run_helper("status").stdout)["installed"])
        install.verify_files(self.system, install.read_manifest(self.system / install.RECEIPT))
        self.run_helper("install")
        self.assertEqual(len(list((self.system / install.STATE / "Recovery").iterdir())), 1)
        self.run_helper("uninstall")
        self.assertFalse((self.system / install.DRIVER).exists())
        self.assertFalse((self.system / install.SERVICE).exists())
        self.assertTrue((self.system / install.LOGS).exists())

    def test_unmanaged_installation_is_preserved(self):
        path = self.system / install.SERVICE
        path.parent.mkdir(parents=True); path.write_bytes(b"prototype")
        before = self.snapshot()
        self.run_helper("plan", ok=False); self.run_helper("install", ok=False)
        self.assertEqual(before, self.snapshot())

    def test_corrupt_source_rejected_before_mutation(self):
        (self.source / "payload" / install.SERVICE).write_bytes(b"tampered")
        self.run_helper("install", ok=False)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_extra_source_directory_rejected(self):
        (self.source / "payload/unknown").mkdir()
        self.run_helper("install", ok=False)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_symlink_target_rejected(self):
        (self.system / "Library").symlink_to(self.base / "outside")
        self.run_helper("install", ok=False)
        self.assertFalse((self.base / "outside").exists())

    def test_symlink_source_rejected(self):
        path = self.source / "payload" / install.SERVICE
        original = self.base / "service"; path.replace(original); path.symlink_to(original)
        self.run_helper("install", ok=False)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_tampered_installed_file_rejected(self):
        self.run_helper("install")
        (self.system / install.SERVICE).write_bytes(b"unknown")
        before = self.snapshot(); self.run_helper("uninstall", ok=False)
        self.assertEqual(before, self.snapshot())

    def test_extra_installed_directory_rejected(self):
        self.run_helper("install")
        (self.system / install.DRIVER / "unknown").mkdir()
        self.run_helper("uninstall", ok=False)
        self.assertTrue((self.system / install.DRIVER / "unknown").exists())

    def test_changed_permissions_rejected(self):
        self.run_helper("install")
        (self.system / install.SERVICE).chmod(0o777)
        self.run_helper("install", ok=False)
        self.assertEqual((self.system / install.SERVICE).stat().st_mode & 0o777, 0o777)

    def test_fresh_start_failure_restores_absence(self):
        self.run_helper("install", ok=False, extra=("--test-failure", "start"))
        for name in install.TARGETS:
            self.assertFalse((self.system / name).exists())
        self.assertFalse((self.system / install.JOURNAL).exists())

    def test_update_failure_restores_previous_payload(self):
        self.run_helper("install")
        before = self.snapshot()
        self.run_helper("install", ok=False, extra=("--test-failure", "start"))
        self.assertEqual(before, self.snapshot())

    def test_interrupted_fresh_install_recovery(self):
        result = self.run_helper("install", ok=False, extra=("--test-failure", "interrupt"))
        self.assertEqual(result.returncode, 99)
        self.assertTrue(json.loads(self.run_helper("status").stdout)["needs_recovery"])
        self.run_helper("install", ok=False)
        self.run_helper("recover")
        self.assertFalse((self.system / install.SERVICE).exists())
        self.assertFalse((self.system / install.JOURNAL).exists())

    def test_interrupted_update_recovery(self):
        self.run_helper("install"); before = self.snapshot()
        self.run_helper("install", ok=False, extra=("--test-failure", "interrupt"))
        self.run_helper("recover")
        self.assertEqual(before, self.snapshot())

    def test_recovery_refuses_unknown_driver_contents(self):
        self.run_helper("install")
        self.run_helper("install", ok=False, extra=("--test-failure", "interrupt"))
        path = self.system / install.DRIVER / "unknown"
        path.parent.mkdir(parents=True); path.write_bytes(b"preserve")
        self.run_helper("recover", ok=False)
        self.assertEqual(path.read_bytes(), b"preserve")
        self.assertTrue((self.system / install.JOURNAL).exists())

    def test_orphan_journal_cleared_without_payload_change(self):
        self.run_helper("install"); before = self.snapshot()
        orphan = self.system / (install.JOURNAL + ".next")
        orphan.write_text("incomplete")
        self.run_helper("recover")
        self.assertEqual(before, self.snapshot())

    def test_unrelated_driver_preserved(self):
        unrelated = self.system / "Library/Audio/Plug-Ins/HAL/Other.driver/keep"
        unrelated.parent.mkdir(parents=True); unrelated.write_bytes(b"keep")
        self.run_helper("install"); self.run_helper("uninstall")
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_midi_package_rejected(self):
        manifest = self.manifest(); manifest["midi_enabled"] = True
        (self.source / "manifest.json").write_text(json.dumps(manifest))
        self.run_helper("install", ok=False)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_daemon_options_checked(self):
        import hashlib
        import plistlib
        path = self.source / "payload" / install.PLIST
        data = plistlib.loads(path.read_bytes()); data["RunAtLoad"] = False
        path.write_bytes(plistlib.dumps(data))
        manifest = self.manifest(); manifest["files"][install.PLIST]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.source / "manifest.json").write_text(json.dumps(manifest))
        self.run_helper("install", ok=False)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_test_helper_cannot_use_live_root(self):
        result = subprocess.run([str(self.helper), "install", "--test-root", "/", "--source", str(self.source)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_shipping_helper_rejects_test_interfaces(self):
        result = subprocess.run([str(self.shipping_helper), "install", "--test-root", str(self.system)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown setup argument", result.stdout)
        self.assertEqual(list(self.system.iterdir()), [])

    def test_shipping_helper_rejects_arbitrary_source(self):
        result = subprocess.run([str(self.shipping_helper), "install", "--source", str(self.source)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown setup argument", result.stdout)
        self.assertEqual(list(self.system.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
