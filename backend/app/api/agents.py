"""Agent 分发接口 (夜莺模式):
- GET /api/agents/install.sh          Linux 一行命令安装脚本 (零依赖版)
- GET /api/agents/package/linux       Linux Agent 安装包 (tar.gz, 内置便携Python)
- GET /api/agents/package/windows     Windows Agent 安装包 (zip, 内置便携Python)
- GET /api/agents/install.bat         Windows 安装脚本 (GBK 编码)

安装脚本会根据请求的 Host 自动生成, 实现:
  curl -sSfL 'http://IP:8080/api/agents/install.sh' | sudo bash -s -- --server 'http://IP:8080'
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, FileResponse, Response

from app.core.config import get_settings

# 复用构建脚本中的安装脚本模板
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from build_agent_packages import render_install_sh, install_bat_bytes  # noqa: E402

router = APIRouter(prefix="/api/agents", tags=["agents"])
settings = get_settings()

# 安装包存放目录: backend/packages/
PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent / "packages"


def _base_url(request: Request) -> str:
    """根据请求来源推断平台访问地址 (优先用客户端传入的 --server)。"""
    host = request.headers.get("host", "PLATFORM_IP:8080")
    return f"http://{host}"


@router.get("/install.sh", response_class=PlainTextResponse)
async def install_sh(request: Request):
    """生成 Linux 一键安装脚本 (零依赖版, 内置便携Python)。用法:
    curl -sSfL 'http://IP:8080/api/agents/install.sh' | sudo bash -s -- --server 'http://IP:8080'
    """
    script = render_install_sh(
        default_server=_base_url(request),
        token=settings.agent_token,
    )
    return PlainTextResponse(script, media_type="text/x-shellscript")


@router.get("/package/linux")
async def package_linux():
    """下载 Linux Agent 安装包 (内置便携Python+psutil)。"""
    pkg = PACKAGE_DIR / "aiops-agent-linux.tar.gz"
    if not pkg.exists():
        return PlainTextResponse("安装包不存在, 请先运行 build_agent_packages 生成", status_code=404)
    return FileResponse(pkg, filename="aiops-agent-linux.tar.gz", media_type="application/gzip")


@router.get("/package/windows")
async def package_windows():
    """下载 Windows Agent 安装包 (内置便携Python+psutil)。"""
    pkg = PACKAGE_DIR / "aiops-agent-windows.zip"
    if not pkg.exists():
        return PlainTextResponse("安装包不存在, 请先运行 build_agent_packages 生成", status_code=404)
    return FileResponse(pkg, filename="aiops-agent-windows.zip", media_type="application/zip")


@router.get("/install.bat")
async def install_bat(request: Request):
    """Windows 安装脚本 (GBK 编码, CMD 直接运行不乱码; 安装包内也内置一份)。"""
    bat = install_bat_bytes(
        default_server=_base_url(request),
        token=settings.agent_token,
    )
    return Response(content=bat, media_type="text/plain")
