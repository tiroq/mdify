# Debugging Results - mdify Container Crashes

## Problem Summary
The docling-serve container crashes when processing certain PDF files (e.g., `TradeAcceptUserManual.pdf`), causing connection errors.

## Root Cause Analysis

### What We Found
1. **Server starts successfully** - Container boots, health checks pass
2. **Crashes during PDF processing** - Connection aborted after ~1 second
3. **No error message in logs** - Server dies silently
4. **Pattern**: Larger/complex PDFs trigger the crash more frequently

### Container Logs (from crash)
```
Starting production server 🚀
Server started at http://0.0.0.0:5001
INFO:     Started server process [1]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:5001
INFO:     192.168.64.1:55974 - "GET /health HTTP/1.1" 200 OK
[Then: Connection Aborted - No error message]
```

### Most Likely Cause: **Out of Memory (OOM)**

When a container exceeds its memory limit, the OS kernel kills it silently without logging an error. This matches our symptoms:
- Silent crash during processing
- No error in container logs  
- Happens more with larger PDFs
- Connection aborted mid-request

## Solutions

### Option 1: Increase Container Memory (Recommended)
Add memory limits to the container startup in `mdify/container.py`:

```python
cmd = [
    self.runtime,
    "run",
    "-d",
    "--name", self.container_name,
    "-p", f"{self.port}:5001",
    "-m", "4g",  # 4GB memory limit
    "-e", f"DOCLING_SERVE_MAX_SYNC_WAIT={self.timeout}",
    self.image,
]
```

### Option 2: Skip Problematic Files
Add a `--skip-on-error` flag to continue processing other files when one crashes:

```python
if not container_alive:
    if args.skip_on_error:
        print("    Skipping file and continuing...", file=sys.stderr)
        # Restart container
        container.stop()
        container.start()
        continue
    else:
        print("    Stopping remaining conversions", file=sys.stderr)
        break
```

### Option 3: Use Docker/Podman Instead
Apple Container is very new (macOS 26+). Try with Docker or Podman which have more mature memory management:

```bash
export MDIFY_CONTAINER_RUNTIME=podman
mdify docs -o parsed
```

## Files That Crash The Server
Based on testing:
- `TradeAcceptUserManual.pdf` (972 KB) - Crashes consistently  
- `pfmi-disclosure-framework.pdf` (1.4 MB) - Crashes consistently
- Larger PDFs (3.6 MB+) - Crash on first attempt

## Files That Work
- `clearstar-program-consultation-paper...pdf` (780 KB) - Processes successfully
- Smaller PDFs - Generally work

## Debugging Tools Added

### 1. Container Log Retrieval
```bash
MDIFY_DEBUG=1 mdify docs -o parsed
```
Now shows last 50 lines of container logs on crash.

### 2. Container Health Checks
Detects if container crashed vs. temporary connection issue.

### 3. Apple Container Support
Fixed log retrieval for Apple Container (uses `-n` not `--tail`).

## Next Steps

1. **Add memory limit support** to container configuration
2. **Add --skip-on-error flag** for batch processing resilience
3. **Test with Docker/Podman** to compare stability
4. **Report to docling-serve project** - The server should handle large PDFs gracefully or return proper errors instead of crashing

## Technical Details

### Code Changes Made
- [mdify/cli.py](mdify/cli.py#L1010-L1050): Added connection error detection and log retrieval
- [mdify/container.py](mdify/container.py#L138-L165): Added `get_logs()` with Apple Container support
- [mdify/container.py](mdify/container.py#L167-L181): Added `is_running()` to detect container crashes
- [mdify/cli.py](mdify/cli.py#L37): Added `MDIFY_DEBUG` environment variable

### Apple Container Differences
- Logs: Uses `container logs -n N` instead of `container logs --tail N`
- Commands: Space-separated (`image pull`) not dash (`image-pull`)
- Storage: `~/Library/Application Support/com.apple.container/`
- Daemon: Check via `container system status`
