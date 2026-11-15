#!/bin/bash

# This ensures the script works regardless of where it is called from
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the script's directory so all relative paths work
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
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
    echo "  -h, --help  Show this help message."
    echo ""
    echo "Available Apps:"
    if [ -d "$APPS_DIR" ]; then
        ls "$APPS_DIR"/*.py 2>/dev/null | xargs -n 1 basename | sed 's/^/  - /' || echo "  (No python apps found in $APPS_DIR)"
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
    show_help
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment ($VENV_DIR) not found."
    echo "Please run './setup.sh' first to set up the environment."
    exit 1
fi

source "$VENV_DIR/bin/activate"

echo "--- Launching $TARGET_App ---"

export PYTHONPATH=$PWD

python "$TARGET_PATH"
