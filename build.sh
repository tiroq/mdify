#!/bin/bash
#
# Build script for mdify PyPI package
#
# Usage: ./build.sh [--upload-test] [--upload]
#

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Parse arguments
UPLOAD_TEST=false
UPLOAD_PROD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --upload-test)
            UPLOAD_TEST=true
            shift
            ;;
        --upload)
            UPLOAD_PROD=true
            shift
            ;;
        -h|--help)
            echo "Build script for mdify PyPI package"
            echo ""
            echo "Usage: ./build.sh [--upload-test] [--upload]"
            echo ""
            echo "Options:"
            echo "  --upload-test  Upload to TestPyPI after building"
            echo "  --upload       Upload to PyPI after building"
            echo "  -h, --help     Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

cd "$(dirname "$0")"

info "Creating temporary build environment..."
python3 -m venv .build_env
source .build_env/bin/activate

info "Installing build tools..."
pip install --upgrade pip build twine -q

info "Cleaning previous builds..."
rm -rf build/ dist/ *.egg-info

info "Building package..."
python -m build

success "Build complete!"

# List built files
echo ""
info "Built files:"
ls -lh dist/

# Check package
echo ""
info "Checking package with twine..."
python -m twine check dist/*

# Upload to TestPyPI if requested
if [ "$UPLOAD_TEST" = true ]; then
    echo ""
    warn "Uploading to TestPyPI..."
    echo "You will be prompted for credentials (use __token__ as username)"
    python -m twine upload --repository testpypi dist/*
    success "Uploaded to TestPyPI"
    echo ""
    echo "Test installation with:"
    echo "  pip install --index-url https://test.pypi.org/simple/ --no-deps mdify"
fi

# Upload to PyPI if requested
if [ "$UPLOAD_PROD" = true ]; then
    echo ""
    warn "Uploading to PyPI..."
    read -p "Are you sure you want to upload to production PyPI? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python -m twine upload dist/*
        success "Uploaded to PyPI"
        echo ""
        echo "Install with:"
        echo "  pip install mdify"
    else
        echo "Upload cancelled."
    fi
fi

# Cleanup
deactivate
rm -rf .build_env

echo ""
success "Done!"

if [ "$UPLOAD_TEST" = false ] && [ "$UPLOAD_PROD" = false ]; then
    echo ""
    echo "To upload to TestPyPI: ./build.sh --upload-test"
    echo "To upload to PyPI:     ./build.sh --upload"
fi
