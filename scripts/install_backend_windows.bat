@echo off
chcp 65001 >nul
echo =====================================================
echo   AIOps平台 - Windows后端 一键安装
echo =====================================================
echo.

set DEPLOY_DIR=%~dp0..
set BACKEND_DIR=%DEPLOY_DIR%\backend
set PKG_DIR=%DEPLOY_DIR%\packages\windows

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装 packages\python-3.11.9-amd64.exe
    echo 安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/3] 创建虚拟环境...
cd /d %BACKEND_DIR%
python -m venv venv

echo [2/3] 离线安装依赖...
venv\Scripts\python.exe -m pip install --no-index --find-links=%PKG_DIR% -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [3/3] 安装完成!
echo.
echo 启动方式: 运行 start_backend_windows.bat
pause
