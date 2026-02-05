# Quickstart: Automatic Container Cleanup

## Goal
Ensure mdify-managed containers are stopped and removed before conversion starts, locally or remotely.

## Local usage
Run normal conversions; cleanup runs automatically before container start.

- Example: `mdify document.pdf`

If cleanup fails after one retry, mdify prompts for confirmation to proceed.

## Remote usage (SSH)
Cleanup runs on the remote host before the remote container starts.

- Example: `mdify document.pdf --remote-host production`

## Expected behavior
- Detect mdify-managed containers.
- Stop running containers.
- Remove stopped containers.
- Retry once on failure.
- Prompt in CLI if cleanup still fails.
