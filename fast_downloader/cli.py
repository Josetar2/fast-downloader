"""命令行入口：python -m fast_downloader.cli <URL> [-o 保存目录] [-n 文件名] [-t 线程数]"""

from __future__ import annotations

import argparse
import sys
import time

from .core import DEFAULT_THREADS, MAX_THREADS, Downloader, DownloadError


def _fmt_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024


def _fmt_speed(n: float) -> str:
    return f"{_fmt_size(n)}/s"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="多线程高速下载器（独立版）"
    )
    p.add_argument("url", help="下载地址")
    p.add_argument("-o", "--output", default=".", help="保存目录（默认当前目录）")
    p.add_argument("-n", "--name", default=None, help="文件名（默认从 URL 推断）")
    p.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS,
                   help=f"线程数（默认 {DEFAULT_THREADS}，上限 {MAX_THREADS}；"
                        f"实际分块数会按文件大小自动收敛）")
    args = p.parse_args(argv)

    dl = Downloader(args.url, args.output, filename=args.name, threads=args.threads)
    try:
        dl.prepare()
        total, ranged = dl.probe()
    except DownloadError as e:
        print(f"解析失败：{e}", file=sys.stderr)
        return 1

    print(f"文件：{dl.filename}")
    if dl.resolve_note:
        print(f"解析：{dl.resolve_note}")
    print(f"大小：{_fmt_size(total) if total else '未知'}")
    print(f"分块：{'支持（%d 线程）' % dl.threads if ranged else '不支持，降级单线程'}")

    start = time.time()
    try:
        # 速度直接用回调给的第三个参数：再调 dl.speed() 会把上一段增量清零，
        # 进度条上的速度会永远显示 0
        path = dl.download(on_progress=lambda d, t, sp: _render(d, t, sp))
    except DownloadError as e:
        print(f"\n下载失败：{e}", file=sys.stderr)
        return 1

    _render(dl.total or dl._downloaded, dl.total or dl._downloaded, 0)
    print(f"\n完成：{path}  用时 {time.time() - start:.1f}s")
    return 0


def _render(d: int, t: int, speed: float) -> None:
    pct = (d / t * 100) if t else 0
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "─" * (bar_len - filled)
    sys.stdout.write(
        f"\r[{bar}] {pct:5.1f}%  {_fmt_size(d)}/{_fmt_size(t)}  {_fmt_speed(speed)}"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
