#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a native setup app/DMG locally. Upload only with explicit --notarize-profile.

Never installs files, opens USB, changes services or publishes a GitHub release.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import build
import install

APP_NAME = "Necromancer Audio Setup.app"


def prepare_icon(app):
    """Build all standard macOS icon representations from the curated master."""
    source = build.ROOT / "assets/AppIcon.png"
    with tempfile.TemporaryDirectory(prefix="app-icon-", dir=app.parent) as temporary:
        iconset = Path(temporary) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "@2x" if scale == 2 else ""
                target = iconset / f"icon_{size}x{size}{suffix}.png"
                build.run(["/usr/bin/sips", "--resampleHeightWidth", size * scale, size * scale,
                           source, "--out", target], capture_output=True)
        build.run(["/usr/bin/iconutil", "--convert", "icns", "--output",
                   app / "Contents/Resources/AppIcon.icns", iconset])


def prepare(identity):
    release = build.BUILD / "release"
    manifest = install.read_manifest(release / "manifest.json")
    if manifest["source_sha256"] != build.source_fingerprint():
        raise RuntimeError("Rebuild the payload from current source before preparing setup.")
    tests = json.loads((build.BUILD / "test-results.json").read_text())
    if (not tests.get("passed") or tests.get("source_sha256") != manifest["source_sha256"] or
            tests.get("hardware_access") or tests.get("installation_performed")):
        raise RuntimeError("Passing matching offline verification is required before setup packaging.")
    if manifest.get("midi_enabled"):
        raise RuntimeError("The user setup app requires an audio-only payload.")
    if (identity == "-") != (manifest["signing"] == "ad-hoc"):
        raise RuntimeError("Setup and payload signing modes must match.")
    install.verify_files(release / "payload", manifest, exact_payload=True)
    install.verify_launch_plist(release / "payload", manifest)
    # A local cache avoids cloud-provider metadata racing codesign under Documents.
    # The final sealed DMG is copied back to the repository's ignored dist folder.
    workspace = Path.home() / "Library/Caches/NecromancerAudio/Setup" / manifest["source_sha256"]
    workspace.mkdir(parents=True, exist_ok=True)
    app = workspace / APP_NAME
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    for name in ("MacOS", "Helpers", "Resources/Release"):
        (contents / name).mkdir(parents=True)
    destination = contents / "Resources/Release"
    shutil.copytree(release / "payload", destination / "payload")
    shutil.copy2(release / "manifest.json", destination / "manifest.json")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(build.ROOT / name, contents / "Resources" / name)
    prepare_icon(app)
    info = {"CFBundleIdentifier": "audio.necromancer.mbox2.setup", "CFBundleName": "Necromancer Audio Setup",
            "CFBundleExecutable": "NecromancerSetup", "CFBundlePackageType": "APPL",
            "CFBundleIconFile": "AppIcon.icns",
            "CFBundleVersion": "0.1.0", "CFBundleShortVersionString": "0.1.0",
            "NecromancerPrereleaseVersion": manifest["version"], "LSMinimumSystemVersion": build.MIN_MACOS,
            "NSHighResolutionCapable": True, "CFBundleSupportedPlatforms": ["MacOSX"]}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    for source, output in (("SetupInstaller.swift", contents / "Helpers/setup-helper"),
                           ("SetupApp.swift", contents / "MacOS/NecromancerSetup")):
        build.run(["xcrun", "swiftc", "-O", "-warnings-as-errors", "-target", "arm64-apple-macos" + build.MIN_MACOS,
                   "-file-prefix-map", str(build.ROOT) + "=.", build.ROOT / "src" / source, "-o", output])
        build.sign(output, identity)
    build.sign(app, identity)
    build.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app])
    return app, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sign", default="-", help="explicit Developer ID Application identity")
    parser.add_argument("--notarize-profile", help="explicit saved notarytool Keychain profile; uploads the signed app to Apple")
    args = parser.parse_args()
    if args.notarize_profile and args.sign == "-":
        raise RuntimeError("Notarization requires Developer ID signing.")
    app, manifest = prepare(args.sign)
    destination = build.ROOT / "dist"
    destination.mkdir(exist_ok=True)
    prefix = "necromancer-audio-" + manifest["version"] + "-macos-arm64-setup-candidate"
    notarized = False
    if args.notarize_profile:
        upload = app.parent / "notarization-upload.zip"
        build.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", app, upload])
        response = subprocess.run(["xcrun", "notarytool", "submit", str(upload), "--keychain-profile", args.notarize_profile,
                                   "--wait", "--output-format", "json"], check=True, capture_output=True, text=True)
        result = json.loads(response.stdout)
        if result.get("status") != "Accepted":
            raise RuntimeError("Apple did not accept the notarization submission. Preserve the submission ID and inspect its log.")
        build.run(["xcrun", "stapler", "staple", app])
        build.run(["xcrun", "stapler", "validate", app])
        notarized = True
    stage = app.parent / "dmg-root"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copytree(app, stage / APP_NAME)
    (stage / "Applications").symlink_to("/Applications")
    (stage / "Read me.txt").write_text("Copy Necromancer Audio Setup to Applications, then open it.\n"
        "This is a beta preparation candidate. Hardware acceptance remains in progress.\n"
        "Original Mbox 2, existing firmware 1.43, Apple silicon, stereo analog audio at 48 kHz.\n"
        "MIDI and S/PDIF remain experimental. See the repository qualification record.\n")
    dmg = app.parent / (prefix + ".dmg")
    dmg.unlink(missing_ok=True)
    build.run(["/usr/bin/hdiutil", "create", "-volname", "Necromancer Audio Setup", "-srcfolder", stage,
               "-format", "UDZO", "-ov", dmg])
    build.sign(dmg, args.sign)
    if notarized:
        # A container needs its own notarization/staple even when the inner app is stapled.
        result = subprocess.run(["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile", args.notarize_profile,
                                 "--wait", "--output-format", "json"], check=True, capture_output=True, text=True)
        if json.loads(result.stdout).get("status") != "Accepted":
            raise RuntimeError("Apple did not accept the DMG submission.")
        build.run(["xcrun", "stapler", "staple", dmg]); build.run(["xcrun", "stapler", "validate", dmg])
    if manifest["source_sha256"] != build.source_fingerprint():
        raise RuntimeError("Source changed during packaging; rebuild and reverify.")
    checksum = hashlib.sha256(dmg.read_bytes()).hexdigest()
    artifact = destination / dmg.name
    shutil.copyfile(dmg, artifact)
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != checksum:
        raise RuntimeError("Final setup artifact differs from its signed container.")
    report = {"version": manifest["version"], "artifact": dmg.name, "sha256": checksum,
              "source_sha256": manifest["source_sha256"], "signing": manifest["signing"], "notarized": notarized,
              "requires_python_on_user_mac": False, "hardware_candidate_installed": False,
              "qualification": "beta preparation candidate; live acceptance remains open", "published": False}
    (destination / (prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
