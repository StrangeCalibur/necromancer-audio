# Changelog

## 0.1.0-alpha.1 — private preparation

This candidate is prepared locally and has not been installed on hardware or cleared for publication.

- Extracted the native Mbox 2 audio transport and CoreAudio HAL into a standalone source tree.
- Restricted support to the original `0x0dba:0x3000` runtime profile with existing firmware 1.43, arm64 macOS 26.4+ and 48 kHz stereo duplex audio.
- Replaced the prototype's fixed USB port selection with exact-profile discovery and optional explicit location pinning; ambiguous matches are rejected.
- Replaced the HAL's eight-mapping lifetime cap with reclamation after concurrent readers leave.
- Added a hash-pinned libASPL build, explicit SDK/deployment requirements, local signing and exact payload manifest.
- Prepared managed installation/replacement/removal with preservation of legacy installations, recovery material, a durable pending-transaction journal, an explicit recovery command and offline filesystem tests.
- Kept MIDI opt-in and its user bridge foreground-only; physical DIN qualification remains open.
- Added curated architecture, installation, provenance and qualification documentation without private recordings, raw machine logs or proprietary firmware.

Hardware qualification is on hold following the latest launchd assertion panic. Historical prototype playback/input results are retained as evidence with their limits; they do not qualify this candidate.
