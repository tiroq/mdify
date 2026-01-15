#!/bin/bash
#
# mdify installer script
# https://github.com/tiroq/mdify
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/tiroq/mdify/main/install.sh | bash
#   ./install.sh [-y] [--upgrade]
#
# Options:
#   -y, --yes       Skip confirmation prompts
#   --upgrade       Upgrade existing installation
#

set -e

# Configuration
MDIFY_HOME="${HOME}/.mdify"
MDIFY_VENV="${MDIFY_HOME}/venv"
MDIFY_BIN="${HOME}/.local/bin"
MDIFY_REPO="https://github.com/tiroq/mdify"
MDIFY_ARCHIVE="${MDIFY_REPO}/archive/refs/heads/main.tar.gz"
MIN_PYTHON_VERSION="3.8"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Flags
SKIP_CONFIRM=false
UPGRADE_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            SKIP_CONFIRM=true
            shift
            ;;
        --upgrade)
            UPGRADE_MODE=true
            shift
            ;;
        -h|--help)
            echo "mdify installer"
            echo ""
            echo "Usage: install.sh [-y|--yes] [--upgrade]"
            echo ""
            echo "Options:"
            echo "  -y, --yes     Skip confirmation prompts"
            echo "  --upgrade     Upgrade existing installation"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Helper functions
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Version comparison - returns 0 if $1 >= $2
version_gte() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# Detect Python 3.8+
detect_python() {
    local python_cmd=""
    
    # Check python3 first, then python
    for cmd in python3 python; do
        if command_exists "$cmd"; then
            local version=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
            if [ -n "$version" ] && version_gte "$version" "$MIN_PYTHON_VERSION"; then
                python_cmd="$cmd"
                break
            fi
        fi
    done
    
    if [ -z "$python_cmd" ]; then
        error "Python ${MIN_PYTHON_VERSION} or higher is required but not found.\nPlease install Python ${MIN_PYTHON_VERSION}+ and try again."
    fi
    
    echo "$python_cmd"
}

# Detect user's shell and RC file
detect_shell_rc() {
    local shell_name=$(basename "$SHELL")
    local rc_file=""
    
    case "$shell_name" in
        bash)
            if [ -f "${HOME}/.bashrc" ]; then
                rc_file="${HOME}/.bashrc"
            elif [ -f "${HOME}/.bash_profile" ]; then
                rc_file="${HOME}/.bash_profile"
            else
                rc_file="${HOME}/.bashrc"
            fi
            ;;
        zsh)
            rc_file="${HOME}/.zshrc"
            ;;
        fish)
            rc_file="${HOME}/.config/fish/config.fish"
            ;;
        *)
            # Fallback to .profile for other shells
            rc_file="${HOME}/.profile"
            ;;
    esac
    
    echo "$rc_file"
}

# Check if PATH contains directory
path_contains() {
    echo "$PATH" | tr ':' '\n' | grep -qx "$1"
}

# Add directory to PATH in RC file
add_to_path() {
    local dir="$1"
    local rc_file="$2"
    local shell_name=$(basename "$SHELL")
    
    # Check if already in PATH
    if path_contains "$dir"; then
        info "Directory already in PATH: $dir"
        return 0
    fi
    
    # Create RC file if it doesn't exist
    if [ ! -f "$rc_file" ]; then
        mkdir -p "$(dirname "$rc_file")"
        touch "$rc_file"
    fi
    
    # Check if export already exists in RC file
    if grep -q "export PATH.*${dir}" "$rc_file" 2>/dev/null; then
        info "PATH export already in $rc_file"
        return 0
    fi
    
    info "Adding $dir to PATH in $rc_file"
    
    if [ "$shell_name" = "fish" ]; then
        echo "" >> "$rc_file"
        echo "# Added by mdify installer" >> "$rc_file"
        echo "fish_add_path $dir" >> "$rc_file"
    else
        echo "" >> "$rc_file"
        echo "# Added by mdify installer" >> "$rc_file"
        echo "export PATH=\"$dir:\$PATH\"" >> "$rc_file"
    fi
    
    success "Updated $rc_file"
}

# Download source code
download_source() {
    local dest_dir="$1"
    
    # Try git clone first
    if command_exists git; then
        info "Cloning repository with git..."
        if git clone --depth 1 "$MDIFY_REPO" "$dest_dir" 2>/dev/null; then
            success "Repository cloned successfully"
            return 0
        fi
        warn "Git clone failed, trying alternative download method..."
    fi
    
    # Fallback to curl/wget
    local temp_archive="${MDIFY_HOME}/mdify.tar.gz"
    
    if command_exists curl; then
        info "Downloading with curl..."
        if curl -sSL "$MDIFY_ARCHIVE" -o "$temp_archive"; then
            mkdir -p "$dest_dir"
            tar -xzf "$temp_archive" -C "$dest_dir" --strip-components=1
            rm -f "$temp_archive"
            success "Downloaded and extracted successfully"
            return 0
        fi
    elif command_exists wget; then
        info "Downloading with wget..."
        if wget -q "$MDIFY_ARCHIVE" -O "$temp_archive"; then
            mkdir -p "$dest_dir"
            tar -xzf "$temp_archive" -C "$dest_dir" --strip-components=1
            rm -f "$temp_archive"
            success "Downloaded and extracted successfully"
            return 0
        fi
    fi
    
    error "Failed to download mdify. Please ensure you have git, curl, or wget installed."
}

# Main installation
main() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           mdify installer                  ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Check for existing installation
    if [ -d "$MDIFY_HOME" ]; then
        if [ "$UPGRADE_MODE" = true ]; then
            info "Upgrading existing installation..."
        else
            if [ "$SKIP_CONFIRM" = false ]; then
                echo -e "${YELLOW}mdify is already installed at ${MDIFY_HOME}${NC}"
                read -p "Do you want to reinstall/upgrade? [y/N] " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    echo "Installation cancelled."
                    exit 0
                fi
            fi
        fi
        info "Removing existing installation..."
        rm -rf "$MDIFY_HOME"
    else
        if [ "$UPGRADE_MODE" = true ]; then
            error "mdify is not installed. Run without --upgrade to install."
        fi
    fi
    
    # Confirmation prompt
    if [ "$SKIP_CONFIRM" = false ] && [ "$UPGRADE_MODE" = false ]; then
        echo "This will install mdify to: ${MDIFY_HOME}"
        echo "Symlink will be created at: ${MDIFY_BIN}/mdify"
        echo ""
        read -p "Continue with installation? [Y/n] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            echo "Installation cancelled."
            exit 0
        fi
    fi
    
    # Detect Python
    info "Checking Python installation..."
    PYTHON_CMD=$(detect_python)
    PYTHON_VERSION=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    success "Found Python $PYTHON_VERSION ($PYTHON_CMD)"
    
    # Create installation directory
    info "Creating installation directory..."
    mkdir -p "$MDIFY_HOME"
    mkdir -p "$MDIFY_BIN"
    
    # Download source
    MDIFY_SRC="${MDIFY_HOME}/src"
    download_source "$MDIFY_SRC"
    
    # Create virtual environment
    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$MDIFY_VENV"
    success "Virtual environment created"
    
    # Install mdify
    info "Installing mdify and dependencies..."
    "${MDIFY_VENV}/bin/pip" install --upgrade pip -q
    "${MDIFY_VENV}/bin/pip" install "$MDIFY_SRC" -q
    success "mdify installed successfully"
    
    # Create symlink
    info "Creating symlink..."
    if [ -L "${MDIFY_BIN}/mdify" ] || [ -f "${MDIFY_BIN}/mdify" ]; then
        rm -f "${MDIFY_BIN}/mdify"
    fi
    ln -s "${MDIFY_VENV}/bin/mdify" "${MDIFY_BIN}/mdify"
    success "Symlink created: ${MDIFY_BIN}/mdify"
    
    # Save installer for future upgrades
    info "Saving installer for future upgrades..."
    SCRIPT_SOURCE="${BASH_SOURCE[0]}"
    if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
        cp "$SCRIPT_SOURCE" "${MDIFY_HOME}/install.sh"
    else
        # If running from curl pipe, download the installer
        if command_exists curl; then
            curl -sSL "https://raw.githubusercontent.com/tiroq/mdify/main/install.sh" -o "${MDIFY_HOME}/install.sh"
        elif command_exists wget; then
            wget -q "https://raw.githubusercontent.com/tiroq/mdify/main/install.sh" -O "${MDIFY_HOME}/install.sh"
        fi
    fi
    chmod +x "${MDIFY_HOME}/install.sh" 2>/dev/null || true
    success "Installer saved to ${MDIFY_HOME}/install.sh"
    
    # Handle PATH
    RC_FILE=$(detect_shell_rc)
    add_to_path "$MDIFY_BIN" "$RC_FILE"
    
    # Verify installation
    echo ""
    if "${MDIFY_VENV}/bin/mdify" --help >/dev/null 2>&1; then
        success "Installation completed successfully!"
    else
        warn "Installation completed but verification failed. Please check manually."
    fi
    
    # Print final instructions
    INSTALLED_VERSION=$("${MDIFY_VENV}/bin/python" -c "from mdify import __version__; print(__version__)")
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Installation Complete!              ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Version:    ${BLUE}${INSTALLED_VERSION}${NC}"
    echo -e "  Location:   ${BLUE}${MDIFY_HOME}${NC}"
    echo -e "  Command:    ${BLUE}${MDIFY_BIN}/mdify${NC}"
    echo ""
    
    if ! path_contains "$MDIFY_BIN"; then
        echo -e "${YELLOW}NOTE: To use mdify immediately, run:${NC}"
        echo -e "  export PATH=\"${MDIFY_BIN}:\$PATH\""
        echo ""
        echo -e "Or restart your terminal to apply PATH changes."
        echo ""
    fi
    
    echo "Usage:"
    echo "  mdify document.pdf                    # Convert a single file"
    echo "  mdify /path/to/docs --recursive      # Convert directory recursively"
    echo ""
    echo "Upgrade:"
    echo "  ${MDIFY_HOME}/install.sh --upgrade"
    echo ""
    echo "Uninstall:"
    echo "  ${MDIFY_HOME}/uninstall.sh"
    echo ""
}

# Run main
main
