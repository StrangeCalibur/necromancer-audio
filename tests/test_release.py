# SPDX-License-Identifier: MIT
"""Reject uncurated developer archive contents, including innocuous-looking recordings."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import release


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "source"
        self.prepared = self.root / "build/release"
        for name in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "tools/install.py", "docs/INSTALL.md"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("curated " + name)
            target = self.prepared / ("install.py" if name == "tools/install.py" else name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        (self.prepared / "manifest.json").write_text("manifest")
        (self.prepared / "payload").mkdir()
        (self.prepared / "payload/file").write_text("payload")
        tools = {}
        for name in release.DEVELOPER_TOOLS:
            path = self.prepared / "tools" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("compiled " + name)
            tools[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = {"files": {"file": {}}, "developer_tools": tools}

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_curated_contents_are_accepted(self):
        self.assertEqual(len(release.developer_files(self.prepared, self.manifest, self.root)), 12)

    def test_recording_firmware_crash_or_extra_binary_is_rejected(self):
        for name in ("input.wav", "firmware.bin", "report.ips", "tools/extra"):
            extra = self.prepared / name
            extra.write_bytes(b"unrecognized innocuous-looking data")
            with self.assertRaisesRegex(RuntimeError, "unexpected or missing"):
                release.developer_files(self.prepared, self.manifest, self.root)
            extra.unlink()

    def test_changed_installer_or_documentation_is_rejected(self):
        path = self.prepared / "install.py"
        path.write_text("changed installer")
        with self.assertRaisesRegex(RuntimeError, "changed release sidecar"):
            release.developer_files(self.prepared, self.manifest, self.root)

    def test_changed_known_tool_is_rejected(self):
        (self.prepared / "tools/audio_inventory").write_text("wrong binary")
        with self.assertRaisesRegex(RuntimeError, "tool hash mismatch"):
            release.developer_files(self.prepared, self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
