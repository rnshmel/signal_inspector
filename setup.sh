#!/bin/bash

# This ensures the script works regardless of where it is called from
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the script's directory so all relative paths work
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQ_FILE="requirements.txt"
EXAMPLES_DIR="example_signals"

# Function to show help
show_help() {
    echo "Usage: ./setup.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help      Show this help message and exit."
    echo "  -c, --clean     Clean install of the virtual environment (removes existing '$VENV_DIR' and '$EXAMPLES_DIR/')."
    echo "  -e, --examples  Create '$EXAMPLES_DIR/' directory and generate example IQ files."
    echo "  -w, --wsl       Install extra dependencies required for WSL / Qt (TBD)."
}

# Argument Parsing
CLEAN=false
EXAMPLES=false
WSL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -c|--clean)
            CLEAN=true
            shift
            ;;
        -e|--examples)
            EXAMPLES=true
            shift
            ;;
        -w|--wsl)
            WSL=true
            shift
            ;;
        *)
            echo "Error: Unknown option '$1'"
            show_help
            exit 1
            ;;
    esac
done

# Clean existing environment and examples if requested
if [ "$CLEAN" = true ]; then
    if [ -d "$VENV_DIR" ]; then
        echo "--- Removing existing virtual environment ($VENV_DIR) ---"
        rm -rf "$VENV_DIR"
    fi
    if [ -d "$EXAMPLES_DIR" ]; then
        echo "--- Removing existing examples directory ($EXAMPLES_DIR) ---"
        rm -rf "$EXAMPLES_DIR"
    fi
fi

# Install extra WSL dependencies if requested
if [ "$WSL" = true ]; then
    echo "--- Installing extra WSL dependencies for Qt (TBD) ---"
    # TODO: Add WSL/Qt system or python dependencies here
fi

# Check or create virtual environment
if [ -d "$VENV_DIR" ]; then
    echo "--- Virtual environment ($VENV_DIR) already exists. ---"
    if [ "$EXAMPLES" = false ]; then
        exit 0
    fi
    source "$VENV_DIR/bin/activate"
else
    # Select Python interpreter
    PREFERRED_VERSIONS=("python3.13" "python3.12" "python3.11" "python3.10" "python3")
    PYTHON_CMD=""

    for ver in "${PREFERRED_VERSIONS[@]}"; do
        if command -v "$ver" &> /dev/null && "$ver" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" &> /dev/null; then
            PYTHON_CMD="$ver"
            echo "--- Selected Python interpreter: $PYTHON_CMD ---"
            break
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo "Error: Could not find a valid Python 3.10+ interpreter."
        exit 1
    fi

    echo "--- Checking system dependencies (venv and Qt6 libraries) ---"
    MISSING_PKGS=()

    if ! "$PYTHON_CMD" -c "import venv, ensurepip" &> /dev/null; then
        MISSING_PKGS+=("${PYTHON_CMD}-venv")
    fi

    if [[ "$(uname -s)" == "Linux" ]]; then
        LDCONFIG_CMD="$(command -v ldconfig || command -v /sbin/ldconfig || command -v /usr/sbin/ldconfig || true)"
        if [ -n "$LDCONFIG_CMD" ]; then
            LD_CACHE="$("$LDCONFIG_CMD" -p 2>/dev/null)"
            QT_SYS_LIBS=(
                "libxcb-cursor.so.0:libxcb-cursor0"
                "libxkbcommon-x11.so.0:libxkbcommon-x11-0"
                "libxcb-icccm.so.4:libxcb-icccm4"
                "libxcb-image.so.0:libxcb-image0"
                "libxcb-keysyms.so.1:libxcb-keysyms1"
                "libxcb-render-util.so.0:libxcb-render-util0"
                "libxcb-xkb.so.1:libxcb-xkb1"
                "libGL.so.1:libgl1"
                "libEGL.so.1:libegl1"
            )
            for entry in "${QT_SYS_LIBS[@]}"; do
                lib_name="${entry%%:*}"
                pkg_name="${entry##*:}"
                if ! grep -q "$lib_name" <<< "$LD_CACHE"; then
                    MISSING_PKGS+=("$pkg_name")
                fi
            done
        fi
    fi

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "Error: Missing required system dependencies: ${MISSING_PKGS[*]}"
        echo "On Debian/Ubuntu/Xubuntu systems, install them manually:"
        echo "  sudo apt install ${MISSING_PKGS[*]}"
        exit 1
    fi

    echo "--- Creating new virtual environment ($VENV_DIR) ---"
    # If the creation fails we need to clean up the partially created directory
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "Error: Failed to create venv using $PYTHON_CMD. Cleaning up."
        rm -rf "$VENV_DIR"
        exit 1
    fi

    source "$VENV_DIR/bin/activate"

    echo "--- Upgrading pip and build tools ---"
    if ! pip install --upgrade pip setuptools wheel; then
        echo "Error: Pip upgrade failed. Cleaning up."
        deactivate
        rm -rf "$VENV_DIR"
        exit 1
    fi

    if [ -f "$REQ_FILE" ]; then
        echo "--- Installing dependencies from $REQ_FILE ---"
        if ! pip install -r "$REQ_FILE"; then
            echo "Error: Dependency installation failed. Cleaning up."
            deactivate
            rm -rf "$VENV_DIR"
            exit 1
        fi
    fi
fi

# Generate example IQ files if requested
if [ "$EXAMPLES" = true ]; then
    if [ ! -d "$EXAMPLES_DIR" ]; then
        echo "--- Creating examples directory ($EXAMPLES_DIR) ---"
        mkdir -p "$EXAMPLES_DIR"
    fi
    export PYTHONPATH=$PWD
    echo "--- Generating example IQ files in '$EXAMPLES_DIR/' ---"
    if ! python utils/generate_example_signals.py; then
        echo "Error: Failed to generate example IQ files."
        exit 1
    fi
fi
