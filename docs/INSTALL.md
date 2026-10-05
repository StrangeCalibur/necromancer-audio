# Installation, replacement and recovery

**Experimental developer alpha.** The packaged candidate has passed offline tests; live installer/lifecycle acceptance remains unqualified. Review the plan and recovery procedure before choosing to install. These commands describe the workflow, not a claim that live operations were qualified.

## Requirements and payload

Use an Apple-silicon Mac on macOS 26.4+ and Python 3.10+. Building additionally requires Apple command-line tools with a macOS 26.4+ SDK. The current profile selects one original Mbox 2 with existing firmware 1.43. Multiple matching devices require an explicit USB registry location pin; other revisions and variants are rejected.

`python3 tools/build.py` prepares `build/release/manifest.json` and its exact `payload/`. The manifest records hashes, modes, platform, version and signing mode. The installer checks that payload against the fixed set of supported target files and rejects symlinks, unexpected files and unmanaged installations.

The managed system locations are:

| Purpose | Path |
| --- | --- |
| USB transport executable | `/Library/Application Support/Necromancer Audio/Mbox2/mbox_service` |
| CoreAudio HAL bundle | `/Library/Audio/Plug-Ins/HAL/NecromancerMbox2.driver` |
| Launch daemon | `/Library/LaunchDaemons/audio.necromancer.mbox2.transport.plist` |
| Receipt | `/Library/Application Support/Necromancer Audio/Mbox2/install-receipt.json` |
| Retained recovery payloads | `/Library/Application Support/Necromancer Audio/Mbox2/Recovery/` |
| Service logs | `/Library/Logs/Necromancer Audio/mbox2.log` and `mbox2.err.log` |

The daemon label and privileged Mach service are `audio.necromancer.mbox2.transport`.

## Read-only review

From the source repository root:

```sh
python3 tools/build.py
python3 tools/test.py --offline
python3 tools/install.py plan
python3 tools/install.py status
```

The first build fetches the pinned public dependency if it is absent. The test command rebuilds the default audio-only ad-hoc payload; create the intended payload again after testing if using different signing, location or MIDI options.

`plan` validates the source and current managed installation without changing launchd, opening USB or installing files. `status` checks the managed receipt and files. A pre-existing prototype without this receipt is intentionally reported as unmanaged; its files are preserved.

For an extracted developer archive, change into its directory and run `python3 install.py plan`, then `sudo python3 install.py install --allow-ad-hoc` after reviewing the plan. That script defaults to the accompanying manifest and payload. From a local build, the equivalent plan is:

```sh
python3 build/release/install.py plan
```

## Fresh developer installation

Save audio work and close active audio clients before applying an install or removal because CoreAudio restarts.

Local builds use ad-hoc signatures by default. The installer requires an explicit acknowledgement for such a developer payload:

```sh
sudo python3 tools/install.py install --allow-ad-hoc
```

Installation requires ordinary administrator authentication. It installs the HAL bundle and native transport, starts the launch daemon and restarts CoreAudio. Starting the service captures the selected USB device, initializes it and begins continuous duplex streaming. Stopping it resets/rematches the device; this can turn off its LEDs. No firmware write, kernel extension or security-setting change is part of installation.

The CoreAudio device is **Mbox 2 — Necromancer Audio**. The hardware rate is 48 kHz. Use a low listening level for initial acceptance, and distinguish audible output from a successful API call. The installer result reports hardware acceptance as unverified.

An explicitly identity-signed build can be prepared with:

```sh
python3 tools/build.py --offline --sign 'Developer ID Application: YOUR SIGNING IDENTITY'
```

Signing alone does not establish notarization or release readiness. A downloadable installer/container and its notarization remain separate distribution work. No signing credentials are discovered or uploaded by the default build.

## Replacement

Only an intact installation managed by this installer can be replaced:

```sh
python3 tools/install.py plan --replace
sudo python3 tools/install.py install --replace --allow-ad-hoc
```

The installer verifies the current receipt and hashes, retains a verified recovery copy and protected transaction journal, stops the managed daemon, replaces the exact payload, writes the new receipt and starts the replacement. An ordinary transaction failure triggers restoration of the prior payload. An interrupted transaction requires the explicit recovery operation below.

To select a different prepared payload, pass `--source` pointing at its release directory. A location pin is a build option, for example `--location-id 0x12345678`; use a registry value read from `build/bin/mbox_service --list`, not the example value.

## Existing prototype or other unmanaged installation

`--replace` does not adopt or delete legacy files. If the installer reports an unmanaged installation, stop and preserve it. Inspect its existing installer, receipt/manifest, service configuration and recovery copies before preparing a separate migration procedure. Do not remove files merely because their names match this project's targets. Migration of the historical prototype has not been qualified for this alpha.

## Uninstall

For an intact managed installation, after the hardware hold is cleared:

```sh
sudo python3 tools/install.py uninstall
```

Removal stops the managed daemon, retains a recovery copy, removes its exact audio payload and receipt, and restarts CoreAudio. Unrelated HAL plug-ins, logs and retained recovery material are preserved. Tampered or unmanaged installations are rejected instead of being removed blindly.

The alpha installer does not install a MIDI login agent. Stop any manually running `mbox_midi_bridge` process separately. An older prototype's user MIDI agent belongs to that prototype's migration procedure.

## Recovery

Before changing a managed payload, the installer writes a protected, flushed `pending-transaction.json` in its state directory. A pending journal blocks a new transaction. Once the hardware hold is cleared, recovery from the source repository is:

```sh
sudo python3 tools/install.py recover
```

From a prepared release directory, use:

```sh
sudo python3 install.py recover
```

Recovery validates the journal, recorded manifests, backup hashes and known installed files before changing them. It restores the previous managed payload and its recorded loaded-service state; an interrupted first installation returns to the previous absence of a managed payload. Recovery restarts CoreAudio and can start the prior USB service, so it is a system/hardware operation subject to the same hold as installation. It does not adopt a legacy installation or select arbitrary historical recovery copies.

Do not manually delete the pending journal or edit it to bypass validation. Filesystem tests emulate interrupted operations and exercise this command in temporary roots. Real reboot/power-loss recovery and live service acceptance remain unqualified.

If only an incomplete journal `.next` file remains, `recover` first verifies the intact previous installation (or absence), then clears that orphan without changing the running service or restarting CoreAudio. Unknown extra driver files, directories, links and special file types block removal/recovery for review.

If recovery fails, preserve the printed recovery directory, source payload, receipt and diagnostic output. Do not repeatedly overwrite the installation or substitute a different historical backup without first identifying its version and known defects.

## Experimental MIDI workflow

MIDI is disabled in the default daemon payload. To prepare an opt-in build:

```sh
python3 tools/build.py --offline --enable-midi
python3 tools/install.py plan --replace
```

After that payload is installed under an approved hardware test, start the user bridge in the foreground:

```sh
build/bin/mbox_midi_bridge
```

The endpoint name is **Mbox 2 MIDI — Necromancer Audio**. Quit the foreground bridge to remove its endpoint. Physical testing must use a verified return path or MIDI instrument; completed native USB output transfers alone do not qualify the DIN sockets.
