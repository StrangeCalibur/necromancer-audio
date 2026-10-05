# Third-party notices and protocol provenance

Original Necromancer Audio code is licensed under the repository's [MIT licence](LICENSE).

## libASPL

The CoreAudio HAL adapter links libASPL, obtained from its [upstream repository](https://github.com/gavv/libASPL) at commit `633e0f70203edd87d320fc5a3cae901e1363aac5`.

The archive and SHA-256 are recorded in `dependencies.json`; the build verifies the archive before extracting source. The pinned archive SHA-256 is:

```text
8583fb549419eab14b5c636ee4eb1f0b1df74c534eaf2f990d8bb0fb5de6e01b
```

libASPL uses the MIT licence and retains Apple notices for incorporated source. The build copies these upstream files into the HAL bundle's `Contents/Resources` without replacing their terms:

| Upstream file | Bundle resource |
| --- | --- |
| `LICENSE` | `libASPL-LICENSE` |
| `LICENSE.apple2012` | `libASPL-LICENSE.apple2012` |
| `LICENSE.apple2020` | `libASPL-LICENSE.apple2020` |

The project `LICENSE` is also included there. Preserve all these files when redistributing a built bundle.

## Linux protocol research

Device identity, interface layout, startup behavior, PCM formatting, feedback and MIDIMAN framing were studied in the upstream Linux USB audio implementation. The retained research reference is Linux commit `e767a4ea70a3992c37ed604157d32f0dfbf9b1e3`:

- [Mbox composite profile in `sound/usb/quirks-table.h`](https://github.com/torvalds/linux/blob/e767a4ea70a3992c37ed604157d32f0dfbf9b1e3/sound/usb/quirks-table.h).
- [Device-specific startup in `sound/usb/quirks.c`](https://github.com/torvalds/linux/blob/e767a4ea70a3992c37ed604157d32f0dfbf9b1e3/sound/usb/quirks.c).
- [Feedback and packet scheduling in `sound/usb/endpoint.c`](https://github.com/torvalds/linux/blob/e767a4ea70a3992c37ed604157d32f0dfbf9b1e3/sound/usb/endpoint.c).
- [MIDIMAN framing in `sound/usb/midi.c`](https://github.com/torvalds/linux/blob/e767a4ea70a3992c37ed604157d32f0dfbf9b1e3/sound/usb/midi.c).

Those sources are protocol research references. Their implementation is not copied into the MIT project files, linked into the binaries or included in the curated source payload. Changes that incorporate third-party implementation must review its licence and update these notices before distribution.

## Apple frameworks and tools

The build uses the host's Apple SDK and system frameworks, including Foundation, CoreAudio, CoreMIDI, IOKit and IOUSBHost. They remain system dependencies; SDK/framework binaries are not bundled by this project. The shared transaction-buffer method is [documented by Apple as available from macOS 26.4](https://developer.apple.com/documentation/iousbhost/iousbhostobject/data(withcapacity:options:)); SDK 27.0+ is required to compile this alpha because older tested SDKs omit its option declarations. The [GitHub runner-image catalog](https://github.com/actions/runner-images) identifies the arm64 Xcode 27 preview runner used by CI.

## Proprietary material

No Avid/Digidesign firmware, legacy driver binaries or firmware updater is distributed. Runtime firmware 1.43 is a prerequisite of the current device profile. Firmware redistribution permission has not been established, so proprietary images remain outside the curated repository and archives.
