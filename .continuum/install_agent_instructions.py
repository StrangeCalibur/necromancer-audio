#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple


SOURCE_NAME = "CONTINUUM_AGENT_INSTRUCTIONS.md"
TARGET_NAME = "AGENTS.md"
START_MARKER = "<!-- continuum-agent-fast-path:start -->"
END_MARKER = "<!-- continuum-agent-fast-path:end -->"
UTF8_BOM = b"\xef\xbb\xbf"


def _read_utf8(path: Path) -> Tuple[str, str, bool]:
    data = path.read_bytes()
    has_bom = data.startswith(UTF8_BOM)
    try:
        text = data.decode("utf-8-sig" if has_bom else "utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{path.name} is not UTF-8; refusing to modify it") from exc
    newline = "\r\n" if b"\r\n" in data else "\n"
    return text, newline, has_bom


def _managed_block(source_text: str, newline: str) -> str:
    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise RuntimeError(f"{SOURCE_NAME} is empty; refusing to modify {TARGET_NAME}")
    if START_MARKER in normalized or END_MARKER in normalized:
        raise RuntimeError(f"{SOURCE_NAME} contains reserved managed-block markers")
    body = normalized.replace("\n", newline)
    return newline.join((START_MARKER, body, END_MARKER))


def _merge(existing: str, block: str, newline: str) -> str:
    start_count = existing.count(START_MARKER)
    end_count = existing.count(END_MARKER)
    if start_count != end_count or start_count > 1:
        raise RuntimeError(
            f"{TARGET_NAME} has malformed Continuum markers; refusing to modify it"
        )
    if start_count == 1:
        start = existing.index(START_MARKER)
        end_start = existing.find(END_MARKER, start + len(START_MARKER))
        if end_start < 0:
            raise RuntimeError(
                f"{TARGET_NAME} has malformed Continuum markers; refusing to modify it"
            )
        end = end_start + len(END_MARKER)
        return existing[:start] + block + existing[end:]
    if not existing:
        return block + newline
    return block + newline + newline + existing


def _atomic_write(path: Path, text: str, *, has_bom: bool, mode: Optional[int]) -> None:
    prefix = UTF8_BOM if has_bom else b""
    payload = prefix + text.encode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or refresh the managed Continuum fast-path block in root AGENTS.md "
            "without replacing repo-owned instructions."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 0 only when AGENTS.md already contains the current managed block.",
    )
    args = parser.parse_args()

    bootstrap_dir = Path(__file__).resolve().parent
    project_root = bootstrap_dir.parent
    source_path = project_root / SOURCE_NAME
    target_path = project_root / TARGET_NAME
    if not source_path.is_file():
        print(f"error: missing {source_path}", file=sys.stderr)
        return 2
    if target_path.is_symlink():
        print(
            f"error: {target_path} is a symbolic link; refusing to replace it",
            file=sys.stderr,
        )
        return 2
    if target_path.exists() and not target_path.is_file():
        print(f"error: {target_path} is not a regular file", file=sys.stderr)
        return 2

    try:
        source_text, _, _ = _read_utf8(source_path)
        if target_path.exists():
            existing, newline, has_bom = _read_utf8(target_path)
            mode: Optional[int] = stat.S_IMODE(target_path.stat().st_mode)
        else:
            existing, newline, has_bom, mode = "", "\n", False, None
        desired = _merge(existing, _managed_block(source_text, newline), newline)
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if desired == existing:
        print(f"{TARGET_NAME}: Continuum fast path is current")
        return 0
    if args.check:
        print(f"{TARGET_NAME}: Continuum fast path is missing or stale", file=sys.stderr)
        return 1
    try:
        _atomic_write(target_path, desired, has_bom=has_bom, mode=mode)
    except OSError as exc:
        print(f"error: could not update {target_path}: {exc}", file=sys.stderr)
        return 2
    action = "created" if not existing else "updated"
    print(f"{TARGET_NAME}: {action} managed Continuum fast path; repo instructions preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
