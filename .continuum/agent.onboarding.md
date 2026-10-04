# mbox2_driver Agent Onboarding

Use this file when the onboarding pack is opened outside the repo and you need the minimum correct model without relying on other local files.

Normal repo agents should start with the visible `CONTINUUM_AGENT_INSTRUCTIONS.md` file. It contains the low-token fast path and prevents redundant preflight, search, and link reads.
For Codex, first run `.continuum/install_agent_instructions.py` once after extracting the pack. Codex will then auto-load the same fast path from a managed block in root `AGENTS.md`; do not read the visible copy again.

If you control a tool's global or system-level custom instructions, paste the resolver snippet from `.continuum/custom-instructions-snippet.md` there first.

Instruction priority for custom-instructions-driven tools:

1. the managed Continuum block in root `AGENTS.md` when the runtime auto-loaded it
2. `CONTINUUM_AGENT_INSTRUCTIONS.md` only when that managed block was not loaded
3. `.continuum/custom-instructions-snippet.md` when a tool needs pasted instructions
4. `.continuum/agent.onboarding.md` only as the fallback when none of the first three sources was loaded; do not read duplicate rule sets by default
5. `.continuum/kanban.project.json`
6. `.continuum/kanban.secret.env` for local auth
7. `.continuum/agent_enter.py` for live Kanban and Knowledge entry
8. live Kanban and Knowledge state
9. all remaining repo-owned content in `AGENTS.md`

## Workspace root guardrail (critical)

- Treat the folder you opened as the project root.
- `.continuum` must exist directly in that root as `<project>/.continuum/*`.
- Do not rely on broad file scans to discover `.continuum`; hidden paths may be omitted.
- Check direct paths before reporting onboarding missing: `test -f .continuum/kanban.project.json` and `ls -la .continuum`.
- If onboarding files are only present in a nested path (for example `<project>/Emergency Survival Kanban/.continuum`), stop and ask the user to fix the layout before doing Kanban work.
- Before any Kanban write, confirm `.continuum/kanban.project.json` exists relative to the current working directory.
- Never create a second `.continuum` directory in a nested folder.

## Canonical model

- Continuum is the project system of record.
- Treat live Kanban plus project-native Continuum knowledge as the canonical project state.
- Continuum Knowledge hierarchy is `notebook -> chapter -> page`: notebooks are top-level only, chapters are nestable sections inside notebooks or other chapters, and pages are document bodies.
- Do not create nested notebooks. If you mean notebook-in-notebook, create a `chapter`.
- Treat cards as intent, pages as memory, files as evidence, timeline as history, and links as meaning.
- Do not describe active work with deprecated project-memory labels or generated clones of boards, work items, or notes.
- Do not use old project names, old bootstrap directories, or migration-era framing for current Continuum work unless you are explicitly doing historical cleanup.
- Repo docs are supporting project material that must stay aligned with live Continuum project state.

## First steps

1. If you control global or system-level custom instructions, use the resolver snippet from `.continuum/custom-instructions-snippet.md`.
2. For Codex, run `.continuum/install_agent_instructions.py` once after pack extraction so root `AGENTS.md` auto-loads the managed fast path without replacing repo instructions.
3. Read `CONTINUUM_AGENT_INSTRUCTIONS.md` when the managed root block was not loaded. Use `.continuum/custom-instructions-snippet.md` instead only when the tool needs a pasted project instruction block.
4. Use this onboarding file as the fallback rule set, not as a second copy to read.
5. Read `.continuum/kanban.project.json` and resolve its `backend_base_url` before any network request. Treat that field as the only onboarding target; do not override or infer it, and stop if it is absent.
6. Source `.continuum/kanban.secret.env` from the same project root when it exists, then confirm the manifest `auth_env_var` is set.
7. If the secret file is absent or `auth_env_var` remains empty, report an auth bootstrap failure and do not claim live board state.
8. If loopback HTTP to `localhost`, `127.0.0.1`, or `::1` fails with `Operation not permitted`, `Permission denied`, `EPERM`, or `EACCES`, report `local_network_permission_denied`, request approved unsandboxed/local-network execution, and rerun the same read-only preflight before claiming live state is unavailable.
8. Run `python3 .continuum/agent_enter.py --mode tracked --intent "<current task>" --json` before non-trivial work.
9. Read the complete `module_index`; before the first command in a module, follow its `enter` endpoint or rerun the helper with `--module <module_id>` and retain the guide while its fingerprint is unchanged.
10. Before deployment, promotion, live-health, rollback, or recovery work, and before claiming what is live, healthy, observable, or recoverable, enter the Deploy module and read its shared workspace plus current dated observations. Treat Deploy as a read-only truth and instruction contract: it records no command execution, and positive live or recovery claims require fresh evidence.
11. If `project_chat_message` is present, read it inline as a small Project Chat overlay and reply when requested.
12. When working from a selected card, move the selected card to `in_progress` immediately after live preflight unless it is already `in_progress`, `blocked`, or `done`, and add a short activity note.
13. Do not continue implementation on a card that is still `ready` or `backlog`; if there is no matching card for non-trivial work, create or select one before editing.
14. If the generated helper is unavailable, verify access with `GET /v1/kanban/projects`, normalizing projects from `.projects // .items // .` before indexing.
15. Read the live board summary for project `mbox2_driver`, board `main`.
16. Read `GET /v1/knowledge/tree?project_id=mbox2_driver&depth=4&mode=preview` before deciding the project has no Notes/Knowledge context.
17. If live preflight cannot run or fails after the appropriate retry path, stop and report the failing gate instead of continuing from local docs or prior summaries.
18. If the tool can read repo files, read the repo `AGENTS.md` if it exists.
19. If the tool can read repo files, read any repo-local first-step skill before feature work.
20. If the repo provides a dedicated read-only entry checker, use it only as the strict fallback or when changing entry/auth behavior.
21. If active cards or docs still contain deprecated project-model wording, correct that wording before continuing with feature work.

## API response shape guardrail

Continuum collection endpoints may return object envelopes or bare arrays depending on deployment/version. Normalize before indexing:

- projects: `.projects // .items // .`
- boards: `.boards // .items // .`
- cards: `.cards // .items // .`
- knowledge tree/search: `.tree // .nodes // .items // .results // .`

## Graph, context, and write safety

- Use context packs and backlinks before broad edits that touch more than one card, page, file, or inventory object.
- Use graph search for concept-centric retrieval and timeline/playback reads for chronological reconstruction.
- Use cleanup candidate reads before archiving or deleting generated test content, duplicates, stale objects, or empty pages.
- Treat `partial_success` write responses as durable state plus follow-up failure; fetch current state before retrying.
- Metadata updates merge by default. Replace metadata only when explicit and intended.
- If duplicate candidates or high-write-volume warnings are returned, slow down and prefer update/link/reuse over more creates.
- Read the full `module_index` on entry. Before a module's first command, enter its complete guide and retain it while the guide fingerprint is unchanged.
- Before deployment, promotion, live-health, rollback, or recovery work, and before claiming what is live, healthy, observable, or recoverable, enter the Deploy module and read its shared workspace plus current dated observations. Treat Deploy as a read-only truth and instruction contract: it records no command execution, and positive live or recovery claims require fresh evidence.
- Treat `project_chat_message` as a tiny inline Project Chat overlay containing the actual priority message; reply when requested.
- Discover `/v1/agent/workflows`; when the WorkSession lifecycle is available, prefer `start_work`, `progress_work`, `handoff_work`/`resume_work`, and `complete_work` or `release_work` over repeated granular calls.
- Use `apply_feedback`, `record_decision`, `decompose_work`, and `unblock_work` only for their coordinated graph changes. Supply an `idempotency_key` for supported direct commits and use plan/commit for high-impact closure or graph creation.
- Use `/v1/agent/query` for independent batched reads with canonical `{query_id, operation, arguments}` items; `args` and `inputs` remain accepted aliases.
- Treat approval-reviewed network access as scarce. Do not request one sandbox escalation per Continuum HTTP call. Group a bounded preflight/read phase and bounded mutation/verification phase when escalation is required.
- Use WorkSession completion/release or `/v1/agent/transact` for multi-entity closeout, and do not repeat live calls merely to discover response-envelope shape.
- If normal Continuum closeout is already inside the user's authorized task, reviewer scarcity alone is not a reason to request a magic approval phrase. This does not waive explicit confirmation genuinely required by the operation.
- Before `/v1/agent/transact`, discover `/v1/agent/operations?mode=full` and read `transaction_contract`. Canonical nodes use `{operation_id, operation, arguments, depends_on, preconditions}`; validate or plan before commit and never guess the shape through retries.
- Validation errors must preserve structured codes, operation indexes or workflow names, field paths, suggestions, and expected schemas. Report `agent_contract_error_body_lost` if a client collapses this into a generic tool or transport error.
- Requirements is independently owned. Coordinate with it through the Requirements API/transaction operations and typed links; never write its database or fold its canonical state into WorkSession storage.

## Tool-interface guardrail

- Normal repo agents should use the generated agent entry helper and manifest-declared HTTP endpoints; onboarding must not depend on ChatGPT MCP-specific tool names.
- MCP tools are connection- and profile-scoped. Use only names advertised for the current connection, not names copied from docs or another connector.
- If a client advertises a tool but execution returns `Unknown tool`, stop and report `mcp_manifest_execution_mismatch`; do not guess aliases or continue from a stale manifest.
- Operators must restore the previous profile or replace/reconnect the connector and verify both `tools/list` and representative execution. Do not switch an established connector between `full` and `compact` in place.
- Compact MCP file reads use `continuum_file` actions `list`, `get`, `metadata`, or `text` with scopes `all`, `project`, `board`, or `card`; `get` aliases metadata and card scope requires `card_id`.

## What to read first in the repo

1. the auto-loaded managed Continuum block in root `AGENTS.md`, when installed
2. `CONTINUUM_AGENT_INSTRUCTIONS.md` only when the managed block was not loaded
3. `.continuum/custom-instructions-snippet.md` only when the tool needs pasted project instructions
4. `.continuum/agent.onboarding.md` only as the fallback when the fast path was unavailable
5. `.continuum/kanban.project.json`
6. `.continuum/agent_enter.py` with the current task as `--intent`
7. all remaining repo-owned content in `AGENTS.md`
8. any repo-local first-step skill for the project
9. the specific doc and card for the task you are doing
