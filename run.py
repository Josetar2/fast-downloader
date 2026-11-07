#!/usr/bin/env python
"""统一入口：无参数启动图形界面，带参数走命令行。"""

from __future__ import annotations

import sys

from pcl_fast_downloader import cli, gui


def main() -> int:
    if len(sys.argv) > 1:
        return cli.main()
    gui.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
