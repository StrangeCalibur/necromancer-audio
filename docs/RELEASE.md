# Prerelease procedure

The public audio beta is `0.1.0-beta.1`. It includes a Developer ID signed and notarized native setup DMG, curated source archive, optional ad-hoc signed/unnotarized developer archive and `SHA256SUMS`. Keep owner-reported hardware acceptance and remaining limits explicit in the release notes and QUALIFICATION.md.

## Prepare exact source

1. Review VERSION, the service version, README, changelog, notices and qualification. Keep their scope consistent.
2. Audit tracked files and all reachable Git history for credentials, personal paths/identifiers, recordings, raw logs and proprietary firmware. Private evidence and maintainer coordination stay ignored locally. Keep third-party notices in the source and HAL bundle.
3. Commit the reviewed source. Build a fresh clone with `python3 tools/build.py`, then run `python3 tools/test.py --offline`. No USB access, installation or service change is required.
4. Run `python3 tools/release.py` on that clean checkout. The tool requires matching source/test/payload fingerprints, exact archive allowlists, payload hashes and valid local signatures. It writes deterministic archives, checksums and a local readiness report; it does not publish.
5. Build the Developer ID signed setup payload/app in a local cache after offline tests, notarize the app and DMG separately, staple both tickets and verify Gatekeeper and the mounted embedded package. Preserve submission IDs before waiting. Do not change tested runtime behavior during promotion.
6. Extract and inspect both archives. Verify their SHA-256 values, manifests, source provenance, licences and accompanying test report. The source archive builds without private project credentials. Record exact commit, toolchain, test count and archive hashes in the maintainer release record.

## Promote on GitHub

Create an annotated `v<VERSION>` tag for the verified commit. Prepare a draft prerelease with the reviewed notes, the notarized setup DMG, two archives and SHA256SUMS. Re-read tag, draft and asset identities before promotion. Public visibility and publishing require owner authorization; the owner requested the first open source release on 2026-10-05 and explicitly approved public beta publication on 2026-10-20.

Publish the prerelease and verify it is accessible without authentication, that the tag resolves to the tested commit, and that downloaded assets match SHA256SUMS. Keep source/build success separate from device acceptance. CI runs the same offline checks and exercises packaging; passing CI does not prove hardware behavior.

If an artifact is wrong, stop promotion. For an already published problem, explain it, mark the release accordingly and issue a new version instead of silently replacing a tag. Preserve earlier source/evidence and recovery information.

## Hardware qualification is separate

Publishing does not install a payload, reset hardware or flash firmware. Follow INSTALL.md for explicit administrator operations and QUALIFICATION.md for remaining acceptance. The notarized installer is available; broad hardware certification remains future work.
