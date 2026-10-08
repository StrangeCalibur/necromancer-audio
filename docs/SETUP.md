# Native setup candidate

The native setup app is preparation for an audio-only public beta. It is not yet a qualified beta release. It requires Apple silicon and has an API deployment floor of macOS 26.4; actual supported macOS versions will be set from runtime acceptance results.

## User workflow

Open the setup DMG, copy **Necromancer Audio Setup** into Applications, then open it. The app checks its embedded package and the existing installation without opening USB or changing system services.

**Install / Update**, **Uninstall** and **Recover** describe separate explicit operations and request normal macOS administrator authentication. Save audio work and close audio clients first: these operations restart CoreAudio. Installation starts the USB service; recovery can restore and start a previous managed service. No firmware update or system-security change is performed.

The default package supports original Mbox 2 firmware 1.43, stereo analog audio at 48 kHz. MIDI is disabled. The app refuses to overwrite an unmanaged prototype, changed files, unknown driver contents or unsafe filesystem paths. It preserves unrelated audio plug-ins, service logs and verified recovery copies. It uses the same schema-1 receipt and journal format as the Python developer installer.

**Copy Diagnostics** copies version and bounded installation-check results. It does not collect recordings, crash reports, USB serial numbers or complete system logs. Successful installation is separate from listening/input acceptance.

## Maintainer build

The setup app's icon is generated with Apple's `sips` and `iconutil` tools from `assets/AppIcon.png`. The artwork participates in the source fingerprint and is included in the curated source archive; changing it requires fresh verification, signing and notarization. See `assets/README.md` for artwork provenance.

Run the offline suite, then recreate the intended signed payload because the suite builds an ad-hoc payload:

```sh
python3 tools/test.py --offline
python3 tools/build.py --offline --sign 'Developer ID Application: YOUR IDENTITY'
python3 tools/setup.py --sign 'Developer ID Application: YOUR IDENTITY'
```

The app, privileged helper, USB service and HAL plug-in are identity signed with hardened runtime and timestamping. The setup DMG and JSON report are written to `dist/` and explicitly named **setup-candidate**. Signing alone does not establish notarization, clean-Mac Gatekeeper acceptance or hardware qualification.

For CI/local development, omit both signing arguments to make an ad-hoc setup candidate. The shipping native helper rejects live mutations from an ad-hoc package. Its test counterpart is separately compiled with `SETUP_TEST` and requires a temporary root; mock actions never invoke launchd or CoreAudio. Test options are not compiled into the shipping helper.

## Notarization

Use an Apple Developer Program account with a saved `notarytool` Keychain profile. Create that profile interactively with `xcrun notarytool store-credentials` outside source control; never paste account passwords into issue reports or commits. Then explicitly provide the profile name:

```sh
python3 tools/setup.py --sign 'Developer ID Application: YOUR IDENTITY' --notarize-profile 'YOUR_PROFILE'
```

This opt-in operation uploads the signed app and its final DMG to Apple's notary service, requires Accepted results, and staples/validates each ticket. It does not publish to GitHub or install the driver. Verify the final download through Gatekeeper on a clean Mac. Apple documents this workflow at https://developer.apple.com/developer-id/.

## Acceptance before beta promotion

Use a second Apple-silicon Mac with no previous Necromancer installation for clean-install acceptance. Its macOS version must be at least 26.4; record the exact version because runtime compatibility below the development system remains unqualified. First verify the downloaded app opens normally, then connect the original firmware-1.43 Mbox 2 for playback/input and reconnect tests. Save audio work before installation or removal. This does not replace managed-update and recovery testing.

Record candidate version, source fingerprint, artifact hash and installed-file hashes. Establish:

- Clean install, managed update, removal, recovery and preserved unrelated plug-ins on a real Mac.
- Playback listening and independent physical input checks on both analog inputs.
- USB reconnect, service restart, sleep/wake and reboot, with the device present and absent where applicable.
- Representative sustained playback/recording load, dropout counters and measured round-trip latency.
- An honest macOS/USB compatibility matrix, ideally with a second Mac and a second original Mbox 2.
- Notarized download and normal installation without Python, Xcode or Terminal.

Retain raw recordings, machine identities and complete logs privately. Publish redacted results in the qualification record. The working historical prototype is not automatically adopted or deleted; migration requires a separately prepared and verified recovery procedure.
