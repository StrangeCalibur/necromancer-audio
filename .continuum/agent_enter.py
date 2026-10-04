#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional


DEFAULT_TIMEOUT_SECONDS = 20
PREFLIGHT_SCHEMA_VERSION = 1
PREFLIGHT_HIERARCHY_LIMIT = 2000
BOOTSTRAP_DIR_NAMES = (".continuum", ".hearth")
AGENT_ENTER_USER_AGENT = "Continuum-Agent-Enter/1.0"
AGENT_GUIDANCE = {
    "module_orientation": (
        "Read module_index on entry. Before the first command in a module, enter its "
        "complete guide with continuum_discover(module_id='<module>', mode='full') "
        "or rerun this helper with --module <module>."
    ),
    "deployment_truth": (
        "Before deployment, promotion, live-health, rollback, or recovery work, and "
        "before claiming what is live, healthy, observable, or recoverable, enter the "
        "deployments module and read its workspace plus current dated observations. "
        "The Deploy contract cannot execute commands."
    ),
    "project_chat_overlay": (
        "If project_chat_message is present, read the actual message inline as "
        "Project Chat and reply when requested."
    ),
    "claim_selected_card": (
        "Move selected work to in_progress before implementation unless it is already "
        "in_progress, blocked, or done."
    ),
    "approval_batched_network": (
        "Treat approval-reviewed network access as a scarce boundary. Batch independent "
        "reads through /v1/agent/query and multi-entity closeout through a WorkSession "
        "completion/release workflow or /v1/agent/transact; do not request one approval "
        "per HTTP call or repeat network requests only to probe response shape."
    ),
}


class PreflightFailure(RuntimeError):
    def __init__(self, gate: str, message: str, error_kind: str = "") -> None:
        super().__init__(message)
        self.gate = str(gate or "bootstrap")
        self.error_kind = str(error_kind or "")


def _check(gate: str, name: str, status: str, detail: str) -> dict[str, str]:
    return {
        "gate": str(gate or "bootstrap"),
        "name": str(name or gate or "preflight"),
        "status": str(status or "FAIL").lower(),
        "detail": str(detail or ""),
    }


def _preflight_contract(
    checks: list[dict[str, str]],
    *,
    failed_gate: str = "",
    error_kind: str = "",
) -> dict[str, Any]:
    failed = next((item for item in checks if str(item.get("status") or "").lower() == "fail"), None)
    return {
        "status": "fail" if failed else "pass",
        "failed_gate": (str(failed_gate or (failed or {}).get("gate") or "") or None) if failed else None,
        "error_kind": (str(error_kind or "preflight_failed") or None) if failed else None,
        "checks": list(checks),
    }


def _attach_preflight_contract(
    payload: dict[str, Any],
    checks: list[dict[str, str]],
    *,
    failed_gate: str = "",
    error_kind: str = "",
) -> dict[str, Any]:
    payload["schema_version"] = PREFLIGHT_SCHEMA_VERSION
    payload["preflight"] = _preflight_contract(
        checks,
        failed_gate=failed_gate,
        error_kind=error_kind,
    )
    return payload


def _script_bootstrap_dir() -> Optional[Path]:
    script_parent = Path(__file__).resolve().parent
    if script_parent.name in BOOTSTRAP_DIR_NAMES:
        return script_parent
    return None


def _default_root() -> Path:
    script_bootstrap = _script_bootstrap_dir()
    if script_bootstrap is not None:
        return script_bootstrap.parent
    cwd = Path.cwd().resolve()
    return cwd


def _select_bootstrap_dir(root: Path) -> Path:
    script_bootstrap = _script_bootstrap_dir()
    if script_bootstrap is not None and script_bootstrap.parent == root:
        return script_bootstrap
    for dirname in BOOTSTRAP_DIR_NAMES:
        candidate = root / dirname
        if (candidate / "kanban.project.json").exists():
            return candidate
    return root / ".continuum"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _agent_entry_headers(headers: dict[str, str]) -> dict[str, str]:
    request_headers = dict(headers)
    if not any(key.lower() == "user-agent" for key in request_headers):
        request_headers["User-Agent"] = AGENT_ENTER_USER_AGENT
    return request_headers


def _run_git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _repo_context(root: Path) -> dict[str, Any]:
    status_lines = [line for line in _run_git(root, ["status", "--short"]).splitlines() if line.strip()]
    return {
        "root": str(root),
        "branch": _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": _run_git(root, ["rev-parse", "--short", "HEAD"]),
        "upstream": _run_git(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]),
        "dirty": bool(status_lines),
        "dirty_count": len(status_lines),
        "dirty_files": status_lines[:80],
    }


def _is_loopback_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return host.lower() in {"localhost", "127.0.0.1", "::1"}


def _permission_denied(exc: BaseException) -> bool:
    message = str(exc)
    errno_value = getattr(exc, "errno", None)
    return errno_value in {1, 13} or any(
        marker in message
        for marker in [
            "Operation not permitted",
            "Permission denied",
            "EPERM",
            "EACCES",
        ]
    )


def _request_json(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    query: Optional[dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    base = str(base_url or "").rstrip("/")
    params = {
        key: value
        for key, value in (query or {}).items()
        if value is not None and value != ""
    }
    url = f"{base}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=_agent_entry_headers(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        message = body.strip() or exc.reason or "HTTP error"
        error = RuntimeError(f"GET {path} returned HTTP {exc.code}: {message}")
        setattr(error, "http_status", exc.code)
        raise error from exc
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else exc
        if _is_loopback_url(url) and _permission_denied(reason if isinstance(reason, BaseException) else exc):
            raise RuntimeError(
                f"GET {path} failed: local HTTP access to {url} was blocked by process sandbox/permissions"
            ) from exc
        raise RuntimeError(f"GET {path} failed: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"GET {path} timed out") from exc
    except PermissionError as exc:
        if _is_loopback_url(url):
            raise RuntimeError(
                f"GET {path} failed: local HTTP access to {url} was blocked by process sandbox/permissions"
            ) from exc
        raise
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GET {path} returned non-JSON response") from exc
    if not isinstance(payload, dict):
        return {"items": payload}
    return payload


def _collection(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _classify_error(message: str) -> tuple[str, str]:
    if "local HTTP access" in message and "blocked by process sandbox/permissions" in message:
        return (
            "local_network_permission_denied",
            "The sandbox blocked loopback HTTP. Request approved local-network or unsandboxed execution and rerun this same read-only Continuum preflight before reporting live state unavailable.",
        )
    if "Connection refused" in message:
        return ("connection_refused", "Check that the Continuum backend is running on the configured base URL.")
    if "timed out" in message:
        return ("timeout", "Check backend health and network routing, then retry this preflight.")
    return ("request_failed", "Inspect the failing gate and retry after correcting the reported condition.")


def _error_payload(
    root: Path,
    message: str,
    *,
    repo: Optional[dict[str, Any]] = None,
    checks: Optional[list[dict[str, str]]] = None,
    failed_gate: str = "bootstrap",
    error_kind: str = "",
) -> dict[str, Any]:
    classified_kind, remediation = _classify_error(message)
    explicit_error_kind = str(error_kind or "").strip()
    resolved_checks = list(checks or [])
    if not any(str(item.get("status") or "").lower() == "fail" for item in resolved_checks):
        resolved_checks.append(_check(failed_gate, failed_gate, "FAIL", message))
    payload = {
        "ok": False,
        "error_kind": explicit_error_kind or classified_kind,
        "error": message,
        "remediation": remediation,
        "repo": repo or _repo_context(root),
    }
    return _attach_preflight_contract(
        payload,
        resolved_checks,
        failed_gate=failed_gate,
        error_kind=explicit_error_kind or classified_kind,
    )


def _request_gate(gate: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return _request_json(**kwargs)
    except RuntimeError as exc:
        message = str(exc)
        if "HTTP 401" in message or "HTTP 403" in message:
            raise PreflightFailure("auth", message, "auth_denied") from exc
        raise PreflightFailure(gate, message, f"{gate}_failed") from exc


def _server_preflight_checks(
    payload: dict[str, Any],
    *,
    mode: str,
    expected_project_id: str,
    expected_board_id: str,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    project_id = str(scope.get("project_id") or "").strip()
    board_id = str(scope.get("board_id") or "").strip()
    if project_id == expected_project_id:
        checks.append(_check("projects", "projects endpoint", "PASS", f"selected project {project_id}"))
    else:
        checks.append(
            _check(
                "projects",
                "projects endpoint",
                "FAIL",
                f"project mismatch: expected {expected_project_id!r}, got {project_id!r}",
            )
        )
    if str(scope.get("auth") or "").strip().lower() == "verified":
        checks.append(_check("auth", "auth verified", "PASS", "backend accepted the configured credential"))
    else:
        checks.append(_check("auth", "auth verified", "FAIL", "agent-entry response did not verify auth"))

    board = payload.get("board") if isinstance(payload.get("board"), dict) else {}
    response_board_id = str(board.get("board_id") or board_id).strip()
    if not board:
        checks.append(_check("summary", "board summary", "FAIL", "agent-entry response omitted board summary"))
    elif board_id != expected_board_id or response_board_id != expected_board_id:
        checks.append(
            _check(
                "summary",
                "board summary",
                "FAIL",
                f"board mismatch: expected={expected_board_id!r} scope={board_id!r} summary={response_board_id!r}",
            )
        )
    else:
        checks.append(
            _check(
                "summary",
                "board summary",
                "PASS",
                f"active_total={board.get('active_total')} board={response_board_id}",
            )
        )

    if mode == "quick":
        checks.append(_check("hierarchy", "hierarchy preflight", "WARN", "quick mode does not read hierarchy"))
        checks.append(_check("knowledge", "knowledge tree", "WARN", "quick mode does not read Knowledge"))
        return checks
    try:
        active_total = int(board.get("visible_total", board.get("active_total")))
    except (TypeError, ValueError):
        active_total = -1
    if active_total < 0:
        checks.append(_check("hierarchy", "hierarchy preflight", "FAIL", "board summary omitted active_total"))
    elif active_total > PREFLIGHT_HIERARCHY_LIMIT:
        checks.append(
            _check(
                "hierarchy",
                "hierarchy preflight",
                "FAIL",
                f"active_total={active_total} exceeds agent-entry limit={PREFLIGHT_HIERARCHY_LIMIT}",
            )
        )
    else:
        checks.append(
            _check(
                "hierarchy",
                "hierarchy preflight",
                "PASS",
                f"server-scoped hierarchy covers active_total={active_total}",
            )
        )
    knowledge = payload.get("knowledge") if isinstance(payload.get("knowledge"), dict) else {}
    if "root_count" in knowledge and "visible_count" in knowledge:
        checks.append(
            _check(
                "knowledge",
                "knowledge tree",
                "PASS",
                f"{int(knowledge.get('root_count') or 0)} root(s), {int(knowledge.get('visible_count') or 0)} visible node(s)",
            )
        )
    else:
        checks.append(_check("knowledge", "knowledge tree", "FAIL", "agent-entry response omitted Knowledge counts"))
    return checks


def _manual_preflight(
    *,
    base_url: str,
    project_id: str,
    board_id: str,
    key_header: str,
    key_value: str,
    timeout: int,
    checks: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    preflight_checks = list(checks or [])
    headers = {key_header: key_value}
    projects_payload = _request_gate(
        "projects",
        base_url=base_url,
        path="/v1/kanban/projects",
        headers=headers,
        timeout=timeout,
    )
    projects = _collection(projects_payload, "projects", "items")
    project_ids = {
        str(item.get("project_id") or item.get("id") or "")
        for item in projects
        if isinstance(item, dict)
    }
    if project_id not in project_ids:
        raise PreflightFailure("projects", f"project {project_id!r} is not visible to this key", "project_not_visible")
    preflight_checks.append(_check("projects", "projects endpoint", "PASS", f"{len(projects)} visible project(s)"))

    summary_payload = _request_gate(
        "summary",
        base_url=base_url,
        path="/v1/kanban/summary",
        headers=headers,
        query={
            "project_id": project_id,
            "board": board_id,
            "include_cards": "true",
            "description_mode": "preview",
        },
        timeout=timeout,
    )
    summary_project_id = str(summary_payload.get("project_id") or "").strip()
    summary_board_id = str(summary_payload.get("board_id") or summary_payload.get("board") or "").strip()
    if summary_project_id and summary_project_id != project_id:
        raise PreflightFailure(
            "summary",
            f"project mismatch: expected {project_id!r}, got {summary_project_id!r}",
            "summary_scope_mismatch",
        )
    if summary_board_id and summary_board_id != board_id:
        raise PreflightFailure(
            "summary",
            f"board mismatch: expected {board_id!r}, got {summary_board_id!r}",
            "summary_scope_mismatch",
        )
    preflight_checks.append(
        _check(
            "summary",
            "board summary",
            "PASS",
            f"loaded project={summary_project_id or project_id} board={summary_board_id or board_id}",
        )
    )
    cards_payload = _request_gate(
        "hierarchy",
        base_url=base_url,
        path="/v1/kanban/cards",
        headers=headers,
        query={
            "project_id": project_id,
            "board": board_id,
            "include_hierarchy": "true",
            "limit": str(PREFLIGHT_HIERARCHY_LIMIT),
        },
        timeout=timeout,
    )
    cards = _collection(cards_payload, "cards", "items")
    board_ids = sorted(
        {
            str(card.get("board_id") or "")
            for card in cards
            if isinstance(card, dict) and str(card.get("board_id") or "")
        }
    )
    if board_ids and board_ids != [board_id]:
        raise PreflightFailure(
            "hierarchy",
            f"board preflight mismatch: expected {board_id!r}, got {board_ids!r}",
            "hierarchy_scope_mismatch",
        )

    active_total = summary_payload.get("visible_total")
    if active_total is None:
        active_total = summary_payload.get("active_total")
    if active_total is None:
        active_total = summary_payload.get("active")
    if active_total is None:
        active_total = len(cards)
    try:
        expected_card_count = int(active_total)
    except (TypeError, ValueError):
        expected_card_count = len(cards)
    if expected_card_count > len(cards):
        raise PreflightFailure(
            "hierarchy",
            (
                f"hierarchy response truncated: returned {len(cards)} card(s), "
                f"expected active_total={expected_card_count}, limit={PREFLIGHT_HIERARCHY_LIMIT}"
            ),
            "hierarchy_truncated",
        )
    preflight_checks.append(
        _check("hierarchy", "hierarchy preflight", "PASS", f"{len(cards)} card(s), board={board_id}")
    )

    knowledge_payload = _request_gate(
        "knowledge",
        base_url=base_url,
        path="/v1/knowledge/tree",
        headers=headers,
        query={"project_id": project_id, "depth": 4, "mode": "preview"},
        timeout=timeout,
    )
    nodes = _collection(knowledge_payload, "tree", "nodes", "items", "results")
    preflight_checks.append(_check("knowledge", "knowledge tree", "PASS", f"{len(nodes)} root node(s)"))
    open_total = summary_payload.get("open_total")
    if open_total is None:
        open_total = summary_payload.get("open_work_total")
    if open_total is None:
        open_total = summary_payload.get("active_total")
    if open_total is None:
        open_total = summary_payload.get("active")
    if open_total is None:
        open_total = len(cards)
    markdown = "\n".join(
        [
            "# Continuum Agent Entry",
            "",
            "Manual preflight completed because the generated helper did not receive a ranked agent-entry response.",
            "",
            f"- Project: {project_id}",
            f"- Board: {board_id}",
            f"- Visible projects: {len(projects)}",
            f"- Board cards: {len(cards)}",
            f"- Board ids: {', '.join(board_ids) if board_ids else '(none)'}",
            f"- Knowledge nodes visible: {len(nodes)}",
            "",
            "Continue only with task-specific reads. Use the board summary, hierarchy, and Knowledge tree as current state.",
        ]
    )
    payload = {
        "ok": True,
        "compatibility_fallback": True,
        "mode": "tracked",
        "scope": {
            "project_id": project_id,
            "board_id": board_id,
            "auth": "verified",
        },
        "board": {
            "active_total": active_total,
            "visible_total": active_total,
            "open_total": open_total,
            "completed_total": summary_payload.get("completed_total"),
            "blocked_total": summary_payload.get("blocked_total"),
            "backlog_total": summary_payload.get("backlog_total"),
        },
        "work_index": [],
        "knowledge_index": [],
        "warnings": ["used manual Kanban/Knowledge preflight instead of ranked agent-entry response"],
        "next_reads": [],
        "markdown": markdown,
        "manual_preflight": {
            "project_count": len(projects),
            "card_count": len(cards),
            "board_ids": board_ids,
            "knowledge_node_count": len(nodes),
        },
    }
    return _attach_preflight_contract(payload, preflight_checks)


def _run_agent_enter(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    repo = _repo_context(root)
    bootstrap_dir = _select_bootstrap_dir(root)
    manifest_path = bootstrap_dir / "kanban.project.json"
    secret_path = bootstrap_dir / "kanban.secret.env"
    checks: list[dict[str, str]] = []

    try:
        try:
            manifest = _read_json_file(manifest_path)
        except RuntimeError as exc:
            raise PreflightFailure("bootstrap", str(exc), "bootstrap_invalid") from exc
        project_id = str(args.project_id or manifest.get("project_id") or "").strip()
        board_id = str(args.board_id or manifest.get("default_board_id") or "main").strip() or "main"
        base_url = str(manifest.get("backend_base_url") or "").strip()
        key_header = str(manifest.get("key_header") or "X-Kanban-Key").strip() or "X-Kanban-Key"
        auth_env_var = str(manifest.get("auth_env_var") or "").strip()
        if not project_id:
            raise PreflightFailure("bootstrap", "project_id missing from manifest", "bootstrap_invalid")
        if not base_url:
            raise PreflightFailure(
                "bootstrap",
                "backend_base_url missing from manifest; no network request was attempted",
                "bootstrap_invalid",
            )
        if not auth_env_var:
            raise PreflightFailure("bootstrap", "auth_env_var missing from manifest", "bootstrap_invalid")
        checks.append(
            _check(
                "bootstrap",
                "manifest",
                "PASS",
                f"project={project_id} board={board_id} base={base_url} auth_env={auth_env_var}",
            )
        )
        secret_paths = [secret_path]
        compatibility_secret = root / ".hearth" / "kanban.secret.env"
        if bootstrap_dir.name == ".continuum" and compatibility_secret != secret_path:
            secret_paths.append(compatibility_secret)
        env_values: dict[str, str] = {}
        loaded_secret_files: list[str] = []
        for candidate_secret_path in secret_paths:
            candidate_values = _load_env_file(candidate_secret_path)
            if candidate_values:
                loaded_secret_files.append(str(candidate_secret_path))
                env_values.update(candidate_values)
        key_value = str(os.environ.get(auth_env_var) or env_values.get(auth_env_var) or "").strip()
        if not key_value:
            checked_paths = ", ".join(str(path) for path in secret_paths)
            raise PreflightFailure(
                "auth",
                f"{auth_env_var} is empty after checking process env and {checked_paths}",
                "auth_missing",
            )
        checks.append(_check("auth", "auth key", "PASS", f"{auth_env_var} is present; value redacted"))

        query = {
            "board_id": board_id,
            "mode": args.mode,
            "card_id": args.card_id,
            "intent": args.intent,
            "work_limit": args.work_limit,
            "knowledge_limit": args.knowledge_limit,
            "activity_limit": args.activity_limit,
            "description_preview_chars": args.description_preview_chars,
            "representation": "structured" if args.json else "both",
        }
        try:
            payload = _request_json(
                base_url=base_url,
                path=f"/v1/kanban/projects/{urllib.parse.quote(project_id, safe='')}/agent-entry",
                headers={key_header: key_value},
                query=query,
                timeout=args.timeout,
            )
        except RuntimeError as exc:
            if "agent-entry" not in str(exc) or "HTTP 404" not in str(exc):
                message = str(exc)
                if "HTTP 401" in message or "HTTP 403" in message:
                    raise PreflightFailure("auth", message, "auth_denied") from exc
                raise PreflightFailure("projects", message, "projects_failed") from exc
            payload = _manual_preflight(
                base_url=base_url,
                project_id=project_id,
                board_id=board_id,
                key_header=key_header,
                key_value=key_value,
                timeout=args.timeout,
                checks=checks,
            )
            payload["warnings"] = list(payload.get("warnings") or []) + [
                "agent-entry endpoint returned HTTP 404; update or restart the Continuum backend for ranked entry output",
            ]
        payload["repo"] = repo
        payload["bootstrap"] = {
            "bootstrap_dir": str(bootstrap_dir),
            "manifest": str(manifest_path),
            "secret_file_loaded": bool(loaded_secret_files),
            "secret_files_checked": [str(path) for path in secret_paths],
            "secret_files_loaded": loaded_secret_files,
            "backend_base_url": base_url,
            "project_id": project_id,
            "board_id": board_id,
            "key_header": key_header,
            "auth_env_var": auth_env_var,
            "auth": "verified" if payload.get("ok", False) else "unknown",
        }
        if payload.get("compatibility_fallback"):
            if str(getattr(args, "module", "") or "").strip():
                payload["ok"] = False
                payload["error_kind"] = "module_orientation_unavailable"
                payload["error"] = (
                    "The compatibility fallback cannot provide the requested full "
                    "module guide; update or restart the Continuum backend."
                )
            return payload
        if not payload.get("ok", False):
            message = str(payload.get("error") or "agent-entry response reported failure")
            checks.append(_check("projects", "projects endpoint", "FAIL", message))
            return _attach_preflight_contract(
                payload,
                checks,
                failed_gate="projects",
                error_kind=str(payload.get("error_kind") or "projects_failed"),
            )
        checks.extend(
            _server_preflight_checks(
                payload,
                mode=str(args.mode or "tracked"),
                expected_project_id=project_id,
                expected_board_id=board_id,
            )
        )
        contract_payload = _attach_preflight_contract(payload, checks)
        preflight = contract_payload.get("preflight") if isinstance(contract_payload.get("preflight"), dict) else {}
        if preflight.get("status") == "fail":
            failed_gate = str(preflight.get("failed_gate") or "preflight")
            failed_check = next(
                (item for item in checks if str(item.get("status") or "").lower() == "fail"),
                {},
            )
            detail = str(failed_check.get("detail") or "")
            if failed_gate == "hierarchy" and ("exceeds" in detail or "truncated" in detail):
                error_kind = "hierarchy_truncated"
            elif "mismatch" in detail:
                error_kind = f"{failed_gate}_scope_mismatch"
            else:
                error_kind = f"{failed_gate}_failed"
            preflight["error_kind"] = error_kind
            contract_payload["ok"] = False
            contract_payload["error_kind"] = error_kind
            contract_payload["error"] = f"agent-entry response failed the {failed_gate} preflight gate"
            contract_payload["remediation"] = "Inspect the failed check, correct the response or scope, and rerun."
        module_value = str(getattr(args, "module", "") or "").strip()
        if module_value and contract_payload.get("ok", False):
            try:
                module_payload = _request_json(
                    base_url=base_url,
                    path=(
                        "/v1/agent/modules/"
                        f"{urllib.parse.quote(module_value, safe='')}"
                    ),
                    headers={key_header: key_value},
                    query={
                        "project_id": project_id,
                        "intent": args.intent,
                        "card_id": args.card_id,
                        "representation": "structured",
                    },
                    timeout=args.timeout,
                )
            except RuntimeError as exc:
                contract_payload["ok"] = False
                contract_payload["error_kind"] = "module_entry_failed"
                contract_payload["error"] = str(exc)
                contract_payload["remediation"] = (
                    "Use a module_id advertised by module_index, verify the "
                    "backend module-entry endpoint, and rerun."
                )
            else:
                module_guide = (
                    module_payload.get("module_guide")
                    if isinstance(module_payload, dict)
                    else None
                )
                if not isinstance(module_guide, dict):
                    contract_payload["ok"] = False
                    contract_payload["error_kind"] = "module_entry_contract_missing"
                    contract_payload["error"] = "module-entry response omitted module_guide"
                else:
                    module_summary = (
                        module_guide.get("module")
                        if isinstance(module_guide.get("module"), dict)
                        else {}
                    )
                    contract_payload["selected_module"] = str(
                        module_summary.get("module_id") or module_value
                    )
                    contract_payload["module_guide"] = module_guide
                    module_chat_message = module_payload.get("project_chat_message")
                    if isinstance(module_chat_message, dict) and module_chat_message:
                        contract_payload["project_chat_message"] = module_chat_message
        return contract_payload
    except PreflightFailure as exc:
        checks.append(_check(exc.gate, exc.gate, "FAIL", str(exc)))
        return _error_payload(
            root,
            str(exc),
            repo=repo,
            checks=checks,
            failed_gate=exc.gate,
            error_kind=exc.error_kind,
        )


def _write_diagnostic(root: Path, payload: dict[str, Any], args: argparse.Namespace) -> None:
    if args.no_diagnostic_log:
        return
    try:
        event = {
            "ts": int(time.time()),
            "command": "continuum_bootstrap_agent_enter",
            "schema_version": payload.get("schema_version"),
            "ok": bool(payload.get("ok", False)),
            "bootstrap": payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else {},
            "error_kind": payload.get("error_kind"),
            "preflight": payload.get("preflight") if isinstance(payload.get("preflight"), dict) else {},
            "args": {
                "mode": args.mode,
                "card_id": args.card_id,
                "intent_present": bool(args.intent),
                "json": bool(args.json),
            },
        }
        log_path = _select_bootstrap_dir(root) / "agent-preflight.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:
        return


def _print_text(payload: dict[str, Any]) -> None:
    print("Continuum agent enter")
    repo = payload.get("repo") if isinstance(payload.get("repo"), dict) else {}
    if repo:
        dirty = "dirty" if repo.get("dirty") else "clean"
        print(
            "repo: "
            f"{repo.get('branch') or '-'}@{repo.get('head') or '-'} "
            f"({dirty}, {int(repo.get('dirty_count') or 0)} file(s))"
        )
    if not payload.get("ok", False):
        print(f"result: FAIL - {payload.get('error') or 'unknown error'}")
        remediation = str(payload.get("remediation") or "").strip()
        if remediation:
            print(f"remediation: {remediation}")
        return

    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    board = payload.get("board") if isinstance(payload.get("board"), dict) else {}
    print(
        "target: "
        f"project={scope.get('project_id') or '-'} "
        f"board={scope.get('board_id') or '-'} "
        f"mode={payload.get('mode') or '-'}"
    )
    print(
        "board: "
        f"visible={int(board.get('visible_total') or board.get('active_total') or 0)} "
        f"open={int(board.get('open_total') or board.get('open_work_total') or 0)} "
        f"blocked={int(board.get('blocked_total') or 0)} "
        f"backlog={int(board.get('backlog_total') or 0)}"
    )
    warnings = []
    for item in payload.get("warnings") or []:
        if isinstance(item, dict):
            message = str(item.get("message") or item.get("code") or item).strip()
            level = str(item.get("level") or "").strip()
            warnings.append(f"{level}: {message}" if level else message)
        else:
            message = str(item).strip()
            if message:
                warnings.append(message)
    if warnings:
        print("warnings:")
        for item in warnings:
            print(f"- {item}")
    print("")
    guidance = payload.get("agent_guidance") if isinstance(payload.get("agent_guidance"), dict) else {}
    for code, message in guidance.items():
        print(f"{code}: {message}")
    print("")
    markdown = str(payload.get("markdown") or "").strip()
    print(markdown or "No agent-entry markdown returned.")
    module_guide = (
        payload.get("module_guide")
        if isinstance(payload.get("module_guide"), dict)
        else {}
    )
    module = (
        module_guide.get("module")
        if isinstance(module_guide.get("module"), dict)
        else {}
    )
    commands = (
        module_guide.get("commands")
        if isinstance(module_guide.get("commands"), list)
        else []
    )
    if module:
        print("")
        print(
            "Module guide: "
            f"{module.get('label') or module.get('module_id')} "
            f"({len(commands)} registered command(s))"
        )
        for command in commands:
            if not isinstance(command, dict):
                continue
            allowed = "allowed" if command.get("allowed") else "unavailable"
            print(
                f"- {command.get('name')}: {command.get('description')} "
                f"Use when: {command.get('use_when')} [{allowed}]"
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generated Continuum agent entry: load .continuum/.hearth auth and read live Kanban plus Knowledge state."
    )
    parser.add_argument("--root", default="", help="Project root containing .continuum/ or .hearth/. Defaults to cwd or this script's parent.")
    parser.add_argument("--project-id", default="", help="Override manifest project_id.")
    parser.add_argument("--board-id", default="", help="Override manifest default board.")
    parser.add_argument("--mode", choices=["quick", "tracked", "full"], default="tracked")
    parser.add_argument("--card-id", default="", help="Optional selected card for full mode.")
    parser.add_argument("--intent", default="", help="Optional task intent used to rank cards and Knowledge.")
    parser.add_argument(
        "--module",
        default="",
        help=(
            "After initial entry, enter this module's complete command, workflow, "
            "relationship, permission, and task-relevance guide."
        ),
    )
    parser.add_argument("--work-limit", type=int, default=10)
    parser.add_argument("--knowledge-limit", type=int, default=10)
    parser.add_argument("--activity-limit", type=int, default=10)
    parser.add_argument("--description-preview-chars", type=int, default=300)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of compact text.")
    parser.add_argument("--no-diagnostic-log", action="store_true", help="Do not append agent-preflight.log under the selected bootstrap root.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    payload = _run_agent_enter(args)
    payload["agent_guidance"] = dict(AGENT_GUIDANCE)
    _write_diagnostic(root, payload, args)
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        _print_text(payload)
    return 0 if payload.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
