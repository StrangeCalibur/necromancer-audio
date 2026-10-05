# Necromancer Audio contributor instructions

This repository implements experimental support for the original Mbox 2 USB. Read README.md, docs/ARCHITECTURE.md and docs/QUALIFICATION.md before substantial changes. Preserve existing work and report exactly what was verified.

## Build and verification

Use Apple silicon, Python 3.10+ and an Apple macOS 26.4+ SDK. Run `python3 tools/build.py` and `python3 tools/test.py --offline`. Builds/tests must not gain USB access or system mutations as hidden side effects. Keep dependencies pinned and all licence notices intact.

## Implementation constraints

- Match the exact original Mbox 2 firmware-1.43 descriptor profile. Reject unsupported profiles and ambiguous device selection.
- Use one IOUSBHost owner. Do not introduce a mixed native/libusb ownership fallback.
- Preserve asynchronous transaction buffers until completion and avoid allocation, locks and file I/O in real-time audio callbacks.
- Keep IPC bounded and restricted to the intended service/CoreAudio principals.
- Preserve unmanaged installations; retain verified recovery copies and durable transaction journals for managed replacements.
- Keep MIDI opt-in and distinguish software/USB tests from physical DIN acceptance.

## Hardware and release boundaries

Installation, streaming, firmware writes and service changes are separate explicit operations. Offline tests do not qualify them. The owner cleared the unrelated system-crash hold on 2026-10-05 and requested the first open source alpha; broader hardware acceptance remains open as documented in docs/QUALIFICATION.md.

Keep credentials, proprietary firmware, personal recordings, raw crash reports and machine identifiers out of Git and archives. Local ignored `private/` evidence and optional maintainer coordination files must remain local. Update qualification and release records to reflect measured outcomes without promoting prototype evidence to a new candidate claim.
