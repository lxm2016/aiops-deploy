@echo off
chcp 65001 >nul
echo =====================================================
echo   AIOps平台 - 启动后端服务 (端口8080)
echo =====================================================
cd /d %~dp0..\backend
if not exist venv (
    echo [错误] 未安装，请先运行 install_backend_windows.bat
    pause
    exit /b 1
)
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
pause
