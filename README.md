# Necromancer Audio — Mbox 2

Experimental native macOS audio support for the original Digidesign/Avid Mbox 2 USB interface.

**Status: private local preparation, `0.1.0-alpha.1`. Hardware qualification and publication are on hold following a system panic. This candidate has not been installed or tested on hardware.**

An earlier prototype produced audible CoreAudio playback and recorded a guitar through DI input 1. This repository prepares that work for a reproducible build and a carefully qualified alpha. Source tests, a successful build and historical listening results are separate forms of evidence; none clears the current hardware or release gates.

## Scope

| Item | Current scope |
| --- | --- |
| Device | Original USB Mbox 2, vendor `0x0dba`, product `0x3000` |
| Firmware | Existing runtime firmware 1.43 (`0x0143`) |
| Mac | Apple silicon, macOS 26.4 or newer |
| Development tools | Apple command-line tools with a macOS 26.4 or newer SDK; Python 3.10+ |
| Audio | Two input and two output channels, 48 kHz hardware rate, 24-bit USB samples |
| CoreAudio | Stereo Float32 input/output; application rate conversion belongs to CoreAudio |
| MIDI | Experimental opt-in transport; physical DIN input/output remains unqualified |

Mbox 2 Mini, Mbox 2 Micro, Mbox 2 Pro, other firmware versions and Intel Macs are outside this alpha's supported profile. The repository contains no firmware updater or proprietary firmware. It uses a user-space IOUSBHost service and a CoreAudio HAL plug-in; it does not install a kernel extension or change SIP or boot security.

## Build and test locally

From the repository root:

```sh
python3 tools/build.py
python3 tools/test.py --offline
```

The first build downloads the public libASPL source archive pinned in `dependencies.json` and verifies its SHA-256 before extraction. Subsequent builds can use `python3 tools/build.py --offline`. Python tooling uses the standard library; native compilation uses Apple tools.

Build output goes to `build/`. Tests compile and run protocol, CLI, concurrent mapping and installer filesystem contracts without opening USB, starting CoreAudio/MIDI or changing launchd. `tools/test.py` rebuilds the default audio-only payload with local ad-hoc signatures. Tests do not establish device compatibility or installation acceptance.

## Review installation before use

To prepare local source and developer archives after committing the reviewed source and passing tests:

```sh
python3 tools/release.py
```

This checks a clean source tree, matching test fingerprint, payload hashes, signatures and private-material patterns, then writes archives and SHA-256 checksums to `dist/`. It has no upload or publication operation. The developer archive uses local ad-hoc signatures by default and remains subject to the hardware hold.

```sh
python3 tools/install.py plan
```

Planning is read-only. Installation is a separate administrator operation that loads the background service, initializes USB and restarts CoreAudio. The installer preserves an existing legacy/unmanaged installation by refusing to overwrite it. **Do not install the candidate while the hardware qualification hold is active.** See [installation and recovery](docs/INSTALL.md) for the prepared procedure and exact system paths.

## Experimental MIDI

The default payload leaves MIDI disabled. To prepare a MIDI-enabled payload:

```sh
python3 tools/build.py --offline --enable-midi
```

After a future approved installation of that payload, `build/bin/mbox_midi_bridge` can run in the foreground under the logged-in user and expose **Mbox 2 MIDI — Necromancer Audio** to CoreMIDI. The bridge is not installed as a login service by this alpha installer. Its MIDI endpoint is separate from the audio device **Mbox 2 — Necromancer Audio**. Successful USB writes do not prove that either physical DIN socket works.

## What remains before an external alpha

The release gates include investigation of the current launchd panic, live install/update/uninstall/recovery checks, unplug/reconnect and sleep/wake behavior, reboot, long sessions, and another Mac and Mbox unit. Round-trip latency has not been qualified; the current conservative buffers are unsuitable for claiming low-latency software monitoring. Input 2 signal acceptance, phantom power and S/PDIF remain unqualified.

See the [qualification record](docs/QUALIFICATION.md), [architecture](docs/ARCHITECTURE.md), [contribution workflow](CONTRIBUTING.md) and [third-party notices](THIRD_PARTY_NOTICES.md). Downloadable distribution, signing/notarization and publication are separate release steps that have not been performed.

## Licence

Original project code is available under the [MIT licence](LICENSE). libASPL and its retained Apple notices accompany the built HAL bundle. Protocol references were studied for an independent implementation; Linux reference code and proprietary Avid binaries are not included in this repository or its curated payload.

Mbox, Digidesign and Avid names identify compatible hardware. This project is independent of those vendors.
