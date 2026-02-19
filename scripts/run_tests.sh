#!/bin/bash
#
# Run all automated tests for the project.
#

# Get the directory where the script is located
SCRIPT_DIR=$(dirname "$0")
# Change to project root directory
cd "$SCRIPT_DIR/.."

echo "======================================="
echo "Running all tests..."
echo "======================================="

# Add project root directory to PYTHONPATH and run tests using unittest discover
export PYTHONPATH=$(pwd)
python3 -m unittest discover tests

if [ $? -ne 0 ]; then
    echo "Tests failed!"
    exit 1
fi

echo ""
echo "All tests passed successfully!"
exit 0