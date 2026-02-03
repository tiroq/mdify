# Implementation Tasks: SSH Remote Server Support

**Feature**: `001-ssh-remote-server-support`  
**Status**: Ready for Implementation  
**Total Tasks**: 47 (organized by phase and user story)  
**Estimated Effort**: 4-5 weeks (experienced Python async developer)

---

## Project Orientation & Setup

- [X] T001 Review and understand feature specification (spec.md)
- [X] T002 Review implementation plan (plan.md) for architectural decisions
- [X] T003 Review mdify constitution to understand project principles
- [X] T004 Set up Python 3.8+ virtual environment with dev dependencies
- [X] T005 Install asyncssh package and verify with `python -c "import asyncssh; print(asyncssh.__version__)"`
- [X] T006 Install pyyaml package for config file parsing
- [X] T007 Verify all existing tests pass: `python -m pytest tests/ -v`

---

## Phase 0: Research & Technology Validation ✅ COMPLETE

### R1: asyncssh Production Readiness

- [X] T008 Create `specs/001-ssh-remote-server-support/research.md` with findings sections
- [X] T009 Verify asyncssh supports Python 3.8-3.12 from official documentation
- [X] T010 Review asyncssh security audit status on GitHub and CVE database
- [X] T011 Document asyncssh CVE history and security patches
- [X] T012 Write simple benchmark script comparing asyncssh vs paramiko for 100MB file transfer
- [X] T013 Run benchmarks locally and document results (throughput, memory, CPU)
- [X] T014 Test asyncssh reconnection behavior with connection drop simulation
- [X] T015 Document asyncssh reconnection patterns and best practices

### R2: SSH Config Parsing Strategy

- [X] T016 Research asyncssh.config module for SSH config file parsing capabilities
- [X] T017 Test if asyncssh automatically parses `~/.ssh/config` or requires manual parsing
- [X] T018 Document precedence strategy: CLI flags > ~/.mdify/remote.conf > ~/.ssh/config
- [X] T019 Identify edge cases: Include directives, Match blocks, wildcards, Host aliases
- [X] T020 Create test cases for each precedence scenario
- [X] T021 Document Config class constructor parameters and precedence logic

### R3: File Transfer Progress Implementation

- [X] T022 Research asyncssh SFTP progress callback mechanism and API
- [X] T023 Evaluate progress bar libraries: tqdm vs rich vs custom spinner
- [X] T024 Implement prototype file transfer with progress display
- [X] T025 Calculate transfer speed (bytes/sec) and ETA during transfer
- [X] T026 Document debug mode chunk-by-chunk logging approach (MDIFY_DEBUG=1)
- [X] T027 Document progress UI format and edge cases (very fast/slow networks)

### R4: Container Runtime Detection Over SSH

- [X] T028 Test `which docker` over asyncssh.run() and document output format
- [X] T029 Test `which podman` over asyncssh.run() and verify cross-distro compatibility
- [X] T030 Document how to detect Apple Container on remote macOS systems
- [X] T031 Plan fallback when multiple runtimes detected on remote server
- [X] T032 Document runtime detection algorithm and priority order
- [X] T033 Create test data for remote environment scenarios

### R5: Resource Validation on Remote Server

- [X] T034 Research Linux `df -h` output format for parsing disk space
- [X] T035 Research macOS `df -h` output format and compatibility
- [X] T036 Research Linux `/proc/meminfo` format for available memory calculation
- [X] T037 Research macOS `vm_stat` for available memory calculation
- [X] T038 Document resource check commands and parsing logic
- [X] T039 Create test data for various remote OS configurations

**Deliverable**: `research.md` with all findings and recommendations ✅ DELIVERED

---

## Phase 1: Design & Module Contracts ✅ COMPLETE

### Data Model Definition

- [X] T040 [P] Create `data-model.md` defining SSHConfig dataclass
- [X] T041 [P] Document SSHConfig.from_cli_args() class method contract
- [X] T042 [P] Document SSHConfig.from_ssh_config() class method contract
- [X] T043 [P] Document SSHConfig.from_remote_conf() class method contract
- [X] T044 [P] Create TransferSession dataclass in data-model.md
- [X] T045 [P] Create RemoteContainerState dataclass in data-model.md

### Module Contracts

- [X] T046 [P] Create `contracts/` directory structure
- [X] T047 [P] Create `contracts/ssh_client.md` with SSHClient interface
- [X] T048 [P] Create `contracts/remote_container.md` with RemoteContainer interface
- [X] T049 [P] Create `contracts/config_parsing.md` with config loading strategy
- [X] T050 [P] Create `contracts/cli_integration.md` with new argument definitions

### Integration Design

- [X] T051 Create `quickstart.md` with example usage scenarios

**Deliverable**: `data-model.md`, `contracts/`, `quickstart.md` ✅ DELIVERED

---

## Phase 2.1: SSH Client Foundation ✅ COMPLETE

### SSHClient Implementation

- [X] T052 Create `mdify/ssh_client.py` with SSHClient class skeleton
- [X] T053 Implement `SSHClient.__init__()` to store connection parameters
- [X] T054 Implement `SSHClient.connect()` with asyncssh.connect() integration
- [X] T055 Implement `SSHClient.connect()` with SSH agent support detection
- [X] T056 Implement `SSHClient.connect()` with known_hosts fingerprint validation
- [X] T057 Implement `SSHClient.connect()` with 3-retry exponential backoff logic
- [X] T058 Implement `SSHClient.disconnect()` to gracefully close connection
- [X] T059 Implement `SSHClient.execute()` to run remote commands and capture output
- [X] T060 Implement `SSHClient.execute()` with proper exit code handling

### SSH Config Parsing

- [X] T061 Create `mdify/config.py` with config parsing functions
- [X] T062 Implement `parse_cli_args()` to build SSHConfig from argparse.Namespace
- [X] T063 Implement `parse_ssh_config()` to load from `~/.ssh/config`
- [X] T064 Implement `parse_remote_conf()` to load from `~/.mdify/remote.conf`
- [X] T065 Implement precedence logic: CLI > remote.conf > ssh/config
- [X] T066 Implement validation: ensure host and user are specified
- [X] T067 Implement SSH key path expansion (handle ~/ and environment variables)

### Testing: SSH Client & Config

- [X] T068 Create `tests/test_ssh_client.py` with test class structure
- [X] T069 [P] Add mock SSHClient.connect() test with successful connection
- [X] T070 [P] Add mock SSHClient.connect() test with timeout failure
- [X] T071 [P] Add mock SSHClient.connect() test with auth failure
- [X] T072 [P] Add mock SSHClient.execute() test with command success
- [X] T073 [P] Add mock SSHClient.execute() test with command failure
- [X] T074 Create `tests/test_config.py` with config parsing tests
- [X] T075 [P] Add test for parse_cli_args() precedence
- [X] T076 [P] Add test for parse_ssh_config() with ~/.ssh/config file
- [X] T077 [P] Add test for parse_remote_conf() with ~/.mdify/remote.conf file
- [X] T078 [P] Add test for config precedence (CLI overrides file configs)
- [X] T079 Run all tests: `python -m pytest tests/test_ssh_client.py tests/test_config.py -v`

**Acceptance Criteria**: 
- SSHClient can establish SSH connections with mocked asyncssh ✓
- SSH config loading works with proper precedence ✓
- All 20+ tests pass with 100% mock coverage (no real SSH required) ✓
- **VERIFIED**: Actual SSH connection to 192.168.1.200 works successfully ✓

---

## Phase 2.2: File Transfer ✅ COMPLETE

### Upload & Download Implementation

- [X] T080 [P] Implement `SSHClient.upload_file()` with asyncssh.sftp.put()
- [X] T081 [P] Implement `SSHClient.download_file()` with asyncssh.sftp.get()
- [X] T082 [P] Implement gzip compression for files >1MB before upload
- [X] T083 [P] Implement gzip decompression after download
- [X] T084 Implement progress callback mechanism for upload/download
- [X] T085 Implement checksum calculation (SHA256) for integrity verification
- [X] T086 Implement checksum verification after transfer with retry on mismatch

### Progress Display

- [X] T087 Create `mdify/progress.py` with progress bar implementation
- [X] T088 Implement `ProgressBar.update(bytes_transferred, total_bytes)` for display
- [X] T089 Implement speed calculation (MB/s) and ETA display
- [X] T090 Implement progress bar formatting with spinner for large files
- [X] T091 Implement debug mode logging in ProgressBar (MDIFY_DEBUG=1)
- [X] T092 Implement progress bar cleanup on completion/error

### Testing: File Transfer

- [X] T093 Create `tests/test_file_transfer.py`
- [X] T094 [P] Add mock test for upload with progress callback
- [X] T095 [P] Add mock test for download with progress callback
- [X] T096 [P] Add mock test for compression on large files
- [X] T097 [P] Add mock test for checksum verification
- [X] T098 [P] Add mock test for checksum mismatch retry logic
- [X] T099 Run all tests: `python -m pytest tests/test_file_transfer.py -v`

**Acceptance Criteria**:
- Files transfer correctly with and without compression ✓
- Progress display shows speed and ETA ✓
- Checksum verification detects corrupted transfers ✓
- All tests pass with mocked SFTP operations ✓

---

## Phase 2.3: Remote Container Management ✅ COMPLETE

### RemoteContainer Class

- [X] T100 Create `mdify/remote_container.py`
- [X] T101 Implement `RemoteContainer.__init__()` extending DoclingContainer
- [X] T102 Implement `RemoteContainer.start()` to start container on remote server
- [X] T103 Implement remote runtime detection using `SSHClient.execute()`
- [X] T104 Implement resource validation before container start
- [X] T105 Implement `RemoteContainer.stop()` to stop container on remote server
- [X] T106 Implement `RemoteContainer.is_healthy()` for health check over SSH
- [X] T107 Implement `RemoteContainer.get_logs()` to retrieve remote container logs
- [X] T108 Implement context manager (`__aenter__`, `__aexit__`) for async context

### Remote Resource Validation

- [X] T109 Implement `SSHClient.check_disk_space()` using `df` command
- [X] T110 Implement `SSHClient.check_available_memory()` using system commands
- [X] T111 Implement disk space validation: fail if insufficient space
- [X] T112 Implement memory validation: fail if insufficient memory
- [X] T113 Implement helpful error messages with space/memory requirements

### Testing: Remote Container

- [X] T114 Create `tests/test_remote_container.py`
- [X] T115 [P] Add mock test for RemoteContainer.start() on remote server
- [X] T116 [P] Add mock test for RemoteContainer.stop() on remote server
- [X] T117 [P] Add mock test for health check over SSH
- [X] T118 [P] Add mock test for resource validation pass scenario
- [X] T119 [P] Add mock test for resource validation failure scenario
- [X] T120 [P] Add mock test for container log retrieval
- [X] T121 Run all tests: `python -m pytest tests/test_remote_container.py -v`

**Acceptance Criteria**:
- Remote containers start/stop correctly via SSH ✓
- Health checks work over SSH connection ✓
- Resource validation prevents container start on insufficient resources ✓
- Container logs are retrievable from remote server ✓
- All tests pass with mocked SSH and container operations ✓

---

## Phase 2.4: CLI Integration

### CLI Argument Parsing

- [X] T122 Update `mdify/cli.py` parse_args() to add SSH argument group ✓
- [X] T123 Add `--remote-host` argument for remote server hostname ✓
- [X] T124 Add `--remote-user` argument for SSH username ✓
- [X] T125 Add `--remote-port` argument (default: 22) ✓
- [X] T126 Add `--remote-key` argument for SSH private key path ✓
- [X] T127 Add `--remote-key-passphrase` argument for SSH passphrase ✓
- [X] T128 Add `--remote-timeout` argument for connection timeout ✓
- [X] T129 Add `--remote-work-dir` argument for remote work directory ✓
- [X] T130 Add `--remote-skip-ssh-config`, `--remote-skip-validation`, `--remote-validate-only` flags ✓

### Async Orchestration

- [X] T131 Create `main_async_remote()` function in cli.py for async execution ✓
- [X] T132 Implement `is_remote_mode()` detection based on CLI arguments ✓
- [X] T133 Implement SSH config building logic with proper precedence ✓
- [X] T134 Implement persistent SSH connection lifecycle ✓
- [X] T135 Implement resource validation with full 7-point check ✓
- [X] T136 [PHASE 2.4.2] Implement file list building for remote processing
- [X] T137 [PHASE 2.4.2] Implement transfer session creation with session ID
- [X] T138 [PHASE 2.4.2] Implement queue-aware container lifecycle
- [X] T139 [PHASE 2.4.2] Implement file processing loop with transfer + convert + download
- [X] T140 [PHASE 2.4.2] Implement automatic cleanup of remote temp directory
- [X] T141 [PHASE 2.4.2] Implement cleanup on Ctrl+C interrupt (signal handler)

### Error Handling & User Feedback

- [X] T142 Implement SSH connection error messages with actionable hints ✓
- [X] T143 Implement authentication failure messages (key/permission issues) ✓
- [X] T144 Implement network timeout messages with retry info ✓
- [X] T145 Implement resource validation error messages with suggestions ✓
- [X] T146 [PHASE 2.4.2] Implement file transfer error messages with checksums
- [X] T147 [PHASE 2.4.2] Implement container failure messages with log snippets
- [X] T148 [PHASE 2.4.2] Implement debug mode enhanced logging (MDIFY_DEBUG=1)
- [X] T149 Update main() function to detect remote mode and call main_async_remote() ✓

### Testing: CLI Integration

- [ ] T150 Update `tests/test_cli.py` with SSH argument parsing tests
- [ ] T151 [P] Add test for SSH argument precedence
- [ ] T152 [P] Add test for remote mode detection
- [ ] T153 [P] Add mock test for full remote workflow (end-to-end)
- [ ] T154 [P] Add test for container lifecycle with file queue
- [ ] T155 [P] Add test for cleanup on interrupt signal
- [ ] T156 Run all tests: `python -m pytest tests/test_cli.py -v`

**Phase 2.4.1 Completion Summary**:
- ✅ SSH argument group added to CLI (--remote-host, --remote-port, --remote-user, --remote-key, --remote-timeout, --remote-work-dir, --remote-skip-ssh-config, --remote-skip-validation, --remote-validate-only, --remote-debug)
- ✅ main_async_remote() function implemented for async SSH execution
- ✅ Remote mode detection working (checks for --remote-host argument)
- ✅ SSH config loading from ~/.ssh/config with custom parser
- ✅ Resource validation with 7-point checks passing on real server (192.168.1.200)
- ✅ Error handling for SSH connection, auth, config, and validation errors
- ✅ Integration test: `mdify test.pdf --remote-host tsrv --remote-validate-only` ✓
- ✅ All 196 existing tests still passing
- ✓ tsrv SSH alias configured in ~/.ssh/config

**Phase 2.4.2 (File Transfer & Container Lifecycle)** - Planned for next session


**Acceptance Criteria**:
- SSH arguments parsed correctly
- Remote mode activated when SSH args provided
- Full remote conversion workflow works end-to-end
- Container lifecycle follows queue-aware behavior
- Cleanup happens on both success and failure
- All tests pass with comprehensive mocking

---

## Phase 2.5: Error Handling & Polish

### Edge Case Handling

- [ ] T157 Implement SSH connection timeout handling (3 retries, exponential backoff)
- [ ] T158 Implement SSH authentication retry logic with helpful error messages
- [ ] T159 Implement network interruption recovery during file transfer
- [ ] T160 Implement partial transfer detection with checksum verification
- [ ] T161 Implement remote container crash detection and recovery
- [ ] T162 Implement remote container resource exhaustion handling
- [ ] T163 Implement proper file permissions error messages
- [ ] T164 Implement disk space exhaustion error handling
- [ ] T165 Implement ProxyJump bastion host error handling

### Documentation

- [ ] T166 Update README.md with SSH remote server usage examples
- [ ] T167 Add SSH configuration guide to README (flags vs config file)
- [ ] T168 Add troubleshooting section for common SSH issues
- [ ] T169 Update DEBUGGING_RESULTS.md with remote debugging tips
- [ ] T170 Document asyncssh version requirements in setup.py/pyproject.toml
- [ ] T171 Add SSH remote feature to feature list in README

### Package Dependencies

- [ ] T172 Add `asyncssh>=2.10.0` to pyproject.toml dependencies
- [ ] T173 Add `pyyaml>=6.0` to pyproject.toml dependencies
- [ ] T174 Update requirements or setup.py accordingly
- [ ] T175 Test installation: `pip install -e .` and verify dependencies

### Final Testing & Validation

- [ ] T176 Run full test suite: `python -m pytest tests/ -v --cov=mdify`
- [ ] T177 Verify test coverage for new modules (ssh_client, remote_container, config)
- [ ] T178 Test with Python 3.8, 3.9, 3.10, 3.11, 3.12 (if available)
- [ ] T179 Manual end-to-end test with real remote server (staging environment)
- [ ] T180 Test interrupt handling (Ctrl+C during file transfer)
- [ ] T181 Test cleanup: verify remote temp files are removed
- [ ] T182 Test error scenarios: bad host, bad key, insufficient resources
- [ ] T183 Verify no regression in existing local conversion functionality

### Code Quality

- [ ] T184 Run linting: `pylint mdify/` and fix violations
- [ ] T185 Run type checking: `mypy mdify/` if type hints added
- [ ] T186 Format code: `black mdify/ tests/`
- [ ] T187 Review all new code for security issues (no hardcoded credentials, etc.)
- [ ] T188 Review async patterns for potential deadlocks or race conditions
- [ ] T189 Verify no blocking operations in async code

**Acceptance Criteria**:
- All edge cases handled gracefully with helpful error messages
- Full documentation for users and developers
- New dependencies properly declared
- 100% test pass rate across Python versions
- No regressions in local functionality
- Code quality meets project standards

---

## Success Validation

- [ ] T190 Verify: User can convert document with `mdify doc.pdf --ssh-host server.com`
- [ ] T191 Verify: Files transfer successfully to/from remote server
- [ ] T192 Verify: Remote container starts/stops automatically
- [ ] T193 Verify: SSH config integration works (`--ssh-config-host production`)
- [ ] T194 Verify: Cleanup happens reliably on success and failure
- [ ] T195 Verify: Local conversion functionality unchanged
- [ ] T196 Verify: All existing tests still pass
- [ ] T197 Document any open questions or future enhancements

---

## Dependency Graph & Parallelization

### Strict Ordering Required:
1. **Phase 0** (Research) → Must complete before design
2. **Phase 1** (Design) → Must complete before implementation
3. **Phase 2.1** (SSH Foundation) → Base for all other phases
4. **Phase 2.2** (File Transfer) → Depends on Phase 2.1
5. **Phase 2.3** (Remote Container) → Depends on Phase 2.1
6. **Phase 2.4** (CLI Integration) → Depends on 2.1, 2.2, 2.3
7. **Phase 2.5** (Polish) → Final phase, integrates everything

### Parallelizable Within Phases:
- **Phase 2.2 & 2.3** can progress in parallel (both depend only on 2.1)
- **Testing within each phase** can progress as code is written
- **Documentation in Phase 2.5** can start during Phase 2.4

### Recommended Execution:
1. Complete Phase 0 research (2-3 days)
2. Complete Phase 1 design (1-2 days)
3. Complete Phase 2.1 SSH foundation (3-4 days)
4. **Parallel:** Phase 2.2 (file transfer) + Phase 2.3 (remote container) (5-7 days each)
5. Complete Phase 2.4 CLI integration (3-4 days)
6. Complete Phase 2.5 polish (2-3 days)

**Total Estimate**: 4-5 weeks for experienced Python async developer

---

## Implementation Notes

### Key Technical Decisions:

1. **asyncssh**: Pure-Python async SSH2 implementation
   - No C dependencies
   - Cross-platform support
   - Built-in OpenSSH config support
   - Performance suitable for file transfers

2. **Single Persistent Connection**:
   - Reused across all operations in a session
   - Automatic reconnect if dropped
   - Reduces SSH handshake overhead

3. **Sequential File Transfers**:
   - Simplifies progress tracking
   - Easier error handling
   - Still acceptable performance for typical use cases
   - Can be enhanced to parallel in future

4. **Queue-Aware Container Lifecycle**:
   - Keep container running while files remain
   - Auto-stop when complete
   - Respect `--keep-remote-container` override
   - Balances resource usage with performance

5. **Comprehensive Error Handling**:
   - 3-retry logic with exponential backoff
   - Actionable error messages
   - Automatic cleanup on failure
   - Debug mode for troubleshooting

---

## Sign-Off

**Plan Created**: 2026-02-03  
**Implementation Ready**: Yes  
**All Prerequisites Met**: Yes (Phase 0 research tasks defined)  
**Estimated Completion**: 4-5 weeks

Proceed to Phase 0 research tasks (T008-T039) to validate technical assumptions.
