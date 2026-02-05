# Tasks: Automatic Container Cleanup

**Input**: Design documents from `/specs/002-cleanup-containers/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: Required (pytest + unittest.mock per constitution)
**Organization**: Tasks grouped by user story for independent implementation/testing

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 [P] Define mdify-managed container name prefixes in mdify/container.py

---

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T002 Create CleanupSummary/CleanupFailure dataclasses in mdify/container.py
- [x] T003 Implement managed-container discovery helper in mdify/container.py
- [x] T004 Implement stop/remove cleanup workflow with single retry in mdify/container.py
- [x] T005 Implement remote cleanup helpers (list/stop/remove) in mdify/ssh/remote_container.py

**Checkpoint**: Foundation ready for user story work

---

## Phase 3: User Story 1 - Automatic pre-processing cleanup (Priority: P1) 🎯 MVP

**Goal**: Ensure local mdify-managed containers are cleaned before processing starts.

**Independent Test**: Run local conversion with pre-existing mdify containers and confirm they are stopped/removed before processing.

### Tests for User Story 1

- [x] T006 [P] [US1] Add unit tests for local cleanup discovery in tests/test_container.py
- [x] T007 [P] [US1] Add unit tests for stop/remove retry behavior in tests/test_container.py
- [x] T008 [P] [US1] Add CLI integration test for pre-processing cleanup gate in tests/test_cli.py

### Implementation for User Story 1

- [x] T009 [US1] Invoke local cleanup before container start in mdify/cli.py
- [x] T010 [US1] Wire cleanup summary collection for local runs in mdify/cli.py

**Checkpoint**: US1 functional and testable independently

---

## Phase 4: User Story 2 - Remote machine cleanup (Priority: P2)

**Goal**: Ensure remote mdify-managed containers are cleaned before remote processing starts.

**Independent Test**: Run remote conversion with pre-existing mdify containers and confirm cleanup completes before remote container start.

### Tests for User Story 2

- [x] T011 [P] [US2] Add unit tests for remote cleanup commands in tests/test_ssh_client.py
- [x] T012 [P] [US2] Add CLI integration test for remote pre-processing cleanup in tests/test_cli.py

### Implementation for User Story 2

- [x] T013 [US2] Invoke remote cleanup before remote container start in mdify/cli.py
- [x] T014 [US2] Record remote cleanup summary in mdify/cli.py

**Checkpoint**: US2 functional and testable independently

---

## Phase 5: User Story 3 - Clear operator feedback (Priority: P3)

**Goal**: Provide clear cleanup summaries and prompt for confirmation on failure.

**Independent Test**: Trigger cleanup failure and verify CLI summary + confirmation prompt.

### Tests for User Story 3

- [x] T015 [P] [US3] Add tests for cleanup summary output in tests/test_cli.py
- [x] T016 [P] [US3] Add tests for CLI confirmation prompt on cleanup failure in tests/test_cli.py

### Implementation for User Story 3

- [x] T017 [US3] Add cleanup summary output and failure reporting in mdify/cli.py
- [x] T018 [US3] Add CLI confirmation prompt for cleanup failure in mdify/cli.py

**Checkpoint**: All user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T019 [P] [Docs/Polish] Validate quickstart steps in specs/002-cleanup-containers/quickstart.md
- [x] T020 [P] Validate cleanup completes within 30 seconds for 50 containers (mocked timing) in tests/test_container.py

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **User Stories (Phases 3–5)** → **Polish (Phase 6)**

### User Story Dependencies

- **US1 (P1)**: Depends on Phase 2 only
- **US2 (P2)**: Depends on Phase 2 only
- **US3 (P3)**: Depends on Phase 2 and benefits from US1/US2 outputs

### Parallel Opportunities

- T001 can run in parallel with other Phase 1 tasks (standalone)
- T006–T008 can run in parallel (different tests)
- T011–T012 can run in parallel (different tests)
- T015–T016 can run in parallel (different tests)

---

## Parallel Example: User Story 1

- T006 [US1] Add unit tests for local cleanup discovery in tests/test_container.py
- T007 [US1] Add unit tests for stop/remove retry behavior in tests/test_container.py
- T008 [US1] Add CLI integration test for pre-processing cleanup gate in tests/test_cli.py

---

## Parallel Example: User Story 2

- T011 [US2] Add unit tests for remote cleanup commands in tests/test_ssh_client.py
- T012 [US2] Add CLI integration test for remote pre-processing cleanup in tests/test_cli.py

---

## Parallel Example: User Story 3

- T015 [US3] Add tests for cleanup summary output in tests/test_cli.py
- T016 [US3] Add tests for CLI confirmation prompt on cleanup failure in tests/test_cli.py

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 + Phase 2
2. Implement US1 (tests first)
3. Validate US1 independently

### Incremental Delivery

1. US1 → US2 → US3
2. Validate each story independently before moving on

### Parallel Team Strategy

- After Phase 2, assign US1, US2, and US3 to separate developers if available
