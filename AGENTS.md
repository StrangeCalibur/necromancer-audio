# Agent instructions

This repository is a private local alpha preparation. Preserve existing work and keep all preparation private. Do not create remotes, push, upload, notarize or publish without explicit authorization.

Read `README.md`, `docs/QUALIFICATION.md` and the relevant implementation before changes. Keep source/build proof, offline test proof, live service behavior and human/device acceptance separate.

Hardware qualification is on hold following a launchd assertion panic whose responsible job and cause remain unknown. Source edits, builds and offline tests are permitted. Do not install this candidate, start streaming, manipulate launchd/CoreAudio or flash firmware while that hold remains active. The existing prototype is separate from this uninstalled candidate; preserve its payload and recovery material.

Use `python3 tools/build.py` and `python3 tools/test.py --offline` with Python 3.10+, Apple silicon and a macOS 26.4+ SDK. These tools must not gain hardware access or system mutation as hidden side effects. Keep third-party source pinned and preserve all licence notices.

Do not reintroduce mixed native/libusb ownership or quarantine-excluded experimental helpers. Keep audio callbacks free of project allocation, XPC, USB controls and mapping cleanup. Asynchronous USB data and transaction storage must survive completion/abort; optimized IOUSBHost buffers must not be resized.

Keep private machine paths, identifiers, logs, recordings, credentials and proprietary firmware out of curated source/documentation/archives. Update release and qualification records to reflect exactly what has been verified, including failures and unresolved gates.
