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
    PREFERRED_VERSIONS=("python3.11" "python3.10" "python3.9" "python3.8" "python3")
    PYTHON_CMD=""

    for ver in "${PREFERRED_VERSIONS[@]}"; do
        if command -v "$ver" &> /dev/null; then
            PYTHON_CMD="$ver"
            echo "--- Selected Python interpreter: $PYTHON_CMD ---"
            break
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo "Error: Could not find a valid Python 3 interpreter."
        exit 1
    fi

    echo "--- Checking if the 'venv' module is available ---"
    if ! "$PYTHON_CMD" -c "import venv" &> /dev/null; then
        echo "Error: The 'venv' module is not available for $PYTHON_CMD."
        echo "On Debian/Ubuntu systems, you might need to install it manually:"
        echo "  sudo apt install ${PYTHON_CMD}-venv"
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
