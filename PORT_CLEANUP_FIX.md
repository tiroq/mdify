# Port Cleanup Fix for Remote Container Startup

## Problem
When running mdify with remote server execution, if a previous container wasn't properly cleaned up or if a container crash occurred, the next execution would fail with:

```
Container start failed: docker: Error response from daemon: failed to set up container networking: 
driver failed programming external connectivity on endpoint mdify-remote-XXXX: 
Bind for 0.0.0.0:5001 failed: port is already allocated
```

## Root Cause
The remote container startup code didn't check for or clean up existing containers using the target port before attempting to start a new one. This could happen if:
- A previous mdify session crashed without properly stopping the container
- Multiple mdify instances were run with the same port
- The container stop/cleanup failed silently but the container remained running

## Solution
Added automatic port cleanup logic to `RemoteContainer.start()` via a new `_cleanup_port()` method:

### Implementation Details

**File**: [mdify/ssh/remote_container.py](mdify/ssh/remote_container.py)

**New Method**: `_cleanup_port()`
- Executes `docker/podman ps -a --filter 'publish={port}'` to find containers bound to the target port
- Stops any existing containers using that port
- Removes the stopped containers
- Non-blocking: If cleanup fails, logs it as debug and continues with container startup

**Modified Method**: `start()`
- Now calls `await self._cleanup_port()` at the beginning
- Ensures any stale containers are cleaned up before attempting to start a new one
- Updated docstring to reflect the new cleanup step

### Testing
✅ Verified with batch file conversion (4 files)
✅ Verified with multiple consecutive runs on same port
✅ Confirmed no regressions in:
- Single file conversion
- Multi-file batch processing
- Container health checks
- Remote resource validation

## Impact
- **Fixes**: Port allocation errors during batch processing
- **Improves**: Resilience to crashed/orphaned containers
- **Non-breaking**: Existing functionality unchanged
- **Safe**: Cleanup is non-blocking; failures don't prevent container startup
