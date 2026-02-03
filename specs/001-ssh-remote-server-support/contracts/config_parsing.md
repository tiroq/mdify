# Contract: Config Parsing Strategy

**Status**: Phase 1 - Design  
**Version**: 1.0  
**Last Updated**: 2026-02-03

---

## Overview

This document specifies how SSH and mdify configuration files are loaded and merged with CLI arguments to produce a final `SSHConfig` object.

---

## Configuration Sources

### 1. OpenSSH Config (~/.ssh/config)

**Standard Format**: OpenSSH config file format  
**Location**: `~/.ssh/config` (or $SSH_CONFIG)  
**Priority**: Lowest (overridden by other sources)

**Parsing Rules**:
- Use `asyncssh.config` module for parsing
- Support Include directives with recursion (max 10 levels)
- Support Match directives with hostname matching
- Load these parameters from Host/Match sections:
  - `HostName` → SSHConfig.host
  - `Port` → SSHConfig.port
  - `User` → SSHConfig.username
  - `IdentityFile` → SSHConfig.key_file (first one only)
  - `ConnectTimeout` → SSHConfig.timeout
  - `ServerAliveInterval` → SSHConfig.keepalive
  - `Compression` → SSHConfig.compression (yes/no → bool)

**Example ~/.ssh/config**:
```
Host myserver
    HostName myserver.example.com
    Port 2222
    User deploy
    IdentityFile ~/.ssh/myserver_key
    ConnectTimeout 30
    ServerAliveInterval 60

Host *.prod
    Port 2222
    User production
    Compression yes

# Include other configs
Include ~/.ssh/config.d/*
```

**Parsing Implementation**:
```python
def load_ssh_config(host: str) -> dict:
    """Load SSH config for host using asyncssh.config module."""
    config = asyncssh.config.load_config(
        check_config_syntax=False,
        load_config=True,
        order=['host', 'port', 'user', 'identityfile', 'connecttimeout', 'serveraliveinterval', 'compression']
    )
    if host in config:
        return config[host]
    return {}
```

---

### 2. mdify Remote Config (~/.mdify/remote.conf)

**Format**: YAML  
**Location**: `~/.mdify/remote.conf`  
**Priority**: Medium (overrides SSH config, overridden by CLI)

**File Structure**:
```yaml
# ~/.mdify/remote.conf

# Default configuration applied to all servers
defaults:
  timeout: 30
  keepalive: 60
  work_dir: /tmp/mdify
  compression: false

# Named server configurations
servers:
  production:
    host: prod.server.com
    port: 2222
    username: deploy
    key_file: ~/.ssh/prod_key
    timeout: 60
    container_runtime: docker
    
  staging:
    host: staging.server.com
    username: dev
    work_dir: /var/local/mdify
    container_runtime: podman
    
  local-docker:
    host: 127.0.0.1
    port: 22
    username: user
    key_file: ~/.ssh/id_rsa
    work_dir: /var/lib/mdify
```

**Loading Rules**:
1. Parse YAML file
2. Apply `defaults` section to all servers
3. Select server config by name (from CLI or environment)
4. If no server specified, use first server in list
5. Expand ~ and $VAR in file paths

**Environment Variables**:
- `MDIFY_SERVER`: Select which named server to use
- `MDIFY_CONFIG`: Override default config file path

---

### 3. CLI Arguments

**Format**: Command-line flags  
**Priority**: Highest (overrides all other sources)

**Arguments**:
```bash
mdify convert \
  --remote-host server.com          # Override SSH config host
  --remote-port 2222                # Override SSH config port
  --remote-user deploy              # Override SSH config user
  --remote-key ~/.ssh/key_rsa       # Override SSH config key
  --remote-key-pass-phrase mypass   # Key passphrase if encrypted
  --remote-timeout 60               # Override connect timeout
  --remote-keepalive 120            # Override keepalive interval
  --remote-work-dir /var/mdify      # Override working directory
  --remote-runtime docker           # Force runtime (docker or podman)
  --remote-config-file ~/.mdify/remote.conf  # Specify config file
  input.pdf output.md
```

---

## Precedence and Merging

**Application Order** (lowest to highest priority):

1. **SSH Config** (lowest)
   ```python
   ssh_config = SSHConfig.from_ssh_config(host)
   ```

2. **Merge with mdify config** (medium)
   ```python
   if mdify_config_file.exists():
       mdify_config = SSHConfig.from_remote_conf(mdify_config_file)
       ssh_config = ssh_config.merge(mdify_config)
   ```

3. **Merge with CLI args** (highest)
   ```python
   cli_config = SSHConfig.from_cli_args(args)
   final_config = ssh_config.merge(cli_config)
   ```

**Merge Logic** (in `SSHConfig.merge()`):
```python
def merge(self, higher_precedence: SSHConfig) -> SSHConfig:
    """Merge with higher precedence config."""
    result = SSHConfig(
        host=higher_precedence.host or self.host,
        port=higher_precedence.port or self.port,
        username=higher_precedence.username or self.username,
        # ... etc for all fields
        source=higher_precedence.source,  # Keep track of source
    )
    return result
```

---

## Example: Complete Precedence Flow

**Scenario**: User has SSH config, mdify config, and provides some CLI args

**Given**:
- SSH config has: host=myserver.com, user=default_user, key_file=~/.ssh/id_rsa
- Mdify config has: port=2222, timeout=60
- CLI args: `--remote-user deploy --remote-key ~/.ssh/deploy_key`

**Processing**:
```python
# Step 1: Load SSH config for host "myserver.com"
ssh_config = SSHConfig.from_ssh_config("myserver.com")
# → SSHConfig(host="myserver.com", username="default_user", key_file="~/.ssh/id_rsa", port=22, timeout=30)

# Step 2: Load and merge mdify config
mdify_config = SSHConfig.from_remote_conf()
ssh_config = ssh_config.merge(mdify_config)
# → SSHConfig(host="myserver.com", username="default_user", key_file="~/.ssh/id_rsa", port=2222, timeout=60)

# Step 3: Load and merge CLI args
cli_config = SSHConfig.from_cli_args(args)
# → SSHConfig(username="deploy", key_file="~/.ssh/deploy_key")
final_config = ssh_config.merge(cli_config)

# FINAL RESULT:
# SSHConfig(
#   host="myserver.com",     # from SSH config
#   port=2222,                # from mdify config
#   username="deploy",        # from CLI (overrides SSH config)
#   key_file="~/.ssh/deploy_key",  # from CLI (overrides SSH config)
#   timeout=60,               # from mdify config
#   source="cli"              # highest precedence source
# )
```

---

## Edge Cases

### 1. Missing Required Fields

**Rule**: `host` is required; others have defaults

**Handling**:
```python
if not final_config.host:
    raise ConfigError("No remote host specified. Provide --remote-host or configure SSH host")
```

### 2. File Path Expansion

**Rule**: All file paths undergo tilde and variable expansion

**Implementation**:
```python
def expand_path(path: str) -> str:
    """Expand ~, ~user, and environment variables."""
    path = os.path.expanduser(path)  # Expand ~ and ~user
    path = os.path.expandvars(path)  # Expand $VAR and ${VAR}
    return path
```

### 3. SSH Config Include Directives

**Rule**: Include directives in SSH config are parsed recursively

**Implementation**:
```python
# asyncssh.config handles this automatically
config = asyncssh.config.load_config(load_config=True)
# Recursively includes files from Include directives
```

### 4. Match Directives with Multiple Conditions

**Rule**: Match directive applies if all conditions match

**Example SSH config**:
```
Match Host *.prod User production
    Port 2222
    IdentityFile ~/.ssh/prod_key

Match Host *.dev !User production
    Port 2200
    IdentityFile ~/.ssh/dev_key
```

**Implementation**: asyncssh.config handles matching logic

### 5. Multiple IdentityFile Directives

**Rule**: Use first IdentityFile; warn about others

**Implementation**:
```python
if len(identity_files) > 1:
    logger.warning(f"Multiple identity files configured; using {identity_files[0]}")
```

---

## Configuration File Validation

**Validation Steps**:

1. **SSH Config** (`~/.ssh/config`):
   - File must be readable
   - Must be valid SSH config syntax
   - Paths must exist or be expandable

2. **mdify Config** (`~/.mdify/remote.conf`):
   - File must be readable YAML
   - Must contain `defaults` and/or `servers` sections
   - All file paths must be expandable
   - All ports must be 1-65535
   - All timeouts must be positive integers

3. **CLI Arguments**:
   - Port must be 1-65535
   - Timeout must be positive integer
   - Key file must exist
   - Work directory must be absolute path or relative to ~

---

## Debug Output

When debug mode is enabled, log the merging process:

```
Loading SSH config for host 'myserver.com'...
  host: myserver.com (from SSH config)
  user: default_user (from SSH config)
  key_file: ~/.ssh/id_rsa (from SSH config)
  port: 22 (from SSH config)
  timeout: 30 (from SSH config)

Loading mdify config...
  port: 2222 (overrides SSH config)
  timeout: 60 (overrides SSH config)

Loading CLI args...
  username: deploy (overrides all)
  key_file: ~/.ssh/deploy_key (overrides all)

Final merged config:
  host: myserver.com
  port: 2222
  username: deploy
  key_file: ~/.ssh/deploy_key
  timeout: 60
```

---

## Testing Scenarios

All of these must be tested with unit and integration tests:

1. **SSH config only**: No mdify config, no CLI args
2. **Mdify config only**: No SSH config, no CLI args
3. **CLI args only**: No SSH config, no mdify config
4. **All three combined**: Verify precedence order
5. **Missing required fields**: Verify error handling
6. **Path expansion**: Verify ~ and $VAR expansion
7. **Include directives**: Verify recursive includes work
8. **Match directives**: Verify hostname matching works
9. **Missing files**: Verify graceful error handling

---
