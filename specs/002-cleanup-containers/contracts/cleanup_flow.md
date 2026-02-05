# Contract: Cleanup Flow

## Trigger
Cleanup runs immediately before container start for both local and remote processing.

## Inputs
- Target scope: local or remote
- Container runtime: detected or specified
- Managed container identifiers: name prefixes

## Behavior
1. Discover mdify-managed containers by name prefix.
2. Stop running containers.
3. Remove stopped containers.
4. Retry once if any stop/remove operation fails.
5. If failures remain, prompt operator in CLI to confirm whether to proceed.
6. Emit a summary with stopped/removed counts and failure details.

## Success Criteria
- Processing does not start until cleanup completes or operator confirms after failure.
- Only mdify-managed containers are affected.
- CLI output provides actionable failures.
