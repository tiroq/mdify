# Research: Automatic Container Cleanup

## Decision 1: Identify mdify-managed containers by name prefix

**Decision**: Use existing mdify container name prefixes (`mdify-serve-` for local, `mdify-remote-` / `mdify-` for remote) to discover managed containers.

**Rationale**: The current container lifecycle already generates names with these prefixes, enabling safe targeting without affecting unrelated containers. It avoids adding new label requirements or changing runtime behavior.

**Alternatives considered**:
- Docker/Podman labels (would require changes to existing start flows).
- Image-based matching (could unintentionally match unrelated containers using the same base image).

## Decision 2: Cleanup sequence uses stop → remove

**Decision**: Stop running containers first, then remove stopped containers, with a single retry on failure.

**Rationale**: Aligns with current container lifecycle and avoids abrupt deletion while providing a deterministic, repeatable process. Retry accounts for transient runtime errors.

**Alternatives considered**:
- Force remove only (`rm -f`) without stop (more aggressive, less clear feedback).
- Bulk prune operations (risk of affecting unrelated resources).

## Decision 3: Confirmation via CLI prompt after retry

**Decision**: If cleanup fails after one retry, prompt via CLI confirmation to proceed or abort.

**Rationale**: Balances safety with operator control, aligns with existing CLI confirmation patterns for warnings.

**Alternatives considered**:
- Hard fail without confirmation (too restrictive for operators).
- Always proceed (unsafe by default).
