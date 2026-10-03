# Qualification and release gates

**As of 2026-10-03: private local alpha preparation. Hardware work is on hold after a system panic. This new `0.1.0-alpha.1` candidate has not been installed or qualified on hardware.**

Keep source/build proof, offline contract tests, live transport evidence and human listening/input acceptance separate. Historical prototype results do not prove a modified candidate is safe or ready to distribute.

## Historical prototype evidence

These checks preceded the standalone candidate:

| Check | Evidence and limit |
| --- | --- |
| Listening | An operator heard short tones and ordinary CoreAudio playback through the Mbox. |
| Physical input | Guitar DI input 1 was recorded and replayed. Input 2 signal acceptance was not established. |
| Duplex transport | A simultaneous 60-second silent input/output test completed with matching frames and no reported application discontinuities or USB packet errors during that bounded test. |
| MIDI software path | A bounded software loopback passed; this did not test the Mbox sockets. |
| MIDI native output | 76 MIDI messages produced 704 expected MIDIMAN USB bytes with successful native completions and no reported drops/errors during the test. No physical DIN return signal was observed. |
| Extended stability | An earlier service missed an isochronous deadline during a longer run and recovered. Long-run stability is not qualified. |

These results support continued development, not a compatibility claim for another Mac, USB topology, Mbox unit or firmware revision.

## System crash gates

Two distinct crashes are relevant to release qualification:

- A historical IOUSBHost kernel panic occurred while an earlier experiment mixed native initialization and libusb ownership. That experimental path is quarantined and excluded from this candidate. It must not be restored as a fallback.
- At 19:45:44 UTC on 2026-10-03, the running system panicked after `launchd` exited on an assertion. Inspection of the matching local binary located the assertion in job-monitor handling after a Mach `KERN_NO_SPACE` result. The responsible job and causal relationship to the background Mbox prototype remain unknown. The report does not establish that USB or this candidate caused it.

The device was disconnected following the latest crash. Hardware streaming, service changes and candidate installation remain on hold while the incident is investigated. A release must document the investigation outcome and evidence supporting any resumed hardware test. Raw panic reports, machine identifiers, local logs and private recordings are excluded from curated release documents and archives.

## Candidate source and offline checks

The candidate adds portable selection across USB locations, optional explicit location pinning, mapping reclamation without the old lifetime cap, a pinned-dependency build and an exact-manifest installer. Seven native contract groups passed with address/undefined-behavior sanitizers, including the actual USB profile validator, HAL callbacks and 10,000 concurrent mapping reconnects. Eighteen filesystem tests passed for installation, replacement, rollback, interrupted transactions, orphan journals, uninstall, symlink/path rejection and restrictive umasks. These are offline results; no candidate installation or hardware test was performed.

Use `python3 tools/test.py --offline` after the dependency archive has been fetched. The tool writes `build/test-results.json` and runs native contracts under AddressSanitizer/UndefinedBehaviorSanitizer plus installer filesystem tests and CLI rejection guards. It opens no USB device and performs no system installation or launchd action. Record the candidate commit/archive hash, SDK/compiler, test report and complete result when accepting an offline build. Do not substitute a test count or compilation success for hardware acceptance.

## Gates before an external audio alpha

| Gate | Required acceptance | Current status |
| --- | --- | --- |
| Latest panic | Investigate launchd failure; establish a bounded, recoverable path for resumed testing | Open; hardware hold |
| Clean source build | Fresh-directory build, pinned archive verification, complete tests, curated source scan | Work in progress; no hardware proof |
| Managed installation | Fresh install, replacement, removal, injected failure and interrupted-transaction recovery | 18 offline filesystem tests passed; live operations unqualified |
| Existing prototype migration | Preserve known working payload and verified rollback before any replacement | Not performed |
| Playback and input | New candidate heard at a quiet level; DI input 1 recorded/replayed with valid counters | Historical prototype only |
| USB lifecycle | Unplug/reconnect idle and during streaming, different ports, service restart | Unqualified on candidate |
| Power lifecycle | Sleep/wake and reboot, including service startup with device absent/present | Unqualified |
| Long session | Defined-duration playback/recording under representative desktop/DAW load | Unqualified |
| Portability | Another Mac and another original Mbox 2 on firmware 1.43 | Unqualified |
| Latency | Measured round-trip latency and stable useful buffer settings | Unqualified; conservative buffering |
| Distribution | Curated archive review, licence notices, appropriate signatures/notarization and explicit publication approval | Private local preparation only |

Physical MIDI input/output can remain an explicit experimental limitation of an audio-focused alpha, but it must not be advertised as qualified. Input 2, phantom power and S/PDIF must remain unqualified until attended tests establish their behavior. Hardware-rate switching beyond 48 kHz is outside this alpha.

## Future attended test record

For each hardware session, record the candidate version/hash, hardware model, firmware, macOS/SDK, USB topology, test duration, expected behavior, measured counters and operator acceptance. Keep device serials, boot UUIDs, recordings and complete machine logs in private evidence. Export only the minimal redacted facts needed to support a compatibility claim.

Start from registry-only enumeration and inspect the prepared install plan before a live change. Resume one bounded hardware step at a time once the incident hold is cleared, preserve recovery material, and stop on a new panic or unexplained service failure. Do not change firmware, SIP or boot security to bypass a qualification failure.
