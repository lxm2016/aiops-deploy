@echo off
setlocal enabledelayedexpansion
REM AIOps采集Agent - Windows一键安装脚本 (零依赖版, 安装包内置便携Python)
REM 用法: install_agent_windows.bat <平台服务器地址>
REM 例如: install_agent_windows.bat http://192.168.1.100:8080
REM       install_agent_windows.bat 192.168.1.100   (默认端口8080)

if "%~1"=="" (
    echo 用法: install_agent_windows.bat ^<平台服务器地址^>
    echo 例如: install_agent_windows.bat http://192.168.1.100:8080
    pause
    exit /b 1
)

set ARG=%~1
if "!ARG:~0,4!"=="http" (
    set SERVER=!ARG!
) else (
    set PORT=%~2
    if "!PORT!"=="" set PORT=8080
    set SERVER=http://!ARG!:!PORT!
)

set DEPLOY_DIR=%~dp0..
set PKG=%DEPLOY_DIR%\backend\packages\aiops-agent-windows.zip
if not exist "%PKG%" (
    echo [错误] 未找到安装包: %PKG%
    pause
    exit /b 1
)

echo =====================================================
echo   AIOps Agent 安装 (零依赖版, 服务端: !SERVER!)
echo =====================================================

set TMP=%TEMP%\aiops-agent-install-%RANDOM%
mkdir "%TMP%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%PKG%' -DestinationPath '%TMP%' -Force"
copy /y "%PKG%" "%TMP%\aiops-agent\" >nul

set AIOPS_SERVER=!SERVER!
call "%TMP%\aiops-agent\install.bat"

rmdir /s /q "%TMP%" >nul 2>&1
pause
