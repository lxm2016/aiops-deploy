# -*- coding: utf-8 -*-
"""采集器包: 根据操作系统自动选择 Linux / Windows 采集器。"""
import platform


def get_collector():
    """根据当前操作系统返回对应的采集器实例。"""
    if platform.system() == "Windows":
        from .windows_collector import WindowsCollector
        return WindowsCollector()
    from .linux_collector import LinuxCollector
    return LinuxCollector()
