@echo off
REM Android Permission Fix Test Runner (Windows)

echo ==========================================
echo Android Permission Fix - Test Suite
echo ==========================================
echo.

REM Run property tests and unit tests
echo 1. Running property tests and unit tests...
python -m pytest tests/test_android_permissions.py -v

if %ERRORLEVEL% NEQ 0 (
    echo ❌ Property tests failed
    exit /b 1
)

echo.
echo ✅ All property tests passed
echo.

REM Run integration tests (optional)
echo 2. Running integration tests (optional)...
echo    Note: Integration tests will pull real images and may take a long time
set /p REPLY="   Run integration tests? (y/N) "

if /i "%REPLY%"=="y" (
    python -m pytest tests/test_android_integration.py -v -s
    
    if %ERRORLEVEL% NEQ 0 (
        echo ❌ Integration tests failed
        exit /b 1
    )
    
    echo.
    echo ✅ All integration tests passed
)

echo.
echo ==========================================
echo Testing complete!
echo ==========================================
