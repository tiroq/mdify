#!/bin/bash
#
# mdify uninstaller script
# https://github.com/tiroq/mdify
#
# Usage:
#   ~/.mdify/uninstall.sh
#

set -e

# Configuration
MDIFY_HOME="${HOME}/.mdify"
MDIFY_BIN="${HOME}/.local/bin"
MDIFY_SYMLINK="${MDIFY_BIN}/mdify"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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
            fi
            ;;
        zsh)
            rc_file="${HOME}/.zshrc"
            ;;
        fish)
            rc_file="${HOME}/.config/fish/config.fish"
            ;;
        *)
            rc_file="${HOME}/.profile"
            ;;
    esac
    
    echo "$rc_file"
}

# Remove PATH entries from RC file
clean_rc_file() {
    local rc_file="$1"
    
    if [ ! -f "$rc_file" ]; then
        return 0
    fi
    
    # Check if mdify entries exist
    if ! grep -q "mdify installer" "$rc_file" 2>/dev/null; then
        info "No mdify entries found in $rc_file"
        return 0
    fi
    
    read -p "Remove mdify PATH entries from $rc_file? [y/N] " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Skipping RC file cleanup"
        return 0
    fi
    
    info "Cleaning up $rc_file..."
    
    # Create a backup
    cp "$rc_file" "${rc_file}.mdify-backup"
    
    # Remove mdify-related lines (comment and export)
    local temp_file=$(mktemp)
    grep -v "Added by mdify installer" "$rc_file" | grep -v "fish_add_path.*\.local/bin" | grep -v 'export PATH=.*\.local/bin' > "$temp_file" || true
    
    # Remove trailing empty lines and consecutive empty lines
    cat -s "$temp_file" > "$rc_file"
    rm -f "$temp_file"
    
    success "Cleaned up $rc_file (backup: ${rc_file}.mdify-backup)"
}

# Main uninstallation
main() {
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           mdify uninstaller                ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Check if mdify is installed
    if [ ! -d "$MDIFY_HOME" ]; then
        error "mdify is not installed at ${MDIFY_HOME}"
        exit 1
    fi
    
    # Get installed version for display
    INSTALLED_VERSION=""
    if [ -f "${MDIFY_HOME}/venv/bin/python" ]; then
        INSTALLED_VERSION=$("${MDIFY_HOME}/venv/bin/python" -c "from mdify import __version__; print(__version__)" 2>/dev/null || echo "unknown")
    fi
    
    echo "This will uninstall mdify:"
    echo ""
    echo -e "  Version:    ${BLUE}${INSTALLED_VERSION}${NC}"
    echo -e "  Location:   ${BLUE}${MDIFY_HOME}${NC}"
    echo -e "  Symlink:    ${BLUE}${MDIFY_SYMLINK}${NC}"
    echo ""
    
    read -p "Are you sure you want to uninstall mdify? [y/N] " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstallation cancelled."
        exit 0
    fi
    
    echo ""
    
    # Remove symlink
    if [ -L "$MDIFY_SYMLINK" ] || [ -f "$MDIFY_SYMLINK" ]; then
        info "Removing symlink..."
        rm -f "$MDIFY_SYMLINK"
        success "Symlink removed"
    else
        info "Symlink not found: $MDIFY_SYMLINK"
    fi
    
    # Clean RC file (optional)
    echo ""
    RC_FILE=$(detect_shell_rc)
    if [ -n "$RC_FILE" ]; then
        clean_rc_file "$RC_FILE"
    fi
    
    # Remove installation directory
    echo ""
    info "Removing installation directory..."
    rm -rf "$MDIFY_HOME"
    success "Installation directory removed"
    
    # Final message
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Uninstallation Complete!            ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo ""
    echo "mdify has been successfully uninstalled."
    echo ""
    echo "If you want to reinstall, run:"
    echo "  curl -sSL https://raw.githubusercontent.com/tiroq/mdify/main/install.sh | bash"
    echo ""
}

# Run main
main
