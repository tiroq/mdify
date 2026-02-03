# Phase 0 Research: SSH Remote Server Support

**Date**: 2026-02-03

## R1: AsyncSSH Production Readiness

### Python Version Compatibility

- AsyncSSH 2.22.0 documentation states **Python 3.10+** is required.
  - Source: AsyncSSH docs prerequisites and PyPI description (latest).
- **Impact**: mdify targets Python 3.8+. This is a compatibility conflict that must be resolved before implementation.
  - Options to evaluate:
    1. Pin to an older AsyncSSH release that still supports Python 3.8/3.9 (needs verification).
    2. Raise mdify minimum Python requirement to 3.10 (requires project-level decision).
    3. Switch to an alternative library that supports 3.8 (e.g., paramiko).

### Security Advisories (GitHub)

AsyncSSH has published advisories (Moderate severity):

- GHSA-hfmc-7525-mj55 (Prefix Truncation/Terrapin attack) – Dec 18, 2023
- GHSA-c35q-ffpf-5qpm (Rogue Session Attack) – Nov 9, 2023
- GHSA-cfc2-wr2v-gxm5 (Rogue Extension Negotiation) – Nov 9, 2023

**Recommendation**: If AsyncSSH is used, ensure version includes fixes for these advisories and note mitigations in release notes.

### Benchmarks (AsyncSSH vs Paramiko)

- **Status**: Not executed yet (requires a reachable SSH server and paramiko install).
- **Planned script**: Create a local benchmark script that uploads a 100MB file via SFTP using AsyncSSH and Paramiko, capturing throughput, memory, and CPU. (See “Benchmark Plan” below.)

### Reconnection Behavior

- AsyncSSH exposes keepalive and connect timeouts; reconnection should be implemented at the application level.
- **Status**: Not tested yet (requires a reachable SSH server to simulate drops).

#### Benchmark Plan (to execute later)

1. Generate a 100MB file locally.
2. Upload via AsyncSSH SFTP (single connection).
3. Upload via Paramiko SFTP (single connection).
4. Compare MB/s, peak memory, and CPU time.

---

## R2: SSH Config Parsing Strategy

### Findings (Config parsing)

- AsyncSSH provides **partial support for OpenSSH config files** and supports `Include` directives and `Match` blocks.
- Supported client options include `ProxyJump`, `IdentityFile`, `User`, `Port`, and others.
- `asyncssh.connect(..., config=())` will load `.ssh/config` by default if no explicit config path is provided.

### Precedence Strategy

1. CLI flags
2. `~/.mdify/remote.conf`
3. `~/.ssh/config` (AsyncSSH config parsing)

### Edge Cases to cover in tests

- `Include` directives
- `Match` blocks (including `Match Host` and `Match Exec`)
- Wildcards in `Host` entries
- Alias resolution (`Host foo` + `Hostname real-host`)

### Precedence Test Cases (Draft)

- CLI overrides `~/.mdify/remote.conf` overrides `~/.ssh/config`.
- CLI provides host/user while config provides port/key.
- `--ssh-config-host` alias resolves `HostName` and `User`.
- `Include` with nested host definitions.
- `Match` blocks affecting `User` and `IdentityFile`.
- Wildcard `Host *.example.com` with a specific host entry.

### Config Construction Notes

- `SSHConfig` constructor should accept `host`, `user`, `port`, `key_path`, `proxy_jump`.
- Precedence logic should merge partial configs, preferring non-null CLI values.
- `key_path` should expand `~` and environment variables.

---

## R3: File Transfer Progress

### Findings (Progress callbacks)

- AsyncSSH SFTP provides `progress_handler` callbacks on `put()` and `get()`.
- AsyncSSH SCP provides `progress_handler` on `scp()`.

### Recommendation

- Use SFTP `progress_handler` for both upload/download.
- `progress_handler` signature provides `(path, bytes_copied, total_bytes)` per file.
- Build a simple `ProgressBar` class to compute speed and ETA.

### Debug Logging

- When `MDIFY_DEBUG=1`, emit per-chunk progress logs via `progress_handler` (log bytes and elapsed time).

---

## R4: Container Runtime Detection Over SSH

### Plan (Runtime detection)

- Use `ssh.execute('which docker')` and `ssh.execute('which podman')` to detect runtime.
- For macOS remote hosts, detect `container` (Apple Container) via `which container`.
- Priority order mirrors local detection:
  - macOS: container → orbstack → colima → podman → docker
  - Linux: docker → podman

**Status**: Not tested yet on real remote host.

---

## R5: Resource Validation on Remote Server

### Plan (Resource validation)

- Disk space: `df -h <path>` with parsing of available column.
- Linux memory: `/proc/meminfo` (use MemAvailable).
- macOS memory: `vm_stat` (free + inactive * page size).

**Status**: Parsing logic not validated yet on remote systems.

---

## Open Issues / Blockers

1. **Python version conflict**: AsyncSSH 2.x requires Python 3.10+, but mdify targets Python 3.8+. Requires decision.
2. **Benchmarks not run**: Need a reachable SSH host and Paramiko install to run throughput tests.
3. **Reconnection tests**: Need a reachable SSH host to simulate dropped connections.
4. **Remote runtime/resource checks**: Need SSH access to Linux/macOS hosts to validate parsing logic.

---

## Next Actions Needed

- Decide on Python compatibility strategy (pin older AsyncSSH vs raise minimum Python version vs alternative SSH library).
- Provide access to a test SSH host for benchmarks and reconnection tests.
- Once resolved, proceed to Phase 1 design and contracts.
