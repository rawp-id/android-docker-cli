#!/bin/bash

# Android Permission Fix Test Runner

echo "=========================================="
echo "Android Permission Fix - Test Suite"
echo "=========================================="
echo ""

# Run property tests and unit tests
echo "1. Running property tests and unit tests..."
python -m pytest tests/test_android_permissions.py -v

if [ $? -ne 0 ]; then
    echo "❌ Property tests failed"
    exit 1
fi

echo ""
echo "✅ All property tests passed"
echo ""

# Run integration tests (optional, as it requires pulling real images)
echo "2. Running integration tests (optional)..."
echo "   Note: Integration tests will pull real images and may take a long time"
read -p "   Run integration tests? (y/N) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    python -m pytest tests/test_android_integration.py -v -s
    
    if [ $? -ne 0 ]; then
        echo "❌ Integration tests failed"
        exit 1
    fi
    
    echo ""
    echo "✅ All integration tests passed"
fi

echo ""
echo "=========================================="
echo "Testing complete!"
echo "=========================================="
