# Continuum Kanban Project Setup

Project: mbox2_driver (`mbox2_driver`)
Continuum backend: `https://continuum.strangecalibur.io`

Agent fast path: read `CONTINUUM_AGENT_INSTRUCTIONS.md` at the project root. It is intentionally visible to normal file discovery and points agents to one task-shaped entry call before deeper reads.

Codex does not auto-load that product-specific filename; it auto-loads root `AGENTS.md`. The archive deliberately does not ship a root `AGENTS.md`, because extracting it could overwrite repo-owned instructions.
After extraction, run `python .continuum/install_agent_instructions.py` on Windows or the same command with `python3` on POSIX. The idempotent installer creates root `AGENTS.md` when absent and otherwise prepends or refreshes only a sentinel-delimited Continuum block while preserving all existing content.
Use `python .continuum/install_agent_instructions.py --check` in CI to verify the auto-loaded block matches the current fast path.

## 1) Save the token locally (never commit)
Create `.continuum/kanban.secret.env` with the project key or agent token:

```env
CONTINUUM_KANBAN_KEY_MBOX2_DRIVER=<REPLACE_WITH_PROJECT_KEY_OR_AGENT_TOKEN>
```

## 2) Load it in your shell
```bash
set -a && source .continuum/kanban.secret.env && set +a
```

PowerShell agents do not need a Bash `source` command: the generated Python entry helper loads the secret file itself.

## 3) Agent entry command (preferred)
```bash
python3 .continuum/agent_enter.py --mode tracked --intent "<current task>" --json
```

This helper is generated with the pack and uses only the Python standard library. It loads the manifest and secret file, verifies live Continuum access, fetches ranked agent-entry context when the backend supports it, and falls back to explicit Kanban plus Knowledge preflight checks.
Hard stop after execution: if the helper exits nonzero, returns `ok=false`, or reports a `preflight.status` other than `pass`, stop immediately. Do not make fallback API calls and do not answer from partial or local state.

## 4) Versioned machine verification contract
```bash
python3 .continuum/agent_enter.py --mode tracked --intent "<current task>" --json
```

Treat `schema_version: 1` and the `preflight.status`, `preflight.failed_gate`, `preflight.error_kind`, and `preflight.checks` fields as the stable automation contract. Omit `--json` only when a human-readable terminal summary is preferred.

Connection guidance:
- Use `https://continuum.strangecalibur.io` as the primary Continuum backend for this pack.
- Read this target from `.continuum/kanban.project.json` before the first network request; the manifest `backend_base_url` is authoritative.
- Do not replace it with a CLI override, `CONTINUUM_BASE_URL`, `relay_base_url`, localhost, a LAN address, or another inferred target.
- If `backend_base_url` is absent, stop before network access and report the manifest error.
- If your environment also exposes a compatibility proxy such as `:8088`, treat it as secondary and do not swap it in as the default onboarding route.
- Do not rewrite the pack back to old compatibility base-url wording unless you are intentionally testing a migration layer.

Project layout guidance (critical):
- Keep `.continuum` at the project root (`<project>/.continuum/*`).
- Do not conclude `.continuum` or `.hearth` is missing from broad file scans alone; hidden paths may be omitted.
- Check direct paths before reporting onboarding missing: `test -f .continuum/kanban.project.json`, `test -f .hearth/kanban.project.json`, `ls -la .continuum`, and `ls -la .hearth`.
- If `.continuum/kanban.project.json` is absent and `.hearth/kanban.project.json` is present, use `.hearth` as the Kanban bootstrap root and do not report missing `.continuum` files as a problem.
- If onboarding files are nested (for example `<project>/Emergency Survival Kanban/.continuum` or `.hearth`), move them to the root before running agents.
- Fail closed when neither `.continuum/kanban.project.json` nor `.hearth/kanban.project.json` is present at the current working directory root.

## 5) Agent behavior requirement
Agents should read `.continuum/kanban.project.json` on startup, source `.continuum/kanban.secret.env` when present, verify the manifest `auth_env_var` is set, set `project_id` on all Kanban reads/writes, and send the key in the configured header.
Continuum entry preflight is required before non-trivial work. Run `python3 .continuum/agent_enter.py --mode tracked --intent "<current task>" --json` after loading auth so local git/bootstrap state, live Kanban, ranked summaries, and linked Knowledge are read together.
Read the complete `module_index` returned by Agent Entry. Before the first command in a module, follow its `enter` endpoint or rerun the helper with `--module <module_id>`; retain the guide while its fingerprint is unchanged.
Before deployment, promotion, live-health, rollback, or recovery work, and before claiming what is live, healthy, observable, or recoverable, enter the Deploy module and read its shared workspace plus current dated observations. Treat Deploy as a read-only truth and instruction contract: it records no command execution, and positive live or recovery claims require fresh evidence.
If `project_chat_message` is present, read the actual message inline as a small Project Chat overlay and reply when requested.
When work is tied to an existing card, claim it immediately after preflight and before implementation: move the selected card to `in_progress` unless it is already `in_progress`, `blocked`, or `done`, and add a short activity note with the intended work.
Do not leave active implementation on a `ready` or `backlog` card.
If no card matches non-trivial work, create or select a card before editing, or explicitly report that the work is intentionally untracked.
If the generated entry helper is unavailable, manually verify projects, board summary, board-scoped hierarchy, and the Knowledge tree before building on local docs or prior summaries.
If live preflight cannot run or fails after the appropriate retry path, stop and report the failing gate instead of continuing as though Continuum has no state.
If the secret file is absent or the manifest `auth_env_var` is still empty after loading it, report an auth bootstrap failure and do not claim live board state.
If loopback HTTP to `localhost`, `127.0.0.1`, or `::1` fails with `Operation not permitted`, `Permission denied`, `EPERM`, or `EACCES`, report `local_network_permission_denied`, request approved unsandboxed/local-network execution, and rerun the same read-only preflight before claiming live board state is unavailable.
Agents must not use repo-local scripts to backfill, sync, curate, or bulk-link project knowledge.
Project notebooks, pages, and links are created during explicit work, not by scripted bootstrap.
When `/v1/agent/workflows` exposes the WorkSession lifecycle, prefer `start_work -> progress_work -> handoff_work/resume_work -> complete_work` (or `release_work`) through `/v1/agent/execute` instead of repeating separate search/read/update calls.
Use a unique `idempotency_key` for supported one-call lifecycle commits. Keep validate/plan/commit for completion, feedback, decision, decomposition, and release coordination.
Treat approval-reviewed network access as scarce. Batch independent reads through `/v1/agent/query`; use WorkSession completion/release or `/v1/agent/transact` for multi-entity closeout; and do not request one sandbox escalation per HTTP call or repeat live requests only to probe response shape.
Requirements remains a separate module. Lifecycle workflows may call its public operations and create typed links, but agents must not bypass the Requirements API or treat Requirements as embedded card fields.
Continuum list endpoints may return object envelopes or bare arrays depending on deployment/version. Normalize before indexing:
- projects: `.projects // .items // .`
- boards: `.boards // .items // .`
- cards: `.cards // .items // .`
- knowledge tree/search: `.tree // .nodes // .items // .results // .`

If the tool supports global or system-level custom instructions, add this resolver snippet first:

```text
When working in a project, use the managed Continuum block from root `AGENTS.md` when the runtime auto-loaded it. Otherwise check `CONTINUUM_AGENT_INSTRUCTIONS.md` first; it is the normal low-token entry source. Use `.continuum/custom-instructions-snippet.md` only when the tool needs a pasted project-instructions block. Use `.continuum/agent.onboarding.md` only when neither fast-path source is available; do not load both long rule sets. After that, read `.continuum/kanban.project.json` when present. If `.continuum/kanban.project.json` is absent and `.hearth/kanban.project.json` is present, use `.hearth` as the project's Kanban bootstrap root. Source the selected manifest's `backend_base_url` as the sole network target before the first request; do not override it from CLI flags, environment URL hints, `relay_base_url`, localhost, or LAN guesses, and stop before network access if it is absent. Source `kanban.secret.env` from the selected bootstrap root when it exists, verify the manifest `auth_env_var` is available, then treat live Continuum preflight as a required gate before non-trivial work. Run `python .continuum/agent_enter.py --mode tracked --intent "<current task>" --json` on Windows, or the same command with `python3` on POSIX, for generated `.continuum` packs. Use `python3 .hearth/agent_enter.py --mode tracked --intent "<current task>" --json` for a `.hearth` pack when that helper exists, so local git/bootstrap state, live Kanban, the ranked summary index, and linked Knowledge summaries are read together. Read the complete `module_index`; before the first command in a module, follow its `enter` endpoint or rerun the helper with `--module <module_id>`, and retain the full guide while its fingerprint is unchanged. Before deployment, promotion, live-health, rollback, or recovery work, and before claiming what is live, healthy, observable, or recoverable, enter the Deploy module and read its shared workspace plus current dated observations. Treat Deploy as a read-only truth and instruction contract: it records no command execution, and positive live or recovery claims require fresh evidence. If `project_chat_message` is present, read it inline as a small Project Chat overlay and reply when requested. When work is tied to an existing card, claim it after preflight and before implementation: move the selected card to `in_progress` unless it is already `in_progress`, `blocked`, or `done`, and add a short activity note. Do not leave active implementation on `ready` or `backlog`. If that helper is unavailable, manually verify Kanban and Knowledge with `GET /v1/kanban/projects`, `GET /v1/kanban/summary` using the manifest project and board, `GET /v1/kanban/cards` with `include_hierarchy=true&limit=2000`, and `GET /v1/knowledge/tree`. Verify every hierarchy card matches the requested board and fail closed when the returned card count is below the board summary `active_total`. Do not proceed from local files or prior summaries if this gate fails; report the failing auth, board, Knowledge, or network gate. If loopback HTTP to `localhost`, `127.0.0.1`, or `::1` fails with `Operation not permitted`, `Permission denied`, `EPERM`, or `EACCES`, report `local_network_permission_denied`, request approved unsandboxed/local-network execution, and rerun the same read-only preflight before claiming live Continuum state is unavailable. Do not conclude `.continuum` or `.hearth` is missing from a broad file scan alone; hidden paths may be omitted, so check direct paths such as `test -f .continuum/kanban.project.json`, `test -f .hearth/kanban.project.json`, `ls -la .continuum`, and `ls -la .hearth`. Do not report missing `.continuum` files as a problem when a valid `.hearth` bootstrap pack exists. Continuum list endpoints may return object envelopes or bare arrays, so normalize before indexing: projects `.projects // .items // .`, boards `.boards // .items // .`, cards `.cards // .items // .`, and knowledge tree/search `.tree // .nodes // .items // .results // .`. Treat the current workspace root as the project root and do not invent nested onboarding paths. Normal repo agents should use the generated agent entry helper and manifest-declared HTTP endpoints rather than assuming ChatGPT MCP tool names. MCP tools are connection- and profile-scoped. If a client advertises a tool but execution returns `Unknown tool`, stop and report `mcp_manifest_execution_mismatch`; do not guess aliases or continue from a stale manifest. Operators must restore the previous profile or replace/reconnect the connector and verify both `tools/list` and representative execution. After preflight, discover `GET /v1/agent/workflows`. When available, use the WorkSession lifecycle through `POST /v1/agent/execute`: `start_work`, `progress_work`, `handoff_work`/`resume_work`, then `complete_work` or `release_work`; use `apply_feedback`, `record_decision`, `decompose_work`, and `unblock_work` for their named coordination jobs. Safe lifecycle operations support one-call commit only with an `idempotency_key`; completion, decomposition, decision, feedback, and release work should retain validate/plan/commit review where offered. Treat `partial_success` as durable state requiring a current-state read before retry. Requirements is a separate module: lifecycle workflows coordinate through Requirements public operations and typed links, never by writing Requirements storage directly. Use `POST /v1/agent/query` for independent batched reads with canonical `{query_id, operation, arguments}` items; `args` and `inputs` are accepted aliases. Treat approval-reviewed network access as a scarce boundary: do not request one sandbox escalation per Continuum HTTP call, do not repeat live calls only to probe response shape, and group bounded preflight/read work plus bounded mutation/verification work when escalation is required. Use WorkSession completion/release or `/v1/agent/transact` for multi-entity closeout. Reviewer scarcity alone does not require a new magic approval phrase when normal closeout is already inside the user's authorized task; this never waives confirmation genuinely required by the underlying operation. Before a transaction, discover `GET /v1/agent/operations?mode=full` and read its `transaction_contract`. Canonical nodes use `{operation_id, operation, arguments, depends_on, preconditions}`; validate or plan before commit. Validation failures must preserve their structured code, operation index, field path, suggestions, and expected schema. If a client loses that body behind a generic tool/transport error, report `agent_contract_error_body_lost` instead of retrying guessed shapes. Use `AGENTS.md` only as an additional repo-local source when available, not as the default first step.
```

If this pack is being used outside the repo, read the bundled files:

- `CONTINUUM_AGENT_INSTRUCTIONS.md`
- `.continuum/agent.onboarding.md`
- `.continuum/custom-instructions-snippet.md`
- `.continuum/agent_enter.py`
- `.continuum/install_agent_instructions.py`

Instruction order for deployed packs:

1. the auto-loaded managed Continuum block in root `AGENTS.md`, when installed
2. `CONTINUUM_AGENT_INSTRUCTIONS.md` only when that managed block was not loaded
3. `.continuum/custom-instructions-snippet.md` only when neither fast path was loaded
4. `.continuum/agent.onboarding.md` only when all shorter sources are absent
5. `.continuum/kanban.project.json`
6. `.continuum/kanban.secret.env` for local auth
7. `.continuum/agent_enter.py` for live Kanban and Knowledge entry
8. live Kanban and Knowledge state
9. all remaining repo-owned content in `AGENTS.md`

`.continuum/custom-instructions-snippet.md` includes both the global resolver snippet and a project-specific standalone snippet for tools that need pasted project instructions.

## 6) Recommended read pattern for agents
Run `python3 .continuum/agent_enter.py --mode tracked --intent "<current task>" --json` first. Its versioned preflight object is the canonical machine contract. Use the curl checks below only as emergency diagnostics when the helper is unavailable or you are debugging entry/auth behavior.

Run hierarchy preflight before mutation-heavy work:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/kanban/cards?project_id=mbox2_driver&board=main&include_hierarchy=true&limit=2000" \
  | jq '(.cards // .items // .) as $cards | {count: ($cards | length), board_ids: ($cards | map(.board_id) | unique)}'
```
Verify every returned `card.board_id` matches the requested board and fail closed on mismatch.

Use compact board scans first:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/kanban/summary?project_id=mbox2_driver&board=main&include_cards=true&description_mode=preview&description_preview_chars=600"
```

Fetch full card bodies only when needed:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/kanban/cards/<card_id>?project_id=mbox2_driver&include_activity=true&include_subtasks=true&include_related=true"
```

If you intentionally need every card body in one response, use:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/kanban/summary?project_id=mbox2_driver&board=main&include_cards=true&description_mode=full"
```

Important: `GET /v1/kanban/cards` and `GET /v1/kanban/boards/{board_id}/workspace` still
return full descriptions today. Use them deliberately on memory-heavy boards.

Read the project-native Notes/Knowledge tree before deciding the project has no notes context:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/knowledge/tree?project_id=mbox2_driver&depth=4&mode=preview"
```
If the response contains an empty `tree`, the API is reachable but no notebooks, chapters, or pages exist yet.

Search existing Notes/Knowledge before creating new pages:
```bash
curl -s \
  -H "X-Kanban-Key: $CONTINUUM_KANBAN_KEY_MBOX2_DRIVER" \
  "https://continuum.strangecalibur.io/v1/knowledge/search?project_id=mbox2_driver&q=<query>"
```

## 7) Current card memory budget
- `description`: up to 32,000 chars
- `cannot_do_reason`: up to 4,000 chars
- activity `note`: up to 2,000 chars
- tags: up to 24 tags, 64 chars each
- related cards: up to 64
- attachments: up to 64

## 8) Safe defaults
- Keep writes scoped to this project only.
- Prefer summary preview for board scans and full card fetches on demand.
- Use context packs, backlinks, graph search, and timeline/playback reads before broad multi-entity edits.
- Normal repo agents use the generated agent entry helper and manifest-declared HTTP endpoints; do not assume ChatGPT MCP-specific tool names.
- MCP tools are connection/profile scoped. If an advertised tool returns `Unknown tool`, stop and report `mcp_manifest_execution_mismatch`; do not guess aliases or continue from a stale manifest.
- Use Knowledge as `notebook -> chapter -> page`: notebooks are top-level only, chapters are nestable sections, and pages are document bodies.
- Treat `partial_success` write responses as durable state plus follow-up failure; fetch current state before retrying.
- Metadata updates merge by default; replace metadata only when explicitly intended.
- Reuse or link existing objects when duplicate candidates are returned.
- Treat cross-project access as denied unless explicitly allowlisted.
- Rotate key if leaked.
- Do not use old project names, old bootstrap directories, or migration-era framing for current Continuum work unless you are explicitly doing compatibility cleanup.
