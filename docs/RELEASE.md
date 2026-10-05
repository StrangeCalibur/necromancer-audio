# Developer alpha release procedure

The first public version is `0.1.0-alpha.1`. A release is an experimental prerelease, with a curated source archive, arm64 developer archive and `SHA256SUMS`. Developer binaries are ad-hoc signed and unnotarized; live acceptance limits belong in the release notes and QUALIFICATION.md.

## Prepare exact source

1. Review VERSION, the service version, README, changelog, notices and qualification. Keep their scope consistent.
2. Audit tracked files and all reachable Git history for credentials, personal paths/identifiers, recordings, raw logs and proprietary firmware. Private evidence and maintainer coordination stay ignored locally. Keep third-party notices in the source and HAL bundle.
3. Commit the reviewed source. Build a fresh clone with `python3 tools/build.py`, then run `python3 tools/test.py --offline`. No USB access, installation or service change is required.
4. Run `python3 tools/release.py` on that clean checkout. The tool requires matching source/test/payload fingerprints, exact archive allowlists, payload hashes and valid local signatures. It writes deterministic archives, checksums and a local readiness report; it does not publish.
5. Extract and inspect both archives. Verify their SHA-256 values, manifests, source provenance, licences and accompanying test report. The source archive builds without private project credentials. Record exact commit, toolchain, test count and archive hashes in the maintainer release record.

## Promote on GitHub

Create an annotated `v<VERSION>` tag for the verified commit. Prepare a draft prerelease with the reviewed notes, the two archives and SHA256SUMS. Re-read tag, draft and asset identities before promotion. Public visibility and publishing require owner authorization; the owner requested the first open source release on 2026-10-05.

Publish the prerelease and verify it is accessible without authentication, that the tag resolves to the tested commit, and that downloaded assets match SHA256SUMS. Keep source/build success separate from device acceptance. CI runs the same offline checks and exercises packaging; passing CI does not prove hardware behavior.

If an artifact is wrong, stop promotion. For an already published problem, explain it, mark the release accordingly and issue a new version instead of silently replacing a tag. Preserve earlier source/evidence and recovery information.

## Hardware qualification is separate

Publishing does not install a payload, reset hardware or flash firmware. Follow INSTALL.md for explicit administrator operations and QUALIFICATION.md for remaining acceptance. A notarized installer and broad hardware certification are future work.
