@echo off
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行：启动系统.cmd --install
  pause
  popd
  exit /b 1
)
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" backend\training.py --group-splits %*
set EXIT_CODE=%ERRORLEVEL%
popd
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
