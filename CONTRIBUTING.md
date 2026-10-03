# Contributing

The project is in private local preparation. Keep repository remotes, uploads, publication and notarization outside routine development until explicitly authorized. The current hardware qualification hold permits source work and offline checks; it does not permit installing the candidate, starting USB streaming or changing system services.

## Development baseline

Use Apple silicon, Python 3.10+ and Apple command-line tools with a macOS 26.4+ SDK. Python tooling uses the standard library. Build and test from the repository root:

```sh
python3 tools/build.py
python3 tools/test.py --offline
```

The first build downloads only the dependency recorded in `dependencies.json` and verifies its SHA-256. Keep dependency commits, hashes and required notices together when changing a dependency. Do not vendor unrelated research trees, proprietary firmware or legacy driver binaries into the source tree.

Tests rebuild the default audio-only ad-hoc payload. Rebuild with intended release options after testing. Native contract tests use sanitizers; filesystem installer tests use temporary roots and mock service actions. Add meaningful failure/lifetime tests when changing protocol parsing, asynchronous USB buffers, mapping publication, installer recovery or IPC authorization.

## Implementation constraints

- Preserve exclusive native IOUSBHost ownership. Do not reintroduce a native/libusb handoff or legacy experimental fallback.
- Keep USB calls, XPC, allocation and mapping cleanup outside project audio callbacks.
- Keep async buffers and transaction storage alive until completion or abort; do not resize optimized IOUSBHost buffers.
- Keep device profiles explicit. Do not claim support for another Mbox variant, firmware, architecture or rate based on similar names or descriptors.
- Keep IPC operations fixed, authenticated and bounded. Do not introduce arbitrary paths, command execution or firmware controls.
- Preserve existing installations and recovery material. A migration must identify and verify the actual legacy payload before replacement.

## Evidence and documentation

Describe changes in terms of resulting behavior, relevant tests and remaining acceptance gates. Record offline tests separately from live service behavior, audible playback and physical input. Update `docs/QUALIFICATION.md` when a gate is genuinely verified, keeping historical failures and their resolution visible.

Reports intended for a curated release should include only the minimal reproducible facts: version/hash, platform, firmware, topology category, bounded duration and observed result. Exclude credentials, home paths, identifying UUIDs, raw system logs and recordings. Preserve required copyright/licence notices.

## Installation and hardware tests

Installation, updates, uninstallation and service startup are explicit system/hardware operations. The prepared procedure is in `docs/INSTALL.md`; current qualification status takes precedence over sample commands. No candidate is approved for hardware use or publication while the incident hold remains active.
