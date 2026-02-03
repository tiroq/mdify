# Implementation Plan: SSH Remote Server Support

**Branch**: `001-ssh-remote-server-support` | **Date**: 2026-02-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-ssh-remote-server-support/spec.md`

## Summary

Enable mdify to manage docling containers and process documents on remote servers via SSH. Users can offload resource-intensive document conversion to remote machines while keeping the CLI lightweight and local. The implementation uses **asyncssh** for pure-Python async SSH operations with minimal external dependencies, maintaining a persistent connection throughout the session with automatic reconnect handling.

## Technical Context

**Language/Version**: Python 3.8+ (same as mdify core)  
**Primary Dependencies**: 
- `asyncssh` - Pure-Python async SSH2 protocol implementation (new)
- `requests` - HTTP client for local->remote API calls (existing)
- `pyyaml` - Config file parsing for `~/.mdify/remote.conf` (new)

**Storage**: 
- Local: `~/.mdify/remote.conf` (YAML config), `~/.mdify/known_hosts` (SSH fingerprints)
- Remote: `/tmp/mdify-<session-id>/` (temporary files, auto-cleaned)

**Testing**: pytest with `unittest.mock` + `asynctest` for async mocking  
**Target Platform**: macOS/Linux (local client), Linux (remote servers)  
**Project Type**: Single CLI application with new remote execution modules  
**Performance Goals**: 
- File transfer: >5 MB/s on typical networks
- Connection overhead: <2s for initial SSH handshake
- Container startup: <30s on remote server

**Constraints**: 
- Maintain CLI lightweight: Only add asyncssh + pyyaml dependencies
- No password auth (security): SSH keys only
- Sequential transfers (simplicity): No concurrent file operations
- Single persistent connection (performance): Reuse across all operations

**Scale/Scope**: 
- Support single remote server per session
- Handle files up to 10GB (with progress feedback)
- Manage queue of 1-1000 files per batch

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### ✅ I. Lightweight CLI, Heavy Container

- **Status**: PASS
- **Compliance**: Adding only `asyncssh` and `pyyaml` dependencies. No ML libraries.
- **Rationale**: Remote execution still delegates to containerized docling-serve on remote host.

### ✅ II. Container Runtime Abstraction

- **Status**: PASS
- **Compliance**: Remote runtime detection uses same priority as local (docker/podman/orbstack/colima/container).
- **Rationale**: Extends existing `detect_runtime()` logic to work over SSH connection.

### ✅ III. Defensive Resource Management

- **Status**: PASS
- **Compliance**: Validates remote server memory/disk before starting container.
- **Rationale**: Same resource profiles (minimal/default/heavy) applied to remote containers.

### ✅ IV. Graceful Error Handling

- **Status**: PASS
- **Compliance**: 3-retry logic for SSH failures, automatic cleanup on interrupt, container crash detection.
- **Rationale**: Extends existing error handling patterns to remote scenarios.

### ✅ V. Test-First Development

- **Status**: PASS
- **Compliance**: Will add `tests/test_ssh_client.py` and `tests/test_remote_container.py` with async mocks.
- **Rationale**: Follows existing pytest + mock pattern, extends to async operations.

### ✅ VI. Clean Module Separation

- **Status**: PASS
- **Compliance**: New modules (`ssh_client.py`, `remote_container.py`) follow existing separation pattern.
- **Rationale**: CLI orchestration remains in `cli.py`, SSH logic isolated, container logic extends base class.

**Constitution Gate**: ✅ PASS - All principles upheld. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-ssh-remote-server-support/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
mdify/
├── __init__.py                 # Existing
├── __main__.py                 # Existing
├── cli.py                      # MODIFIED: Add SSH args, remote orchestration
├── container.py                # Existing: Base container lifecycle
├── docling_client.py           # Existing: HTTP client for docling-serve
├── ssh_client.py               # NEW: SSH connection, file transfer, remote execution
├── remote_container.py         # NEW: Remote container lifecycle (extends container.py)
└── config.py                   # NEW: Config file parsing for ~/.mdify/remote.conf

tests/
├── __init__.py
├── test_cli.py                 # MODIFIED: Add SSH argument tests
├── test_container.py           # Existing
├── test_docling_client.py      # Existing
├── test_ssh_client.py          # NEW: SSH client tests with async mocks
├── test_remote_container.py    # NEW: Remote container tests
└── test_config.py              # NEW: Config parsing tests

# User configuration files (created at runtime)
~/.mdify/
├── remote.conf                 # Optional: SSH server profiles
├── known_hosts                 # SSH fingerprints
└── .last_check                 # Existing: Update check timestamp
```

**Structure Decision**: Single project structure. New modules follow existing patterns - `ssh_client.py` handles SSH operations similar to how `docling_client.py` handles HTTP. `remote_container.py` extends `container.py` base class for remote operations.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**No violations detected.** All constitution principles are upheld by this feature.

---

## Phase 0: Research & Technology Validation

**Goal**: Resolve NEEDS CLARIFICATION items and validate asyncssh for production use.

### Research Tasks

#### R1: asyncssh Production Readiness
- [ ] Verify asyncssh supports Python 3.8-3.12
- [ ] Review asyncssh security audit status and CVE history
- [ ] Benchmark asyncssh performance vs paramiko for file transfers
- [ ] Validate asyncssh ProxyJump support and SSH config parsing
- [ ] Test asyncssh reconnection handling for dropped connections

**Output**: Document asyncssh production viability, performance benchmarks, and any gotchas.

#### R2: SSH Config Parsing Strategy
- [ ] Research how asyncssh parses `~/.ssh/config` (auto or manual)
- [ ] Determine if we need custom parser or can use asyncssh built-in
- [ ] Document precedence: CLI flags > `~/.mdify/remote.conf` > `~/.ssh/config`
- [ ] Identify edge cases (Include directives, Match blocks, wildcards)

**Output**: Config loading strategy and precedence rules.

#### R3: File Transfer Progress Implementation
- [ ] Research asyncssh SFTP progress callback mechanism
- [ ] Evaluate progress bar libraries compatible with mdify (tqdm vs custom)
- [ ] Determine how to calculate transfer speed and ETA
- [ ] Plan debug mode chunk-by-chunk logging approach

**Output**: Progress UI design and implementation approach.

#### R4: Container Runtime Detection Over SSH
- [ ] Test executing `which docker/podman` over asyncssh connection
- [ ] Verify `docker ps` and `podman ps` work over SSH
- [ ] Document how to detect Apple Container on remote macOS systems
- [ ] Plan fallback when multiple runtimes detected on remote

**Output**: Remote runtime detection algorithm.

#### R5: Resource Validation on Remote Server
- [ ] Determine commands to check remote disk space (`df`)
- [ ] Determine commands to check remote memory (Linux `/proc/meminfo`, macOS `vm_stat`)
- [ ] Plan how to execute validation before file transfer
- [ ] Document error messages when resources insufficient

**Output**: Remote resource validation checklist.

**Deliverable**: `research.md` documenting all findings and decisions.

---

## Phase 1: Design & Contracts

**Goal**: Define data models, API contracts, and module interfaces.

### 1.1 Data Model

**File**: `data-model.md`

#### SSH Connection Configuration

```python
@dataclass
class SSHConfig:
    """SSH connection parameters."""
    host: str
    user: str
    port: int = 22
    key_path: Optional[Path] = None
    proxy_jump: Optional[str] = None
    
    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> 'SSHConfig':
        """Build from CLI arguments."""
        
    @classmethod
    def from_ssh_config(cls, host_name: str) -> 'SSHConfig':
        """Load from ~/.ssh/config."""
        
    @classmethod
    def from_remote_conf(cls, profile: str) -> 'SSHConfig':
        """Load from ~/.mdify/remote.conf."""
```

#### File Transfer Session

```python
@dataclass
class TransferSession:
    """Tracks file transfer state."""
    session_id: str  # UUID for remote temp directory
    files_remaining: List[Path]
    files_completed: List[Path]
    files_failed: List[Path]
    remote_temp_dir: Path  # /tmp/mdify-<session_id>/
    
    def is_complete(self) -> bool:
        """Check if all files processed."""
        return len(self.files_remaining) == 0
```

#### Remote Container State

```python
@dataclass  
class RemoteContainerState:
    """Remote container lifecycle state."""
    container_id: Optional[str]
    is_running: bool
    is_healthy: bool
    port: int
    resource_profile: str  # 'minimal', 'default', or 'heavy'
```

### 1.2 Module Interfaces

**File**: `contracts/ssh_client.py`

```python
class SSHClient:
    """Async SSH connection manager with persistent connection."""
    
    async def connect(self, config: SSHConfig) -> None:
        """Establish SSH connection with retry logic."""
        
    async def disconnect(self) -> None:
        """Close SSH connection gracefully."""
        
    async def execute(self, command: str) -> Tuple[str, str, int]:
        """Execute command on remote server.
        
        Returns:
            (stdout, stderr, exit_code)
        """
        
    async def upload_file(
        self, 
        local_path: Path, 
        remote_path: Path,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """Upload file to remote server with progress."""
        
    async def download_file(
        self,
        remote_path: Path,
        local_path: Path,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """Download file from remote server with progress."""
        
    async def check_resources(
        self, 
        required_memory_gb: float,
        required_disk_gb: float
    ) -> Tuple[bool, str]:
        """Validate remote server has sufficient resources.
        
        Returns:
            (is_sufficient, error_message)
        """
```

**File**: `contracts/remote_container.py`

```python
class RemoteContainer(DoclingContainer):
    """Extends DoclingContainer for remote execution via SSH."""
    
    def __init__(
        self,
        ssh_client: SSHClient,
        runtime: str,
        image: str,
        port: int = 5001,
        **kwargs
    ):
        """Initialize remote container manager."""
        
    async def start(self, timeout: int = 120) -> None:
        """Start container on remote server."""
        
    async def stop(self) -> None:
        """Stop container on remote server."""
        
    async def is_healthy(self) -> bool:
        """Check if remote container is healthy."""
        
    async def get_logs(self, tail: int = 50) -> Tuple[str, str]:
        """Retrieve container logs from remote server."""
```

### 1.3 CLI Integration

**File**: `contracts/cli_integration.md`

#### New CLI Arguments

Added to `parse_args()`:

```python
# SSH connection group
ssh_group = parser.add_argument_group('SSH Remote Server Options')
ssh_group.add_argument('--ssh-host', type=str, help='Remote server hostname')
ssh_group.add_argument('--ssh-user', type=str, help='SSH username')
ssh_group.add_argument('--ssh-port', type=int, default=22, help='SSH port')
ssh_group.add_argument('--ssh-key', type=Path, help='SSH private key path')
ssh_group.add_argument('--ssh-config-host', type=str, help='Use ~/.ssh/config host')
ssh_group.add_argument('--ssh-proxy-jump', type=str, help='ProxyJump bastion host')
ssh_group.add_argument('--keep-remote-container', action='store_true', 
                      help='Keep container running after processing')
ssh_group.add_argument('--keep-remote-files', action='store_true',
                      help='Keep temp files on remote server')
```

#### Main Execution Flow

```python
async def main_async(args: argparse.Namespace) -> int:
    """Async entry point when using SSH remote mode."""
    
    # 1. Build SSH config from args/files
    ssh_config = build_ssh_config(args)
    
    # 2. Establish persistent SSH connection
    async with SSHClient() as ssh:
        await ssh.connect(ssh_config)
        
        # 3. Detect remote runtime
        runtime = await detect_remote_runtime(ssh)
        
        # 4. Validate remote resources
        is_sufficient, error = await ssh.check_resources(...)
        if not is_sufficient:
            print(error, file=sys.stderr)
            return 1
        
        # 5. Create transfer session
        session = TransferSession(...)
        
        # 6. Start remote container
        async with RemoteContainer(ssh, runtime, image) as container:
            # 7. Process files sequentially
            for file in files_to_convert:
                await process_remote_file(ssh, container, file, session)
                
        # 8. Cleanup (unless --keep-remote-* flags)
        if not args.keep_remote_files:
            await ssh.execute(f"rm -rf {session.remote_temp_dir}")
    
    return 0

def main() -> int:
    """Entry point - delegates to async if SSH mode."""
    args = parse_args()
    
    # Detect if using remote mode
    if is_remote_mode(args):
        return asyncio.run(main_async(args))
    else:
        # Existing local mode (synchronous)
        return main_sync(args)
```

### 1.4 Configuration File Format

**File**: `contracts/remote_conf_schema.yaml`

```yaml
# ~/.mdify/remote.conf
version: 1

# Default SSH settings
ssh:
  user: deploy
  port: 22
  key: ~/.ssh/id_rsa

# Named profiles
profiles:
  production:
    host: prod.example.com
    user: prod-user
    key: ~/.ssh/prod_key
    
  staging:
    host: staging.example.com
    user: staging-user
    # Inherits port and key from default ssh section
    
  bastion:
    host: internal.example.com
    proxy_jump: bastion.example.com
    
  # Use with: mdify file.pdf --ssh-config-host production
```

**Deliverable**: `data-model.md`, `contracts/`, `quickstart.md`

---

## Phase 2: Implementation Phases

**Note**: Actual implementation tasks created via `/speckit.tasks` command.

### Implementation Sequence

#### Phase 2.1: SSH Client Foundation
1. Implement `SSHClient` class with asyncssh
2. Add SSH config parsing (CLI > remote.conf > ~/.ssh/config)
3. Implement persistent connection with reconnect logic
4. Add unit tests for SSH client with async mocks

**Acceptance**: Can establish SSH connection and execute remote commands.

#### Phase 2.2: File Transfer
1. Implement file upload with progress tracking
2. Implement file download with progress tracking
3. Add compression for files >1MB
4. Add checksum verification
5. Add unit tests for file transfer operations

**Acceptance**: Can transfer files bidirectionally with progress display.

#### Phase 2.3: Remote Container Management
1. Extend `DoclingContainer` to `RemoteContainer`
2. Implement remote runtime detection
3. Implement remote resource validation
4. Implement remote container start/stop/health
5. Add unit tests for remote container lifecycle

**Acceptance**: Can start/stop containers on remote server.

#### Phase 2.4: CLI Integration
1. Add SSH argument parsing to `cli.py`
2. Implement async orchestration flow
3. Add queue-aware container cleanup logic
4. Implement cleanup on interrupt (Ctrl+C)
5. Add integration tests for end-to-end remote workflow

**Acceptance**: Can convert documents on remote server via CLI.

#### Phase 2.5: Error Handling & Polish
1. Implement retry logic for SSH connection failures
2. Add detailed error messages for common issues
3. Implement debug mode verbose logging
4. Add edge case handling (see spec)
5. Update documentation and README

**Acceptance**: All error scenarios handled gracefully with actionable messages.

---

## Success Criteria

From spec.md:

1. ✅ User can convert a document on a remote server using `mdify document.pdf --ssh-host server.com`
2. ✅ Files are successfully transferred to/from remote server
3. ✅ Remote container is managed automatically (start/stop/health)
4. ✅ SSH config integration works correctly
5. ✅ Cleanup happens reliably on both success and failure
6. ✅ All existing local conversion functionality remains unchanged

## Open Questions for Implementation

1. Should we cache remote runtime detection result across sessions?
2. How to handle remote server timezone differences for temp directory cleanup?
3. Should we support resuming interrupted multi-file batches across CLI invocations?
4. What's the minimum asyncssh version we should target?

---

**Next Steps**: 
1. Run `/speckit.plan` research phase to fill `research.md`
2. After research complete, create `data-model.md` and `contracts/`
3. Run `/speckit.tasks` to generate implementation tasks from Phase 2
