@echo off
chcp 65001 >nul
pushd "%~dp0"
python scripts\dev.py %*
set EXIT_CODE=%ERRORLEVEL%
popd
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
