#!/usr/bin/env python
"""统一入口：无参数启动图形界面，带参数走命令行。"""

from __future__ import annotations

import sys

# 高 DPI 屏适配：必须在导入 tkinter 之前设置进程 DPI 感知，
# 否则 Windows 会把 96DPI 渲染的位图拉伸放大 -> 窗口与系统对话框全糊。
try:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

from fast_downloader import cli, gui


def main() -> int:
    if len(sys.argv) > 1:
        return cli.main()
    gui.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
