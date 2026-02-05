# Implementation Plan: Automatic Container Cleanup

**Branch**: `002-cleanup-containers` | **Date**: February 5, 2026 | **Spec**: [specs/002-cleanup-containers/spec.md](specs/002-cleanup-containers/spec.md)
**Input**: Feature specification from [specs/002-cleanup-containers/spec.md](specs/002-cleanup-containers/spec.md)

## Summary

Add a pre-processing cleanup step that stops and removes mdify-managed containers on both local and remote targets before conversion starts, with a single retry and a CLI confirmation gate on failure.

## Technical Context

**Language/Version**: Python 3.8+  
**Primary Dependencies**: requests (runtime), asyncssh (optional for remote)  
**Storage**: N/A  
**Testing**: pytest + unittest.mock  
**Target Platform**: macOS and Linux CLI environments  
**Project Type**: single CLI package  
**Performance Goals**: cleanup completes within 30 seconds for up to 50 containers  
**Constraints**: lightweight CLI, multi-runtime container support, no ML dependencies  
**Scale/Scope**: single-user CLI runs per host; local and SSH-remote targets

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- ✅ Lightweight CLI, heavy container: no new ML deps required.
- ✅ Container runtime abstraction preserved (local + remote).
- ✅ Defensive resource management unaffected; cleanup is pre-start only.
- ✅ Graceful error handling required by retry + confirmation.
- ✅ Test-first development planned for container/CLI/SSH modules.
- ✅ Clean module separation maintained (CLI orchestration, container lifecycle, SSH).

**Post-Design Re-check**: ✅ No violations introduced in Phase 1 outputs.

## Project Structure

### Documentation (this feature)

```text
specs/002-cleanup-containers/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (repository root)

```text
mdify/
├── cli.py
├── container.py
├── docling_client.py
└── ssh/
    ├── client.py
    ├── remote_container.py
    └── models.py

tests/
├── test_cli.py
├── test_container.py
└── test_ssh_client.py
```

**Structure Decision**: Single CLI package; changes limited to container lifecycle and CLI orchestration with SSH remote support.

## Phase 0: Research Summary

See [specs/002-cleanup-containers/research.md](specs/002-cleanup-containers/research.md).

## Phase 1: Design & Contracts

- Data model definitions: [specs/002-cleanup-containers/data-model.md](specs/002-cleanup-containers/data-model.md)
- CLI/cleanup behavior contract: [specs/002-cleanup-containers/contracts/cleanup_flow.md](specs/002-cleanup-containers/contracts/cleanup_flow.md)
- Quickstart instructions: [specs/002-cleanup-containers/quickstart.md](specs/002-cleanup-containers/quickstart.md)

## Phase 2: Implementation Plan

1. Add cleanup discovery for mdify-managed containers (local runtime + SSH remote).
2. Implement stop/remove sequence with single retry and summary reporting.
3. Add CLI confirmation gate on cleanup failure (TTY prompt).
4. Wire cleanup into local and remote conversion flows before container start.
5. Add unit tests covering local/remote cleanup, retry, and confirmation behavior.

## Complexity Tracking

No constitution violations.
