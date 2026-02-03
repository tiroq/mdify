# Quickstart: SSH Remote Server Support

**Status**: Phase 1 - Design  
**Version**: 1.0  
**Last Updated**: 2026-02-03

---

## Overview

This quickstart guide demonstrates common usage scenarios for the SSH remote server support feature in mdify.

---

## Scenario 1: Convert PDF on Remote Server (Basic)

**Use Case**: You want to convert a PDF on a remote server instead of your local machine.

**Prerequisites**:
- Remote server is accessible via SSH
- docling-serve container image is available on remote
- 5GB+ disk space and 2GB+ memory available

**Command**:
```bash
mdify convert \
  --remote-host myserver.example.com \
  input.pdf output.md
```

**What Happens**:
1. Connects to `myserver.example.com` via SSH (uses SSH config for auth details)
2. Validates remote resources (disk space, memory, container runtime)
3. Uploads `input.pdf` to remote server
4. Starts docling-serve container on remote
5. Converts PDF to Markdown on remote
6. Downloads `output.md` to local machine
7. Cleans up container and temporary files on remote

**Output**:
```
Connecting to myserver.example.com...
Validating remote resources...
✓ Docker available
✓ 50GB disk space
✓ 16GB memory
Uploading input.pdf... [████████████████████████████] 100%
Starting docling-serve container...
Converting input.pdf...
Downloading output.md... [████████████████████████████] 100%
Success! output.md created (150KB)
```

---

## Scenario 2: Using a Specific SSH Key

**Use Case**: You have a custom SSH key for production server.

**Command**:
```bash
mdify convert \
  --remote-host prod.server.com \
  --remote-key ~/.ssh/prod_deploy_key \
  document.pdf output.md
```

**Notes**:
- Key must have correct file permissions (`chmod 600 ~/.ssh/prod_deploy_key`)
- If key is passphrase-protected, see Scenario 4

**Why Use**:
- Production environments often require specific keys
- Different keys per environment for security
- Key rotation without changing default key

---

## Scenario 3: Non-standard SSH Port

**Use Case**: Your server uses SSH on port 2222 instead of default 22.

**Command**:
```bash
mdify convert \
  --remote-host server.example.com \
  --remote-port 2222 \
  --remote-user deploy \
  document.pdf output.md
```

**Alternatively**: Configure in `~/.ssh/config`:
```
Host server.example.com
    Port 2222
    User deploy
```

Then just use:
```bash
mdify convert --remote-host server.example.com document.pdf output.md
```

---

## Scenario 4: SSH Key with Passphrase

**Use Case**: Your private key is encrypted with a passphrase.

**Command**:
```bash
mdify convert \
  --remote-host server.example.com \
  --remote-key ~/.ssh/id_rsa_encrypted \
  --remote-key-pass-phrase "my-secret-phrase" \
  document.pdf output.md
```

**Security Notes**:
- Avoid putting passphrases in shell scripts
- Better approach: Use passphrase-less key + SSH key restrictions
- Or: Use SSH agent and let SSH config point to it

---

## Scenario 5: Pre-configured Server (Using remote.conf)

**Use Case**: You frequently convert on the same servers; avoid typing flags every time.

**Setup** (`~/.mdify/remote.conf`):
```yaml
defaults:
  timeout: 30
  keepalive: 60
  work_dir: /var/local/mdify

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
    container_runtime: podman
```

**Command** (much simpler):
```bash
# Automatically uses settings from 'production' server
mdify convert --remote-host production document.pdf output.md
```

**Why Use**:
- Avoid repeating flags for each conversion
- Centralized server configuration
- Easy switching between environments

---

## Scenario 6: Validate Resources Before Conversion

**Use Case**: Check if remote server has sufficient resources before converting large files.

**Command**:
```bash
mdify convert \
  --remote-host myserver.com \
  --remote-validate-only \
  large_document.pdf output.md
```

**Output**:
```
Connecting to myserver.com...
Validating remote resources...
✓ SSH connection successful
✓ Working directory /tmp/mdify exists and is writable
✓ Docker available and functional
✓ 50GB disk space available (need 5GB)
✓ 16GB memory available (need 2GB)
✓ SSH configuration valid

All validation checks passed!
```

**When to Use**:
- Before converting many large files
- When moving to a new remote server
- Troubleshooting conversion failures

---

## Scenario 7: Custom Working Directory

**Use Case**: Remote server's /tmp is small; use larger disk for work directory.

**Command**:
```bash
mdify convert \
  --remote-host myserver.com \
  --remote-work-dir /var/local/mdify \
  large_document.pdf output.md
```

**Why Use**:
- Different servers have different storage layouts
- Large file conversions need temporary space
- /tmp often has quota restrictions
- Can use faster/larger disk partitions

---

## Scenario 8: Skip Validation (For Speed)

**Use Case**: You've already validated the server; skip checks for faster conversion.

**Command**:
```bash
mdify convert \
  --remote-host myserver.com \
  --remote-skip-validation \
  document.pdf output.md
```

**Warning**:
- Only skip if you're certain resources are available
- Conversion will fail with unclear errors if resources insufficient
- Use validation before adopting this approach

**Why Use**:
- Batch processing many files (validate once)
- Known-good server environment
- When every second counts

---

## Scenario 9: Force Specific Container Runtime

**Use Case**: Server has both Docker and Podman; need Podman specifically.

**Command**:
```bash
mdify convert \
  --remote-host myserver.com \
  --remote-runtime podman \
  document.pdf output.md
```

**Why Use**:
- Some servers prefer Podman (better rootless support)
- Docker might have licensing/support restrictions
- Performance testing with different runtimes

**Default Behavior**: Auto-detects docker first, falls back to podman

---

## Scenario 10: Debugging Connection Issues

**Use Case**: SSH connection is failing; need detailed logs to troubleshoot.

**Command**:
```bash
mdify convert \
  --remote-host myserver.com \
  --remote-debug \
  document.pdf output.md
```

**Output** (with --remote-debug):
```
[SSH] Connecting to myserver.com:22 as user 'deploy'...
[SSH] Trying key /home/user/.ssh/id_rsa... SUCCESS
[SSH] Connection established (OpenSSH_8.0)
[SSH] Uploading input.pdf (1.2MB)
[SSH] Chunk 1/20: 65KB transferred (10MB/s)
[SSH] Chunk 2/20: 65KB transferred (12MB/s)
...
[SSH] Connecting to container health endpoint http://myserver.com:8000/health...
[SSH] Health check: 200 OK (0.45s)
```

**Debug Information**:
- Connection attempt details
- Authentication method and key used
- File transfer chunk progress
- Container health check responses
- Error details with full stack traces

---

## Scenario 11: Environment Variable Configuration

**Use Case**: Want to set default remote server without editing config files.

**Environment Variables**:
```bash
# Set default remote server
export MDIFY_SERVER=production

# Set custom config file
export MDIFY_CONFIG=~/.mdify/custom-servers.yaml

# Enable debug mode
export MDIFY_DEBUG=1
```

**Then use simplified command**:
```bash
mdify convert document.pdf output.md
```

**Why Use**:
- CI/CD environments
- Different configs per environment
- Temporary overrides without config file changes

---

## Scenario 12: Batch Processing Multiple Files

**Use Case**: Convert 100 PDFs on remote server in parallel.

**Setup** (`convert_batch.sh`):
```bash
#!/bin/bash

REMOTE_HOST="batch.server.com"

# Validate once
mdify convert --remote-host $REMOTE_HOST --remote-validate-only input1.pdf /tmp/dummy.md

# Validate resources once before starting batch
if [ $? -ne 0 ]; then
    echo "Remote resource validation failed!"
    exit 1
fi

# Process files in parallel (4 at a time)
for pdf in documents/*.pdf; do
    output="${pdf%.pdf}.md"
    
    # Skip validation for batch (--remote-skip-validation)
    mdify convert \
        --remote-host $REMOTE_HOST \
        --remote-skip-validation \
        "$pdf" "$output" &
    
    # Keep max 4 processes running
    if (( $(jobs -r -p | wc -l) >= 4 )); then
        wait -n
    fi
done

# Wait for remaining jobs
wait

echo "Batch conversion complete!"
```

**Usage**:
```bash
bash convert_batch.sh
```

**Benefits**:
- Validate once, process many
- Parallel processing on single remote server
- Efficient resource usage

---

## Scenario 13: CI/CD Pipeline Integration

**Use Case**: Convert PDFs as part of automated documentation build.

**GitHub Actions Example**:
```yaml
name: Build Documentation

on: [push, pull_request]

jobs:
  convert:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install mdify
        run: pip install mdify-cli
        
      - name: Convert PDFs to Markdown
        run: |
          mdify convert \
            --remote-host ${{ secrets.REMOTE_HOST }} \
            --remote-user ${{ secrets.REMOTE_USER }} \
            --remote-key-pass-phrase ${{ secrets.SSH_KEY_PASSPHRASE }} \
            documents/spec.pdf docs/spec.md
            
      - name: Commit changes
        run: |
          git config user.email "bot@example.com"
          git config user.name "Documentation Bot"
          git add docs/
          git commit -m "Update documentation from PDFs" || true
          git push
```

**Environment Secrets** (configure in GitHub):
- `REMOTE_HOST`: Production SSH server hostname
- `REMOTE_USER`: SSH username
- `SSH_KEY_PASSPHRASE`: Passphrase for CI/CD SSH key

**Why Use**:
- Automated documentation updates
- No local processing power needed
- Central server handles conversions
- Consistent output across builds

---

## Error Scenarios & Troubleshooting

### "SSH: Connection timeout"
```bash
# Add longer timeout
mdify convert \
  --remote-host slow.server.com \
  --remote-timeout 90 \
  document.pdf output.md
```

### "Permission denied (publickey)"
```bash
# Check your key and server settings
mdify convert \
  --remote-host myserver.com \
  --remote-user correct_username \
  --remote-key ~/.ssh/correct_key \
  --remote-debug \
  document.pdf output.md
```

### "Insufficient disk space"
```bash
# Use different working directory
mdify convert \
  --remote-host myserver.com \
  --remote-work-dir /mnt/large-disk/mdify \
  document.pdf output.md
```

### "Docker not found on remote"
```bash
# Try podman instead
mdify convert \
  --remote-host myserver.com \
  --remote-runtime podman \
  document.pdf output.md
```

---

## Next Steps

1. **Set up remote server**: Ensure SSH access and Docker/Podman are installed
2. **Create config file**: Set up `~/.mdify/remote.conf` for your servers
3. **Test connection**: Run `--remote-validate-only` to verify setup
4. **Start converting**: Use scenarios above that match your use case
5. **Integrate**: Add remote conversion to CI/CD pipelines

For detailed API reference, see:
- `data-model.md`: Data structures
- `contracts/ssh_client.md`: SSHClient interface
- `contracts/config_parsing.md`: Configuration loading rules
- `contracts/cli_integration.md`: CLI argument specifications

---
