# Necromancer Audio — Mbox 2

Experimental open source macOS support for the original Digidesign/Avid **Mbox 2 USB** interface. MIT licensed, with a user-space USB transport and a CoreAudio HAL plug-in.

**`0.1.0-alpha.1` is a developer alpha for Apple silicon and macOS 26.4+.** Historical prototype playback and DI-1 guitar recording were heard and verified on one setup. The packaged candidate has passed offline tests; its live installer and broader hardware compatibility remain unqualified. See [qualification](docs/QUALIFICATION.md) before installing.

## Supported profile

| Item | This alpha |
| --- | --- |
| Interface | Original Mbox 2 USB, VID `0x0dba`, PID `0x3000` |
| Existing firmware | **1.43**; no firmware updater is included |
| Mac | Apple silicon, arm64 |
| System | macOS 26.4 or newer |
| Build tools | Apple command-line tools with a macOS 26.4+ SDK; Python 3.10+ |
| Audio | Fixed 48 kHz; stereo input/output; 24-bit USB PCM and Float32 CoreAudio |
| MIDI | Opt-in experimental transport; physical DIN ports unqualified |

Mbox 2 Mini, Micro and Pro, Intel Macs, other firmware revisions and other sample rates are outside this alpha. Installation requires administrator access. No kernel extension, SIP change or boot-security change is required. The conservative buffers are not qualified for low-latency software monitoring.

## Get the alpha

Download the source or the **unnotarized, ad-hoc signed arm64 developer archive** from [GitHub Releases](https://github.com/StrangeCalibur/necromancer-audio/releases). `SHA256SUMS` accompanies the archives. This is an expert/developer distribution, not a notarized one-click installer.

For a source build:

```sh
git clone https://github.com/StrangeCalibur/necromancer-audio.git
cd necromancer-audio
python3 tools/build.py
python3 tools/test.py --offline
```

The first build downloads a public libASPL source archive pinned by commit and SHA-256 in [dependencies.json](dependencies.json). Python tooling uses only the standard library. Output goes to `build/`. Tests rebuild the default audio-only payload and exercise native contracts under AddressSanitizer and UndefinedBehaviorSanitizer, installer filesystem transactions and CLI guards. They do not open USB, start services or establish hardware acceptance.

## Install and select the device

Read [installation and recovery](docs/INSTALL.md), including the limitations for existing unmanaged/prototype installations. Save audio work and close audio clients before an installation because CoreAudio restarts.

From a source build, review the read-only plan first:

```sh
python3 tools/install.py plan
```

For a fresh installation after reviewing that plan:

```sh
sudo python3 tools/install.py install --allow-ad-hoc
```

For a downloaded developer archive, run its accompanying `install.py` instead. Installation starts the USB transport and exposes **Mbox 2 — Necromancer Audio** in macOS audio settings. Start at a low listening level; audible playback must be checked separately from successful service startup. The installer refuses to overwrite an unmanaged installation and retains recovery material for managed updates.

## Optional MIDI

Audio-only is the default. To build an audio service with experimental MIDI enabled:

```sh
python3 tools/build.py --offline --enable-midi
```

After explicitly installing that payload, `build/bin/mbox_midi_bridge` runs in the foreground under the logged-in user and exposes **Mbox 2 MIDI — Necromancer Audio** to CoreMIDI. It is not installed as a login service. Successful USB writes and software loopback do not establish physical DIN input/output compatibility.

## Development and release preparation

See [contributing](CONTRIBUTING.md), [architecture](docs/ARCHITECTURE.md), and [qualification](docs/QUALIFICATION.md). Report reproducible problems through [GitHub Issues](https://github.com/StrangeCalibur/necromancer-audio/issues). Include model, firmware, macOS, version and USB topology; redact serial numbers and personal data.

On a clean committed checkout with a passing matching test report:

```sh
python3 tools/release.py
```

This verifies the source allowlist, privacy patterns, payload hashes and signatures, then writes deterministic curated archives and checksums to `dist/`. It performs no upload or publication. [Release procedure](docs/RELEASE.md) describes promotion and verification.

## Licensing and provenance

Independent project code is MIT licensed. libASPL and its Apple-derived portions retain their original notices. Linux Mbox 2 support was studied as protocol reference; proprietary drivers and firmware are not distributed. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). This project is independent of Avid and Digidesign.
