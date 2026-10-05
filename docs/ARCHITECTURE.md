# Architecture

The driver consists of a root USB transport, a CoreAudio HAL adapter and an optional logged-in-user MIDI bridge. USB ownership and audio callbacks are separated so native USB calls, XPC, allocation and mapping cleanup stay outside the project audio callbacks.

## Device selection and ownership

`src/mbox_options.h` parses the fixed CLI and matches vendor `0x0dba`, product `0x3000`, runtime firmware `0x0143`. Registry-only `--list` does not open USB. `--inspect` opens a descriptor-reading session without running the initialization/streaming sequence. `--serve-capture` requires root, selects exactly one eligible device and takes exclusive native IOUSBHost ownership. With several eligible devices, an explicit `--location-id` is required.

After descriptor/profile validation, the service polls the runtime-ready response and reconciles device configuration under that same owner. It opens the audio interfaces, selects their streaming alternatives, sets and reads back the 48 kHz capture rate, and opens the required pipes. It never hands an initialized device to libusb or legacy USB interfaces. No firmware flashing operation exists.

| Function | Interface / endpoint |
| --- | --- |
| Stereo playback | Interface 2, alternate 2, OUT `0x03` |
| Playback feedback | Interface 2, alternate 2, IN `0x83` |
| Stereo capture | Interface 4, alternate 2, IN `0x85` |
| Experimental MIDI input | Interface 6, interrupt IN `0x81` |
| Experimental MIDI output | Interface 6, bulk OUT `0x02` |

The unused bulk IN `0x82` is not a MIDI input substitute. The profile is restricted to this original Mbox 2 layout; descriptors alone do not establish support for other variants.

## Audio transport and timing

The USB format is stereo signed 24-bit big-endian, six bytes per sample frame. Full-speed feedback is interpreted as 10.14 samples per USB frame. A validated phase accumulator chooses whole sample frames while respecting packet capacity. At the nominal 48 kHz rate this is about 48 sample frames per millisecond; a 49-frame packet is 294 bytes.

The service uses eight 8 ms transfers per endpoint for a 64 ms queued horizon. Transaction descriptors use IOUSBHost's shared kernel/user transaction storage, which sets the macOS/SDK 26.4 floor. Data buffers and transaction storage stay alive through completion or synchronous abort. Serialized completion queues own the transport state, and abort occurs from outside those queues so callbacks can drain.

The shared audio region contains two tagged 32,768-frame rings, a hardware-derived clock, generation and heartbeat information, online/client state and health counters. Naturally aligned lock-free atomics guard interprocess access. Tags and generations reject missing, overwritten or obsolete samples. Invalid values are clamped or converted to silence; the HAL reads silence while offline.

The HAL presents two Float32 stereo channels at 48 kHz using libASPL. Its zero-timestamp period is 32,768 frames and its conservative safety offset is 4,096 frames (about 85.3 ms at 48 kHz). These are implementation settings, not a measured round-trip latency claim. Low-latency software monitoring remains unqualified.

## IPC and mapping lifetime

The privileged service exposes `audio.necromancer.mbox2.transport`. The fixed audio `connect` operation shares memory only with root or `_coreaudiod`; the IPC surface does not accept arbitrary paths, executable code, USB controls or firmware operations.

The HAL's serial control queue owns XPC and publishes mappings. `mbox_mapping.hpp` uses sequentially consistent reader entry, pointer acquisition, publication and quiescence checks. Audio readers only increment/decrement a lock-free counter and access their selected pointer. Retired mappings are unmapped on the control queue after prior readers leave; reconnect waits for reclamation instead of imposing the prototype's eight-mapping lifetime cap. Offline contract tests exercise repeated publication and concurrent readers. Real service interruption/reconnect behavior still requires hardware qualification.

Heartbeat/online state determines whether the HAL exposes the device as alive. The native service retries the selected device after a failed/disconnected streaming session. This intended lifecycle behavior has not yet been accepted on the new candidate across unplugging, sleep/wake or reboot.

## Optional MIDI

MIDI is disabled by default. An opt-in service owns interface 6 together with the audio interfaces; a separate foreground user bridge publishes CoreMIDI endpoints. Only root and the current console user may use the MIDI IPC operations. This does not grant the user bridge audio shared-memory access.

The independent codec handles channel messages, running status, real-time bytes, system-common messages and streaming SysEx, using MIDIMAN four-byte packets with up to three MIDI bytes and a cable/length control byte. Cable zero is the supported cable.

Transport queues and IPC messages are bounded. USB output uses retained, immutable-length buffers of 4, 8, 12 and 16 bytes; optimized IOUSBHost data objects are never resized while sending. Offline tests cover asynchronous buffer lifetime and abort behavior. Software loopback and USB completion evidence are useful transport checks, while physical DIN input and output remain separate qualification gates.

## Build, install and distribution boundaries

Python standard-library tooling fetches a hash-pinned libASPL archive, compiles arm64 code against the explicit deployment floor, signs locally, and writes an exact release manifest. The default signature is ad-hoc; a supplied identity is an explicit build option. The build does not install, open hardware, discover credentials, notarize or publish.

The audio installer validates its fixed target set, preserves unmanaged installations, requires root for mutations and retains recovery material. Offline filesystem tests substitute mock service actions; passing them does not verify real launchd, CoreAudio or USB transitions. The public alpha distributes unnotarized developer archives. Live device acceptance and broader distribution remain subject to [qualification](QUALIFICATION.md).
