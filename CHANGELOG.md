# Changelog

## 0.1.0-alpha.2 — unreleased beta preparation

- Added a native macOS setup app with read-only status/plan, administrator authentication, managed installation/update, uninstall, interrupted-operation recovery and copyable diagnostics. Users need no Python or development tools.
- Added a compiled Swift installer with fixed targets, signature and checksum validation, protected backups/journal and refusal to adopt unmanaged prototypes. Test-only roots and failure injection are absent from the shipping helper.
- Added native setup filesystem tests and a signed DMG preparation/notarization path. No notarization credentials are discovered, embedded or uploaded by default.
- Kept the candidate audio-only and retained the public alpha's hardware qualification boundaries. This version does not establish public-beta or stable readiness.

## 0.1.0-alpha.1 — 2026-10-05

First open source developer alpha for the original Digidesign/Avid Mbox 2 USB on Apple silicon and macOS 26.4+.

- Added a standalone IOUSBHost transport and CoreAudio HAL plug-in for firmware 1.43, stereo input/output and fixed 48 kHz.
- Refuse streaming before IPC/USB setup when the runtime lacks the shared-buffer allocator.
- Added strict descriptor validation, portable single-device selection and optional USB location pinning.
- Added bounded shared-memory audio IPC and concurrent mapping retirement.
- Kept experimental MIDI opt-in; physical DIN acceptance remains unqualified.
- Added a hash-pinned libASPL build, explicit SDK/deployment requirements, local signing and an exact payload manifest.
- Added managed install/update/removal, refusal to overwrite unmanaged installations, retained recovery copies and a durable interrupted-transaction recovery journal.
- Required SDK 27.0+ after CI exposed missing shared-buffer declarations in SDK 26.6; runtime deployment floor remains 26.4 and older-runtime acceptance is unqualified.
- Added sanitizer-backed native contracts, installer/archive tests, macOS CI, contribution guidance and curated source/developer archives with checksums.

The unrelated system-crash hold has been cleared. Historical prototype playback and DI-1 guitar recording were verified; the packaged candidate's live installation, lifecycle, sustained-load, portability and latency acceptance remain open. Developer binaries are ad-hoc signed and unnotarized. No firmware or proprietary driver is included.
