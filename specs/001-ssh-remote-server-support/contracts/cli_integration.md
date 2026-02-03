# Contract: CLI Integration

**Status**: Phase 1 - Design  
**Version**: 1.0  
**Last Updated**: 2026-02-03

---

## Overview

This document specifies the new CLI arguments and integration points for SSH remote server support.

**Location**: `mdify/cli.py`

---

## New CLI Arguments

All arguments are added to the existing `convert` subcommand (or as global options applicable when using remote).

### SSH Connection Group

```
--remote-host HOST
  SSH host or IP address of remote server
  Type: str
  Required: No (local mode if not specified)
  Example: --remote-host server.example.com
  
--remote-port PORT
  SSH port on remote server
  Type: int
  Default: 22
  Min: 1, Max: 65535
  Example: --remote-port 2222
  
--remote-user USER
  SSH username for authentication
  Type: str
  Default: Current system user ($USER)
  Example: --remote-user deploy
  
--remote-key KEY_PATH
  Path to SSH private key
  Type: str
  Default: ~/.ssh/id_rsa
  Example: --remote-key ~/.ssh/prod_key
  
--remote-key-pass-phrase PHRASE
  Passphrase for encrypted private key
  Type: str
  Default: None (assume unencrypted key)
  Example: --remote-key-pass-phrase "my secret phrase"
  
--remote-timeout SECONDS
  Connection timeout in seconds
  Type: int
  Default: 30
  Min: 1, Max: 300
  Example: --remote-timeout 60
```

### Remote Environment Group

```
--remote-work-dir PATH
  Working directory on remote server for temporary files
  Type: str
  Default: /tmp/mdify
  Example: --remote-work-dir /var/local/mdify
  
--remote-runtime RUNTIME
  Force specific container runtime
  Type: choice
  Choices: docker, podman
  Default: Auto-detect (docker preferred over podman)
  Example: --remote-runtime podman
  
--remote-config-file FILE
  Path to mdify remote config file
  Type: str
  Default: ~/.mdify/remote.conf
  Example: --remote-config-file ~/.mdify/servers.yaml
```

### SSH Config Group

```
--remote-no-ssh-config
  Skip loading SSH config file (~/.ssh/config)
  Type: bool (flag)
  Default: False
  Example: mdify convert --remote-host server.com --remote-no-ssh-config input.pdf output.md
  
--remote-ssh-config-file FILE
  Path to SSH config file (default ~/.ssh/config)
  Type: str
  Default: ~/.ssh/config
  Example: --remote-ssh-config-file ~/.ssh/alt-config
```

### Validation and Resource Checks

```
--remote-skip-validation
  Skip resource validation checks on remote (disk space, memory, runtime)
  Type: bool (flag)
  Default: False
  Caution: Using this may cause conversion to fail if resources insufficient
  Example: mdify convert --remote-host server.com --remote-skip-validation input.pdf output.md
  
--remote-validate-only
  Run validation checks and exit (don't perform conversion)
  Type: bool (flag)
  Default: False
  Example: mdify convert --remote-host server.com --remote-validate-only input.pdf output.md
```

### Debug and Progress

```
--remote-debug
  Enable detailed SSH operation logging
  Type: bool (flag)
  Default: False (controlled by MDIFY_DEBUG env var)
  Example: mdify convert --remote-host server.com --remote-debug input.pdf output.md
  
--remote-progress
  Show file transfer progress with speed and ETA
  Type: bool (flag)
  Default: True (show progress unless redirected or --quiet)
  Example: mdify convert --remote-host server.com input.pdf output.md
```

---

## CLI Examples

### Example 1: Basic Remote Conversion

```bash
# Minimal - uses SSH config and defaults
mdify convert \
  --remote-host myserver.com \
  input.pdf output.md
```

### Example 2: Custom Key and Port

```bash
# Explicit authentication details
mdify convert \
  --remote-host server.example.com \
  --remote-port 2222 \
  --remote-user deploy \
  --remote-key ~/.ssh/deploy_key \
  input.pdf output.md
```

### Example 3: Encrypted Key with Passphrase

```bash
# Private key with passphrase
mdify convert \
  --remote-host server.example.com \
  --remote-key ~/.ssh/id_rsa_encrypted \
  --remote-key-pass-phrase "my-secure-passphrase" \
  input.pdf output.md
```

### Example 4: Validation Without Conversion

```bash
# Verify remote resources are sufficient
mdify convert \
  --remote-host server.example.com \
  --remote-validate-only \
  input.pdf output.md
```

### Example 5: Skip Validation (Risky)

```bash
# Trust that remote is configured correctly
mdify convert \
  --remote-host server.example.com \
  --remote-skip-validation \
  input.pdf output.md
```

### Example 6: Alternative Config File

```bash
# Use named server from custom config
mdify convert \
  --remote-host production \
  --remote-config-file ~/.mdify/servers.yaml \
  input.pdf output.md
```

---

## Argument Groups in argparse

Organize arguments using argument groups for clarity:

```python
# In mdify/cli.py

def setup_remote_arguments(parser):
    """Add remote SSH arguments to argument parser."""
    
    # SSH Connection Group
    ssh_group = parser.add_argument_group('SSH Connection')
    ssh_group.add_argument('--remote-host', help='SSH host or IP')
    ssh_group.add_argument('--remote-port', type=int, default=22, help='SSH port')
    ssh_group.add_argument('--remote-user', help='SSH username')
    ssh_group.add_argument('--remote-key', help='Path to SSH private key')
    ssh_group.add_argument('--remote-key-pass-phrase', help='Key passphrase')
    ssh_group.add_argument('--remote-timeout', type=int, default=30, help='Connection timeout')
    
    # Remote Environment Group
    env_group = parser.add_argument_group('Remote Environment')
    env_group.add_argument('--remote-work-dir', default='/tmp/mdify', help='Work directory on remote')
    env_group.add_argument('--remote-runtime', choices=['docker', 'podman'], help='Container runtime')
    env_group.add_argument('--remote-config-file', help='Path to remote config file')
    
    # Configuration Group
    config_group = parser.add_argument_group('SSH Configuration')
    config_group.add_argument('--remote-no-ssh-config', action='store_true', help='Skip SSH config file')
    config_group.add_argument('--remote-ssh-config-file', help='Path to SSH config file')
    
    # Validation Group
    val_group = parser.add_argument_group('Validation & Checks')
    val_group.add_argument('--remote-skip-validation', action='store_true', help='Skip resource checks')
    val_group.add_argument('--remote-validate-only', action='store_true', help='Validate and exit')
    
    # Debug Group
    debug_group = parser.add_argument_group('Debug & Progress')
    debug_group.add_argument('--remote-debug', action='store_true', help='Enable SSH debug logging')
    debug_group.add_argument('--remote-progress', action='store_true', default=True, help='Show transfer progress')
```

---

## Integration with Existing Code

### Current CLI Structure

The mdify CLI currently has this structure:
```python
mdify/cli.py
├── main()                   # Entry point
├── convert_command()        # mdify convert subcommand
└── other_commands()
```

### Required Changes

1. **Import Remote Modules**
   ```python
   from mdify.ssh.client import AsyncSSHClient
   from mdify.ssh.remote_container import RemoteContainer
   from mdify.ssh.models import SSHConfig
   ```

2. **Modify convert_command()**
   ```python
   async def convert_command(args):
       # Check if remote mode is enabled
       if args.remote_host:
           # Remote conversion flow
           await remote_convert(args)
       else:
           # Existing local conversion flow
           local_convert(args)
   ```

3. **New remote_convert() Function**
   ```python
   async def remote_convert(args):
       """Execute conversion on remote server."""
       # 1. Load and merge SSH config
       ssh_config = SSHConfig.from_ssh_config(args.remote_host)
       if Path(args.remote_config_file).exists():
           mdify_config = SSHConfig.from_remote_conf(args.remote_config_file)
           ssh_config = ssh_config.merge(mdify_config)
       cli_config = SSHConfig.from_cli_args(args)
       ssh_config = ssh_config.merge(cli_config)
       
       # 2. Connect to remote
       client = AsyncSSHClient(ssh_config)
       await client.connect()
       
       # 3. Validate resources (unless --remote-skip-validation)
       if not args.remote_skip_validation:
           validation = await client.validate_remote_resources()
           if not all(validation.values()):
               print("Resource validation failed:")
               for check, passed in validation.items():
                   status = "✓" if passed else "✗"
                   print(f"  {status} {check}")
               if args.remote_validate_only:
                   sys.exit(1)
               return  # Or raise error
       
       # 4. If --remote-validate-only, exit here
       if args.remote_validate_only:
           print("All validation checks passed!")
           return
       
       # 5. Upload input file
       await client.upload_file(args.input_pdf, "/tmp/mdify/input.pdf", progress_callback=show_progress)
       
       # 6. Start container
       container = RemoteContainer(client, "docling-serve:latest", 8000)
       await container.start()
       
       # 7. Run conversion
       result = await convert_on_remote(container, args)
       
       # 8. Download output
       await client.download_file("/tmp/mdify/output.md", args.output_md, progress_callback=show_progress)
       
       # 9. Cleanup
       await container.stop()
       await client.disconnect()
   ```

---

## Error Messages

**User-facing error messages** for common scenarios:

```
ERROR: Remote host is required for remote conversion
  Use: mdify convert --remote-host <HOST> <INPUT> <OUTPUT>

ERROR: SSH authentication failed (no valid key or password)
  Check: Key file exists at ~/.ssh/id_rsa
  Check: Key passphrase is correct if key is encrypted
  Check: SSH server allows your username

ERROR: SSH connection timeout after 30 seconds
  Check: Host is reachable (ping server.com)
  Check: SSH port is correct (default 22)
  Check: Firewall allows SSH connections

ERROR: Remote resource validation failed:
  ✗ disk_space_min_5gb: Only 2GB available in /tmp/mdify
  ✗ memory_min_2gb: Only 1GB available
  Use: mdify convert --remote-work-dir /path/with/more/space ...

ERROR: Container runtime not available on remote
  Check: docker or podman is installed
  Check: You have permission to use the runtime
  Use: mdify convert --remote-runtime podman ...  # Force specific runtime
```

---

## Backward Compatibility

All new arguments are optional. Existing local conversion commands work unchanged:

```bash
# This still works exactly as before
mdify convert input.pdf output.md

# New remote mode is opt-in
mdify convert --remote-host server.com input.pdf output.md
```

---

## Testing Requirements

- Unit tests for argument parsing
- Integration tests for all argument combinations
- Tests for validation error messages
- Tests for SSH config merging with CLI args
- Tests for remote validation with various resource constraints

---
