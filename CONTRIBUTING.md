# Contributing

Issues and pull requests are welcome. This alpha targets the original Mbox 2 USB on Apple silicon, firmware 1.43 and fixed 48 kHz audio. Read the [qualification record](docs/QUALIFICATION.md) before making compatibility claims.

## Build and tests

Use Python 3.10+, Apple silicon and Apple command-line tools with a macOS 26.4+ SDK:

```sh
python3 tools/build.py
python3 tools/test.py --offline
```

The first build fetches the pinned public dependency. Subsequent builds can use `--offline`. Tests rebuild the default ad-hoc signed audio-only payload, run seven native contract groups with address/undefined-behavior sanitizers, and test installer/release filesystem contracts. They neither access hardware nor change system services. Rebuild after testing if using different signing, location or MIDI options.

Add meaningful failure/lifetime tests for changes to protocol parsing, async USB buffers, mapping publication, installer recovery or IPC authorization. Keep patches focused and explain the behavior change and verification in the pull request.

## Engineering constraints

- Keep a single IOUSBHost owner; never mix native initialization with libusb capture.
- Reject unsupported descriptor/firmware profiles and ambiguous device selection.
- Retain asynchronous USB buffers until callbacks complete; retire shared mappings only after readers leave.
- Avoid allocation, blocking locks and file I/O in CoreAudio real-time callbacks.
- Keep service IPC narrow and restrict privileged operations to intended principals.
- Preserve unmanaged installations and verified rollback material.
- Pin dependencies by commit/hash and retain their licences.

## Hardware reports

Report version/commit, exact Mbox model and firmware, macOS, USB topology, duration, expected/actual behavior, transport counters and what you heard or recorded. Use the issue template. Redact personal paths, serials, boot identifiers and credentials; avoid posting raw machine logs or recordings with private material. Do not attach proprietary firmware or vendor driver packages.

Install/update/uninstall and service startup are explicit operations described in [INSTALL.md](docs/INSTALL.md). A build, USB completion or visible device is not a listening or physical-input result. Record prototype and packaged-candidate evidence separately.

## Licensing

Submit original code that you can contribute under the project's MIT licence. Identify any third-party code and its licence before inclusion, and update THIRD_PARTY_NOTICES.md when appropriate. Protocol facts and a reference citation do not authorize copying an implementation under an incompatible licence.
