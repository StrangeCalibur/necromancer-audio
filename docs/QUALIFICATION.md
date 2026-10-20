# Qualification record

**2026-10-20: owner-approved public audio beta `0.1.0-beta.1`.** The owner confirmed that the kernel crashes were unrelated to this driver and resolved. They are not treated as a current release blocker.

Source/build proof, offline tests, prototype transport evidence and packaged-candidate hardware acceptance are separate. Publication enables development and wider testing; it does not certify the candidate for production audio.

## Historical prototype evidence

These checks preceded the standalone packaged candidate:

| Check | Evidence and limit |
| --- | --- |
| Listening | An operator heard short tones and ordinary CoreAudio playback through the Mbox. |
| Physical input | Guitar DI input 1 was recorded and replayed. Input 2 signal acceptance was not established. |
| Duplex transport | A simultaneous 60-second silent input/output test completed with matching frames and no reported application discontinuities or USB packet errors during that bounded test. |
| MIDI software path | A bounded software loopback passed; this did not test the Mbox sockets. |
| MIDI native output | 76 messages produced 704 expected MIDIMAN USB bytes with successful native completions and no reported drops/errors. No physical DIN return signal was observed. |
| Extended stability | An earlier service missed an isochronous deadline during a longer run and recovered. Long-run stability remains unqualified. |
| Attended use, 2026-10-04 | The project record reports the original Mbox 2 stayed connected, visible and working without observed instability throughout the day. This is prototype evidence, not a controlled sustained-load or packaged-candidate test. |

These observations concern one setup and do not establish compatibility with another Mac, USB topology, unit or firmware revision. Historical mixed native/libusb experiments remain excluded; the candidate uses one IOUSBHost owner.

## Source and offline proof

The release is built from a fresh checkout without private maintainer onboarding or credentials. The dependency archive is pinned and SHA-256 verified. The current local toolchain is Apple clang 21.0.0 with macOS SDK 27.0, targeting macOS 26.4 and arm64.

Seven native contract groups exercise PCM/feedback, CLI/device selection, MIDI codec, concurrent mapping reclamation, actual HAL callbacks/timestamps/input ring, mock async MIDI transport and USB descriptor-profile rejection. Native tests run with AddressSanitizer and UndefinedBehaviorSanitizer, including 10,000 mapping reconnects. The 49 Python tests cover installer filesystem transactions, the compiled native setup helper, archive/source curation and icon fingerprinting. CLI guards reject unsupported actions before device access.

`python3 tools/test.py --offline` writes `build/test-results.json`; its source fingerprint must match the prepared manifest before packaging. Tests use temporary filesystem roots and mocked service operations. They neither open USB nor change system services. The developer archive includes this report; `SHA256SUMS` identifies the released archives. GitHub CI runs the build/tests and archive preparation on the arm64 Xcode 27 preview image. SDK 26.6 failed to compile because it lacks the shared transaction-buffer declarations; the build now requires SDK 27.0+. The runtime deployment floor remains 26.4, matching Apple's API availability declaration, but runtime compatibility on macOS 26.4–26.x has not been tested. A selector-availability guard refuses streaming before IPC/USB setup when the runtime lacks the shared-buffer allocator.

## Acceptance boundaries

| Area | Current status |
| --- | --- |
| System-crash hold | Cleared by owner; unrelated crashes resolved |
| Source/build | Fresh-checkout build, pinned dependency and offline contracts required before promotion |
| Managed installation | Owner reports installation worked on additional laptops; update/removal/recovery still have offline proof only |
| Existing prototype migration | No automatic adoption; unmanaged files preserved; migration unqualified |
| Candidate playback/input | Owner confirms playback and recording on additional laptops with the preceding notarized DMG; input-by-input coverage not specified |
| USB lifecycle | Candidate unplug/reconnect, ports and service restart unqualified |
| Power lifecycle | Candidate sleep/wake and reboot unqualified |
| Sustained load | Representative desktop/DAW playback/recording duration unqualified |
| Portability | Additional laptops owner-tested; exact models/OS versions/topology unspecified; second original Mbox 2 unqualified |
| Latency | Round-trip latency unmeasured; conservative buffering; no low-latency claim |
| Input 2 / phantom power / S/PDIF | Unqualified |
| Physical MIDI DIN input/output | Unqualified; opt-in experimental software transport only |
| Distribution | MIT source; Developer ID signed and Apple-notarized setup DMG; optional developer archive is ad-hoc signed and unnotarized |

Hardware-rate switching beyond 48 kHz and other Mbox variants/firmware revisions are outside this beta. Production readiness requires the live acceptance work above; these limitations remain visible in the public beta.

## Attended test records

On 2026-10-20, the owner confirmed that the new DMG worked on other laptops, including installation, playback and recording, and approved public beta publication. This refers to the `0.1.0-alpha.2` icon candidate built from `86ec8268691182d096da3846dd8123d07b45cc59`, DMG SHA-256 `cf1376e0aaa4f091e91394988456d52e793d90412b785a12dd8ec4f782c5c434`. This is owner-reported acceptance, not independently instrumented testing. Laptop models, exact macOS versions, input-by-input coverage, durations and counters were not provided. Earlier owner reporting also described several days of stable use on the original installation.

`0.1.0-beta.1` changes version metadata, setup/release wording and prerelease packaging support; it introduces no audio transport, HAL or installer-transaction behavior changes relative to that candidate. It is freshly built, signed, notarized and checked offline. The final beta's new artifact hash does not imply that it received another physical test. Release notes and `SHA256SUMS` identify its bytes.

Compiled-helper filesystem tests cover planning, managed transactions, failed-update restoration, interruption recovery, unknown-file refusal and preservation of unrelated plug-ins. Those use temporary roots and mock service actions. Detailed lifecycle, managed update/removal/recovery, measured latency, second-device coverage and exact OS compatibility remain beta follow-up work. The owner approved publication with those limits visible; they have not been marked passed.

Record candidate version/hash, model, firmware, macOS/SDK, USB topology, duration, expected behavior, measured counters and operator listening/input acceptance. Keep serials, boot identifiers, recordings and complete machine logs private; publish only redacted facts needed to support the result.

Start with registry-only enumeration and the read-only install plan, preserve recovery material, and test one bounded operation at a time. Stop on a new panic or unexplained service failure. Do not change firmware, SIP or boot security to bypass a qualification failure.
