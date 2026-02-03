# Feature Specification: SSH Remote Server Support

## Overview

Enable mdify to manage docling containers and process documents on remote servers via SSH. This allows users to offload resource-intensive document conversion to remote machines while using the lightweight CLI locally.

## User Stories

### Primary Use Cases

1. **As a developer with a local laptop**, I want to process large documents on a remote server with more resources, so I can avoid overloading my local machine.

2. **As a team member**, I want to use a shared remote server for document conversion, so multiple users can leverage the same containerized environment without each maintaining their own.

3. **As a cloud user**, I want to specify my remote server via existing SSH config, so I don't need to repeatedly provide connection details.

4. **As a security-conscious user**, I want to use SSH key authentication, so my credentials remain secure.

## Functional Requirements

### Remote Server Configuration

- Support specifying remote server via CLI flags: `--ssh-host`, `--ssh-user`, `--ssh-port`, `--ssh-key`
- Support loading configuration from a dedicated config file (e.g., `~/.mdify/remote.conf`)
- Support using existing `~/.ssh/config` entries via `--ssh-config-host <name>`
- Default SSH port to 22 if not specified
- Support SSH key-based authentication (password auth not supported for security)

### Remote Container Management

- Detect container runtime on remote server (same priority as local: docker/podman/orbstack/colima/container)
- Start docling-serve container on remote server if not already running
- Reuse existing remote container if healthy
- Keep container running while files remain in the processing queue
- Stop and remove container automatically when all files are processed
- Support `--keep-remote-container` flag to override automatic cleanup (leaves container running)
- Support same resource profiles (minimal/default/heavy) for remote containers

### File Transfer

- Transfer input files to remote server via SSH/SCP before conversion
- Use temporary directory on remote server (e.g., `/tmp/mdify-<session_id>/`)
- Transfer converted markdown files back to local output directory
- Clean up remote temporary files after successful transfer (optional via `--keep-remote-files` flag)
- Show progress bar for files larger than 10MB with percentage, speed (MB/s), and ETA
- In debug mode (`MDIFY_DEBUG=1`), show detailed chunk-by-chunk transfer logs

### Remote Execution

- Execute container runtime commands on remote server via SSH
- Forward container logs from remote to local stderr for debugging
- Handle remote connection failures gracefully with retry logic (3 retries with exponential backoff)
- Validate remote server has sufficient resources before starting container

## Non-Functional Requirements

### Performance

- File transfer should use compression (gzip) for files over 1MB
- Sequential file transfers to keep implementation simple and reliable
- Maintain single persistent SSH connection for entire mdify session to avoid repeated handshakes
- Automatically reconnect if connection is dropped during session

### Security

- Never store passwords in config files
- Use SSH agent for key management when available
- Validate remote server fingerprint on first connection (store in `~/.mdify/known_hosts`)
- Support SSH ProxyJump for bastion host scenarios:
  - Automatically detect and use ProxyJump from `~/.ssh/config` if defined for the target host
  - Allow explicit override via `--ssh-proxy-jump` flag

### Reliability

- Automatic cleanup of remote resources on failure or interrupt (Ctrl+C)
- Resume capability for interrupted transfers (optional, deferred to future)
- Health check remote container before each conversion

### Compatibility

- Compatible with OpenSSH client (standard on macOS/Linux)
- Support Python 3.8+ (same as mdify core)
- No additional Python dependencies beyond existing + asyncssh for SSH

## Technical Design

### New CLI Arguments

```text
--ssh-host HOST         Remote server hostname or IP
--ssh-user USER         SSH username (default: current user)
--ssh-port PORT         SSH port (default: 22)
--ssh-key PATH          Path to SSH private key
--ssh-config-host NAME  Use host from ~/.ssh/config
--ssh-proxy-jump HOST   Override ProxyJump bastion host (auto-detected from config if not specified)
--keep-remote-container Keep container running after conversion
--keep-remote-files     Don't clean up temporary files on remote
```

### Configuration File Format

`~/.mdify/remote.conf` (YAML):
```yaml
ssh:
  host: example.com
  user: john
  port: 22
  key: ~/.ssh/id_rsa
  
profiles:
  production:
    host: prod.example.com
    user: deploy
  
  staging:
    host: staging.example.com
    user: deploy
```

### Module Structure

- `mdify/ssh_client.py` - SSH connection management, file transfer
- `mdify/remote_container.py` - Remote container lifecycle (extends `container.py`)
- Update `cli.py` - Add SSH-related arguments and orchestration logic

## Edge Cases & Error Handling

### Connection Failures

- SSH connection timeout → Retry 3 times, then fail with actionable message
- Authentication failure → Fail immediately with message about key/config
- Network interruption during transfer → Resume if supported, else retry from beginning

### Remote Resource Issues

- Insufficient disk space → Fail before transfer with estimated space needed
- Insufficient memory → Suggest smaller profile or fail with resource requirements
- Container runtime not found → Fail with installation instructions for remote server

### File Transfer Issues

- Large file timeout → Increase timeout proportionally to file size
- Partial transfer → Verify checksums, retry if mismatch
- Permission errors on remote → Fail with directory permission message

## Out of Scope

- Password-based SSH authentication (security risk)
- Windows remote servers (Linux/macOS only)
- Multiple simultaneous remote servers in single command
- Remote GPU support in initial version (deferred to future enhancement)
- Automatic remote server provisioning/setup

## Success Criteria

1. User can convert a document on a remote server using `mdify document.pdf --ssh-host server.com`
2. Files are successfully transferred to/from remote server
3. Remote container is managed automatically (start/stop/health)
4. SSH config integration works correctly
5. Cleanup happens reliably on both success and failure
6. All existing local conversion functionality remains unchanged

## Clarifications

### Session 2026-02-03

- Q: What's the default behavior for remote container lifecycle? → A: Keep container running while files remain in queue, stop and remove when all processing complete; add `--keep-remote-container` flag to override and leave running
- Q: What UI mechanism for file transfer progress? → A: Progress bar showing percentage, speed (MB/s), and ETA for files >10MB; detailed chunk-by-chunk logs in debug mode
- Q: What connection reuse strategy for SSH? → A: Single persistent connection for entire mdify session with automatic reconnect if dropped
- Q: Concurrent vs sequential file transfers? → A: Sequential transfers only for simplicity and reliability
- Q: ProxyJump support strategy? → A: Auto-detect from ~/.ssh/config if defined, allow explicit override via `--ssh-proxy-jump` flag

## Open Questions (Addressed in Phase 0 Research)

- SSH agent forwarding for accessing private container registries? → Phase 0 Research Task R1
- Should we validate remote server OS/architecture compatibility? → Phase 2.5 Validation Task T186
- Progress UI mechanism? → ✅ Resolved: Progress bar with speed/ETA + debug logs
