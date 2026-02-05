# Data Model: Automatic Container Cleanup

## CleanupSummary

**Purpose**: Track cleanup actions and outcomes for a single processing run.

**Fields**:
- `target`: `"local" | "remote"`
- `runtime`: `"docker" | "podman" | "container" | "orbstack" | "colima"` (string for detected runtime)
- `stopped_count`: integer
- `removed_count`: integer
- `failures`: list of CleanupFailure
- `retry_attempted`: boolean
- `proceeded_after_failure`: boolean

## CleanupFailure

**Purpose**: Represent a container that could not be stopped or removed.

**Fields**:
- `container_name`: string
- `action`: `"stop" | "remove"`
- `reason`: string
- `exit_code`: integer | null

## ManagedContainerIdentifier

**Purpose**: Criteria used to recognize mdify-managed containers.

**Fields**:
- `name_prefixes`: list of strings (e.g., `mdify-serve-`, `mdify-remote-`, `mdify-`)

## Relationships

- CleanupSummary contains zero or more CleanupFailure entries.
- ManagedContainerIdentifier informs container discovery for CleanupSummary.
