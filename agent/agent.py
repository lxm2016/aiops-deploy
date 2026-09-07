#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIOps 跨平台监控 Agent 主程序

功能:
    - 定时采集本机 CPU / 内存 / 磁盘 / 网络 / 端口 / 服务信息
    - 以 JSON 格式 POST 上报到服务端 /api/servers/report 接口
    - 请求头携带 X-Agent-Token 用于身份校验

支持平台:
    - Linux:   CentOS / openEuler / Rocky Linux / Ubuntu / 龙蜥(Anolis OS)
    - Windows: Windows Server 2008 ~ 2019

用法:
    python3 agent.py                          # 使用脚本同目录下的 config.yaml
    python3 agent.py -c /etc/aiops/config.yaml
    python3 agent.py --once                   # 只采集上报一次(调试用)
"""
import argparse
import json
import logging
import os
import signal
import threading
import time
import urllib.error
import urllib.request

from collectors import get_collector

try:
    import yaml  # 可选依赖: 有则用yaml解析, 没有则用内置简易解析器
except ImportError:
    yaml = None

# 停止标志: 收到 SIGINT/SIGTERM 后置位, 主循环优雅退出
stop_event = threading.Event()


def _handle_signal(signum, frame):
    """信号处理: 收到终止信号后通知主循环退出。"""
    logging.info("收到终止信号 %s, 准备退出...", signum)
    stop_event.set()


def _simple_yaml_load(text):
    """极简YAML解析器(仅支持本项目config.yaml的两层 key: value 结构)。
    在目标机器没有安装 PyYAML 时使用, 避免额外依赖。"""
    result = {}
    current = None
    for raw in text.splitlines():
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip().strip('"').strip("'")
        if indent == 0:
            if value == "":
                result[key] = {}
                current = result[key]
            else:
                result[key] = value
                current = None
        else:
            if current is not None:
                # 尝试转数字
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                current[key] = value
    return result


def load_config(path):
    """加载 YAML 配置文件, 文件缺失或字段缺失时使用内置默认值。"""
    cfg = {
        "server": {
            "url": "http://SERVER:8080/api/servers/report",
            "token": "aiops-agent-shared-token",
        },
        "agent": {
            "interval": 5,    # 采集/上报间隔(秒)
            "timeout": 10,    # HTTP 请求超时(秒)
        },
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        user_cfg = yaml.safe_load(text) if yaml else _simple_yaml_load(text)
        user_cfg = user_cfg or {}
        for section, values in user_cfg.items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
    except FileNotFoundError:
        logging.warning("未找到配置文件 %s, 使用默认配置", path)
    except Exception as e:
        logging.error("配置文件 %s 解析失败: %s", path, e)
    return cfg


def report(url, token, timeout, payload):
    """将采集数据 POST 上报到服务端, 请求头携带 X-Agent-Token。
    使用标准库 urllib, 零第三方网络依赖。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-Agent-Token": token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        return status


def main():
    parser = argparse.ArgumentParser(description="AIOps 跨平台监控 Agent")
    parser.add_argument(
        "-c", "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
        help="配置文件路径(默认: 脚本同目录下的 config.yaml)",
    )
    parser.add_argument("--once", action="store_true", help="只采集上报一次后退出(调试用)")
    parser.add_argument("--server", help="平台地址, 如 http://172.16.10.147:8080 (优先级高于配置文件)")
    parser.add_argument("--token", help="Agent令牌 (优先级高于配置文件)")
    parser.add_argument("--interval", type=int, help="采集间隔秒数 (优先级高于配置文件)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cfg = load_config(args.config)
    url = cfg["server"]["url"]
    token = str(cfg["server"]["token"])
    interval = max(5, int(cfg["agent"]["interval"]))  # 间隔最小 5 秒, 防止配置错误打爆服务端
    timeout = int(cfg["agent"]["timeout"])

    # 命令行参数优先于配置文件
    if args.server:
        base = args.server.rstrip("/")
        url = base + "/api/servers/report" if "/api/" not in base else base
    if args.token:
        token = args.token
    if args.interval:
        interval = max(5, args.interval)

    # 容错: 配置/命令行漏写 http:// 前缀时自动补上
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # 根据当前操作系统自动选择采集器
    collector = get_collector()
    logging.info(
        "Agent 启动 | 平台=%s | 上报地址=%s | 间隔=%ss",
        collector.os_type, url, interval,
    )

    while not stop_event.is_set():
        start = time.time()
        try:
            payload = collector.collect()
            status = report(url, token, timeout, payload)
            logging.info(
                "上报成功: HTTP %s | cpu=%.1f%% mem=%.1f%% disk=%.1f%% rx=%.2fMbps tx=%.2fMbps",
                status,
                payload["cpu_percent"], payload["mem_percent"], payload["disk_percent"],
                payload["net_rx_mbps"], payload["net_tx_mbps"],
            )
        except (urllib.error.URLError, OSError) as e:
            logging.error("上报失败: %s", e)
        except Exception:
            logging.exception("采集/上报过程发生异常")

        if args.once:
            break

        # 按 1 秒步长休眠, 保证能及时响应终止信号
        deadline = start + interval
        while not stop_event.is_set() and time.time() < deadline:
            stop_event.wait(1)

    logging.info("Agent 已退出")


if __name__ == "__main__":
    main()
