#!/bin/bash

# This ensures the script works regardless of where it is called from.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the script's directory so all relative paths work
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQ_FILE="requirements.txt"
APPS_DIR="apps"

# Function to show help
show_help() {
    echo "Usage: ./run.sh [APP_NAME]"
    echo ""
    echo "Arguments:"
    echo "  APP_NAME    The name of the python script in '$APPS_DIR/' to run."
    echo "              (e.g., 'basic_signal_inspector.py')"
    echo ""
    echo "Options:"
    echo "  --help      Show this help message."
    echo ""
    echo "Available Apps:"
    if [ -d "$APPS_DIR" ]; then
        ls "$APPS_DIR"/*.py | xargs -n 1 basename | sed 's/^/  - /'
    else
        echo "  (No apps directory found)"
    fi
}

# Argument Parsing
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    show_help
    exit 0
fi

if [ -z "$1" ]; then
    echo "Error: No app specified."
    show_help
    exit 1
fi

TARGET_App="$1"
TARGET_PATH="$APPS_DIR/$TARGET_App"

# Handle case where user omits .py extension
if [ ! -f "$TARGET_PATH" ] && [ -f "${TARGET_PATH}.py" ]; then
    TARGET_PATH="${TARGET_PATH}.py"
fi

if [ ! -f "$TARGET_PATH" ]; then
    echo "Error: Could not find app '$TARGET_App' in '$APPS_DIR/'"
    exit 1
fi

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

# 4. Setup/check venv
if [ ! -d "$VENV_DIR" ]; then
    echo "--- Creating new virtual environment ($VENV_DIR) ---"
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "Error: Failed to create venv using $PYTHON_CMD."
        exit 1
    fi

    # Activate
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
else
    # Exit
    source "$VENV_DIR/bin/activate"
fi

# Start
echo "--- Launching $TARGET_App ---"

# PYTHONPATH needs to be the script directory (which we CD into).
export PYTHONPATH=$PWD

python "$TARGET_PATH"
