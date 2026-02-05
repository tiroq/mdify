# Feature Specification: Automatic Container Cleanup

**Feature Branch**: `002-cleanup-containers`  
**Created**: February 5, 2026  
**Status**: Draft  
**Input**: User description: "add feature to automatically check all containers on remote/current machine and stop containers before start processing data additionally remove them to freeup space"

## Clarifications

### Session 2026-02-05

- Q: Which containers should be stopped/removed? → A: Only mdify-managed containers.
- Q: What happens if cleanup fails? → A: Ask for confirmation before processing.
- Q: Should cleanup be retried automatically? → A: Retry once, then ask for confirmation.
- Q: How should confirmation be obtained? → A: CLI prompt confirmation.

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Automatic pre-processing cleanup (Priority: P1)

As an operator, I want mdify-managed containers on the target machine to be stopped and removed before data processing begins so that processing starts with a clean environment and frees disk space.

**Why this priority**: Prevents processing failures and resource exhaustion caused by leftover containers.

**Independent Test**: Can be fully tested by starting multiple containers, running a processing command, and confirming all containers are stopped/removed before processing starts.

**Acceptance Scenarios**:

1. **Given** the target machine has running mdify-managed containers, **When** data processing is initiated, **Then** those containers are stopped before processing begins.
2. **Given** the target machine has stopped mdify-managed containers, **When** data processing is initiated, **Then** those containers are removed before processing begins.

---

### User Story 2 - Remote machine cleanup (Priority: P2)

As an operator using a remote machine, I want the same pre-processing cleanup to run on that remote machine so that remote processing starts with a clean environment.

**Why this priority**: Remote processing is common and must be protected from container buildup just like local runs.

**Independent Test**: Can be fully tested by running remote processing on a machine with existing containers and verifying cleanup occurs before processing.

**Acceptance Scenarios**:

1. **Given** a remote target machine with running or stopped mdify-managed containers, **When** remote data processing is initiated, **Then** the cleanup completes on the remote machine before processing begins.

---

### User Story 3 - Clear operator feedback (Priority: P3)

As an operator, I want clear feedback about cleanup actions so that I can confirm containers were stopped/removed and understand any failures.

**Why this priority**: Transparency helps operators trust the cleanup and respond quickly to issues.

**Independent Test**: Can be fully tested by initiating processing and reviewing the reported cleanup summary and error messages.

**Acceptance Scenarios**:

1. **Given** cleanup succeeds, **When** processing starts, **Then** a summary indicates how many containers were stopped and removed.
2. **Given** cleanup fails for any container, **When** processing starts, **Then** the failure is reported with an actionable message.
3. **Given** cleanup fails after a retry, **When** processing is about to start, **Then** the operator is prompted in the CLI to confirm whether to proceed.

---

[Add more user stories as needed, each with an assigned priority]

### Edge Cases

- No mdify-managed containers exist on the target machine.
- Some mdify-managed containers cannot be stopped or removed due to permissions or locks.
- Cleanup takes longer than expected because of a large number of mdify-managed containers.
- Remote connectivity drops during cleanup.
- Cleanup fails on first attempt but succeeds after a single retry.

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: System MUST detect all mdify-managed containers present on the target machine before data processing begins.
- **FR-002**: System MUST stop all running mdify-managed containers on the target machine before data processing begins.
- **FR-003**: System MUST remove all stopped mdify-managed containers on the target machine before data processing begins.
- **FR-004**: System MUST perform the cleanup on both local and remote target machines when processing is initiated for those targets.
- **FR-005**: System MUST provide a cleanup summary indicating counts of containers stopped and removed.
- **FR-006**: If any container cannot be stopped or removed, system MUST report the failure and the reason.
- **FR-007**: System MUST prevent data processing from starting until the cleanup completes, unless the operator explicitly confirms proceeding after a cleanup failure.
- **FR-008**: System MUST retry cleanup once before prompting for operator confirmation.
- **FR-009**: System MUST request operator confirmation via a CLI prompt before proceeding after a cleanup failure.

### Assumptions

- Operators intend to clean all mdify-managed containers on the target machine before processing.
- A cleanup failure requires operator confirmation before processing can proceed.

### Key Entities *(include if feature involves data)*

- **Cleanup Summary**: A record of how many containers were stopped and removed, plus any failures.
- **Cleanup Failure**: A record of a container that could not be stopped or removed, including a reason.
- **Managed Container Identifier**: Name prefixes `mdify-serve-`, `mdify-remote-`, and `mdify-`.

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 95% of processing runs complete cleanup and start processing without manual intervention.
- **SC-002**: Cleanup completes within 30 seconds for up to 50 containers on the target machine.
- **SC-003**: 90% of operators report that cleanup feedback is clear and sufficient to confirm actions.
- **SC-004**: Reduce processing failures attributed to leftover containers by 80% within one month of release.
