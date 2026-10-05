#!/usr/bin/env python3
"""Build the experimental alpha with Apple tools and a hash-pinned source dependency.

No device access, installation, credential discovery, uploads or publication.
"""
# SPDX-License-Identifier: MIT
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
CACHE = ROOT / ".cache"
MIN_MACOS = "26.4"
LABEL = "audio.necromancer.mbox2.transport"
SERVICE = "Library/Application Support/Necromancer Audio/Mbox2/mbox_service"
DRIVER = "Library/Audio/Plug-Ins/HAL/NecromancerMbox2.driver"
PLIST = "Library/LaunchDaemons/" + LABEL + ".plist"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_fingerprint():
    checksum = hashlib.sha256()
    paths = [ROOT / "VERSION", ROOT / "dependencies.json"]
    for folder in ("src", "tests", "tools"):
        paths += [p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in (".m", ".mm", ".h", ".hpp", ".c", ".cpp", ".py")]
    for path in sorted(paths):
        checksum.update(path.relative_to(ROOT).as_posix().encode())
        checksum.update(b"\0")
        checksum.update(path.read_bytes())
        checksum.update(b"\0")
    return checksum.hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def dependency(offline=False):
    spec = json.loads((ROOT / "dependencies.json").read_text())["libASPL"]
    CACHE.mkdir(exist_ok=True)
    archive = CACHE / "libaspl.tar.gz"
    if not archive.exists():
        if offline:
            raise RuntimeError("Dependency archive is absent. Run the build once with network access.")
        print("Downloading the pinned public libASPL source archive", flush=True)
        with urllib.request.urlopen(spec["archive"], timeout=60) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != spec["sha256"]:
            raise RuntimeError("Dependency archive hash/size mismatch")
        archive.write_bytes(data)
    if archive.is_symlink() or digest(archive) != spec["sha256"]:
        raise RuntimeError("Cached dependency archive failed verification")
    # Re-extract verified source; stale or locally modified dependency files cannot enter a build.
    dep = CACHE / "libASPL"
    if dep.is_symlink():
        raise RuntimeError("Dependency directory must not be a symlink")
    with tempfile.TemporaryDirectory(prefix="libaspl-", dir=CACHE) as temp:
        extracted = Path(temp)
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != "libASPL-" + spec["commit"] or ".." in parts or member.issym() or member.islnk():
                    raise RuntimeError("Unexpected dependency archive entry")
                target = extracted.joinpath(*parts[1:])
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as stream:
                        target.write_bytes(stream.read())
                else:
                    raise RuntimeError("Unsupported dependency archive entry")
        if dep.exists():
            shutil.rmtree(dep)
        shutil.copytree(extracted, dep)
    return dep, spec


def toolchain():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This alpha build targets an Apple-silicon Mac (arm64).")
    sdk = run(["xcrun", "--show-sdk-version"], capture_output=True, text=True).stdout.strip()
    if tuple(int(x) for x in sdk.split(".")[:2]) < (26, 4):
        raise RuntimeError("A macOS 26.4 or newer SDK is required by IOUSBHost shared transaction buffers.")
    compiler = run(["xcrun", "clang", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    return {"sdk": sdk, "compiler": compiler, "architecture": "arm64", "minimum_macos": MIN_MACOS}


def flags():
    return ["-arch", "arm64", "-mmacosx-version-min=" + MIN_MACOS, "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wno-unused-parameter", "-Wno-deprecated-declarations", "-I" + str(ROOT / "src"),
            "-ffile-prefix-map=" + str(ROOT) + "=."]


def compile_file(source, target, dep, library=None, bundle=False, sanitizer=False):
    cxx = source.suffix in (".mm", ".cpp")
    objc = source.suffix in (".m", ".mm")
    args = ["xcrun", "clang++" if cxx else "clang", *flags(), "-std=c++17" if cxx else "-std=c11"]
    if objc:
        args += ["-fobjc-arc", "-fblocks", "-framework", "Foundation"]
    if cxx:
        args += ["-isystem", dep / "include", "-framework", "CoreAudio"]
    if source.name in ("mbox_native.m", "test_mbox_midi_transport.m", "test_device_profile.m"):
        args += ["-framework", "IOUSBHost", "-framework", "IOKit"]
    if "midi" in source.name and objc:
        args += ["-framework", "CoreMIDI"]
    if source.name == "audio_inventory.m":
        args += ["-framework", "CoreAudio"]
    if sanitizer:
        args += ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    if bundle:
        args += ["-bundle"]
    args += [source]
    if library:
        args += [library]
    args += ["-o", target]
    run(args)


def build_library(dep, jobs, env):
    objects = BUILD / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    sources = sorted((dep / "src").glob("*.cpp"))
    fingerprint = hashlib.sha256(json.dumps(env, sort_keys=True).encode())
    fingerprint.update(Path(__file__).read_bytes())
    for path in sorted([*(dep / "include").rglob("*.hpp"), *sources]):
        fingerprint.update(path.relative_to(dep).as_posix().encode())
        fingerprint.update(path.read_bytes())
    stamp = objects / "fingerprint"
    changed = not stamp.exists() or stamp.read_text() != fingerprint.hexdigest()

    def compile_one(path):
        target = objects / (path.name + ".o")
        if changed or not target.exists():
            run(["xcrun", "clang++", "-std=c++17", "-arch", "arm64", "-mmacosx-version-min=" + MIN_MACOS,
                 "-O2", "-fPIC", "-Wno-invalid-constexpr", "-Wno-reorder-init-list", "-I" + str(dep / "include"),
                 "-ffile-prefix-map=" + str(ROOT) + "=.", "-c", path, "-o", target])
        return target

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        compiled = list(pool.map(compile_one, sources))
    library = objects / "libASPL.a"
    run(["xcrun", "ar", "rcs", library, *compiled])
    stamp.write_text(fingerprint.hexdigest())
    return library


def sign(path, identity):
    args = ["/usr/bin/codesign", "--force", "--sign", identity]
    if identity != "-":
        args += ["--options", "runtime", "--timestamp"]
    run([*args, path])
    run(["/usr/bin/codesign", "--verify", "--strict", path])


def build(args):
    env = toolchain()
    source_sha256 = source_fingerprint()
    version = (ROOT / "VERSION").read_text().strip()
    if ('#define MBOX_VERSION "' + version + '"') not in (ROOT / "src/mbox_options.h").read_text():
        raise RuntimeError("VERSION and native version disagree")
    dep, spec = dependency(args.offline)
    BUILD.mkdir(exist_ok=True)
    library = build_library(dep, args.jobs, env)
    binaries = BUILD / "bin"
    binaries.mkdir(exist_ok=True)
    units = [(ROOT / "src/mbox_native.m", "mbox_service"), (ROOT / "src/mbox_midi_bridge.m", "mbox_midi_bridge")]
    units += [(p, p.stem) for p in sorted((ROOT / "tools").glob("*.m*")) if p.suffix in (".m", ".mm")]
    for source, name in units:
        compile_file(source, binaries / name, dep)
        sign(binaries / name, args.sign)
    bundle = BUILD / "NecromancerMbox2.driver"
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "Contents/MacOS").mkdir(parents=True)
    resources = bundle / "Contents/Resources"
    resources.mkdir()
    compile_file(ROOT / "src/MboxDriver.mm", bundle / "Contents/MacOS/NecromancerMbox2", dep, library, bundle=True)
    factory = "93D58921-CDFD-473A-954A-B3BCD2082F02"
    info = {"CFBundleExecutable": "NecromancerMbox2", "CFBundleIdentifier": "audio.necromancer.mbox2.driver",
            "CFBundleName": "Necromancer Mbox 2", "CFBundlePackageType": "BNDL", "CFBundleVersion": "0.1.0",
            "CFBundleShortVersionString": "0.1.0", "NecromancerPrereleaseVersion": version,
            "LSMinimumSystemVersion": MIN_MACOS, "CFBundleSupportedPlatforms": ["MacOSX"],
            "CFPlugInFactories": {factory: "MboxDriverEntryPoint"},
            "CFPlugInTypes": {"443ABAB8-E7B3-491A-B985-BEB9187030DB": [factory]},
            "AudioServerPlugIn_MachServices": [LABEL], "sandboxSafe": True}
    (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    shutil.copy2(ROOT / "LICENSE", resources / "LICENSE")
    for name in spec["licenses"]:
        shutil.copy2(dep / name, resources / ("libASPL-" + name))
    sign(bundle, args.sign)
    release = BUILD / "release"
    if release.exists():
        shutil.rmtree(release)
    payload = release / "payload"
    (payload / SERVICE).parent.mkdir(parents=True)
    shutil.copy2(binaries / "mbox_service", payload / SERVICE)
    shutil.copytree(bundle, payload / DRIVER)
    (payload / PLIST).parent.mkdir(parents=True)
    program = ["/" + SERVICE, "--serve-capture"]
    if args.location_id is not None:
        program += ["--location-id", str(args.location_id)]
    if args.enable_midi:
        program += ["--enable-midi"]
    launch = {"Label": LABEL, "ProgramArguments": program, "MachServices": {LABEL: True},
              "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 10,
              "ProcessType": "Interactive", "Umask": 0o027,
              "StandardOutPath": "/Library/Logs/Necromancer Audio/mbox2.log",
              "StandardErrorPath": "/Library/Logs/Necromancer Audio/mbox2.err.log"}
    (payload / PLIST).write_bytes(plistlib.dumps(launch))
    files = {}
    for path in sorted(payload.rglob("*")):
        if path.is_file():
            relative = path.relative_to(payload).as_posix()
            mode = 0o755 if relative in (SERVICE, DRIVER + "/Contents/MacOS/NecromancerMbox2") else 0o644
            path.chmod(mode)
            files[relative] = {"sha256": digest(path), "mode": mode}
    manifest = {"schema": 1, "version": version, **env, "dependency": {"libASPL": spec["commit"]},
                "signing": "ad-hoc" if args.sign == "-" else "identity-signed",
                "notarized": False, "midi_enabled": args.enable_midi, "files": files,
                "source_sha256": source_sha256,
                "developer_tools": {name: digest(binaries / name) for _, name in units if name != "mbox_service"}}
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    for name in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, release / name)
    shutil.copytree(ROOT / "docs", release / "docs")
    shutil.copy2(ROOT / "tools/install.py", release / "install.py")
    (release / "tools").mkdir()
    for _, name in units:
        if name != "mbox_service":
            shutil.copy2(binaries / name, release / "tools" / name)
    if source_sha256 != source_fingerprint():
        raise RuntimeError("Source changed during build; rebuild a stable checkout before packaging.")
    print(json.dumps({"built": True, "version": version, "release": str(release), **env}, indent=2))
    return dep, library


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--sign", default="-", help="explicit code-signing identity; default is local ad-hoc signing")
    parser.add_argument("--enable-midi", action="store_true", help="opt in to experimental USB MIDI transport")
    parser.add_argument("--location-id", type=lambda s: int(s, 0), help="optional USB registry location pin")
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 32 or (args.location_id is not None and not 0 <= args.location_id <= 0xffffffff):
        parser.error("jobs must be 1–32 and location ID must be a uint32")
    return args


if __name__ == "__main__":
    build(parse_args())
