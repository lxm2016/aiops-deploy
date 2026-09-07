@echo off
setlocal enabledelayedexpansion
title AIOps Agent 安装

REM ============================================================
REM  AIOps Agent 一键安装 (Windows 零依赖版)
REM  内置便携 Python 运行时, 无需预装 Python
REM  解压本压缩包后, 双击运行本文件, 输入平台地址即可
REM ============================================================

set SERVER=
set TOKEN=aiops-agent-shared-token
set INTERVAL=5
if defined AIOPS_SERVER set SERVER=%AIOPS_SERVER%

echo ============================================================
echo   AIOps Agent 安装 (Windows 零依赖版)
echo ============================================================
echo.
if "!SERVER!"=="" (
    echo   示例平台地址: http://172.16.10.147
    echo.
    set /p SERVER="请输入平台地址: "
)
if "!SERVER!"=="" (
    echo [错误] 平台地址不能为空
    pause
    exit /b 1
)
if /i not "!SERVER:~0,4!"=="http" set SERVER=http://!SERVER!

echo 平台地址: !SERVER!
echo 采集间隔: !INTERVAL!s
echo.

cd /d "%~dp0"
set PY=%~dp0python\python.exe
set PYW=%~dp0python\pythonw.exe

REM 检查内置 Python 运行时, 缺失则回退系统 python
if not exist "%PY%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 内置 Python 运行时缺失, 且系统未安装 Python
        pause
        exit /b 1
    )
    set PY=python
    set PYW=pythonw
    echo [警告] 内置运行时缺失, 回退使用系统 Python
)

for %%I in ("%PY%") do echo [OK] Python 运行时: %%~fI

echo [1/4] 写入配置...
(
echo server:
echo   url: "!SERVER!/api/servers/report"
echo   token: "!TOKEN!"
echo agent:
echo   interval: !INTERVAL!
echo   timeout: 10
) > "%~dp0config.yaml"

echo [2/4] 测试采集并上报一次...
"%PY%" agent.py --once
if errorlevel 1 (
    echo [警告] 测试上报失败, 请检查平台地址与网络, Agent 仍会按配置继续重试
)

echo [3/4] 设置开机自启...
schtasks /delete /tn "AIOpsAgent" /f >nul 2>&1
schtasks /create /tn "AIOpsAgent" /tr "\"!PYW!\" \"%~dp0agent.py\"" /sc onstart /ru SYSTEM /rl highest /f

echo [4/4] 启动 Agent...
REM 先终止旧 Agent 进程, 避免重复运行
wmic process where "name='pythonw.exe' and commandline like '%%agent.py%%'" call terminate >nul 2>&1
timeout /t 1 /nobreak >nul
start "" "%PYW%" "%~dp0agent.py"

echo.
echo ============================================================
echo   安装完成! Agent 已在后台运行并设置开机自启。
echo   可到平台 "服务器管理" 页面查看本机上线情况。
echo ============================================================
pause
