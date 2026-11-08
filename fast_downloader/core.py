"""
Fast Downloader — 核心下载引擎（纯标准库，无第三方依赖）

高速多线程下载能力：
- 支持 HTTP Range 分块多线程下载
- 不支持 Range 的服务器自动降级为单线程流式下载
- 断点续传（已下载的 part 文件会被复用）
- 实时进度回调（已下载字节 / 总字节 / 速度）
"""

from __future__ import annotations

import math
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import netdisk

DEFAULT_UA = "FastDownloader/1.0 (+https://github.com/)"
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024  # 1 MiB 读取缓冲


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def _open(url: str, headers: dict, timeout: int, method: str = "GET"):
    req = urllib.request.Request(url, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


class Downloader:
    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: str | None = None,
        threads: int = 16,
        timeout: int = 30,
        retries: int = 5,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self.url = url
        self.save_dir = save_dir
        self.filename = filename or self._guess_filename(url)
        self.threads = max(1, int(threads))
        self.timeout = timeout
        self.retries = retries

        self.filepath = os.path.join(save_dir, self.filename)
        self.part_dir = self.filepath + ".parts"
        self.total = 0
        self.supports_range = False
        self._ua = user_agent
        self.effective_url = url
        self.extra_headers = {}

        self._downloaded = 0
        self._lock_state = {"start": time.time(), "last": time.time(), "last_bytes": 0}
        self.cancelled = False

    # ---------- 工具 ----------
    @staticmethod
    def _guess_filename(url: str) -> str:
        path = url.split("?")[0].split("#")[0].rstrip("/")
        name = path.split("/")[-1]
        return name or "download.bin"

    @staticmethod
    def _safe_name(name: str) -> str:
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        return name.strip() or "download.bin"

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": self._ua}
        h.update(self.extra_headers)
        if extra:
            h.update(extra)
        return h

    def _part_path(self, idx: int) -> str:
        return os.path.join(self.part_dir, f"part.{idx}")

    # ---------- 探测 ----------
    def probe(self) -> tuple[int, bool]:
        length, accept = 0, ""
        try:
            with _open(self.effective_url, self._headers(), self.timeout, method="HEAD") as r:
                length = int(r.headers.get("Content-Length", "0") or 0)
                accept = (r.headers.get("Accept-Ranges", "") or "").lower()
        except Exception:
            length, accept = 0, ""

        if not (length and accept == "bytes"):
            try:
                with _open(
                    self.effective_url,
                    self._headers({"Range": "bytes=0-0"}),
                    self.timeout,
                    method="GET",
                ) as r:
                    cr = r.headers.get("Content-Range", "")
                    if cr and "/" in cr:
                        length = int(cr.split("/")[-1])
                        accept = "bytes"
            except Exception:
                pass

        self.total = length
        self.supports_range = accept == "bytes"
        return self.total, self.supports_range

    # ---------- 进度 ----------
    def _bump(self, n: int) -> None:
        self._downloaded += n

    def _snapshot_speed(self) -> float:
        now = time.time()
        st = self._lock_state
        dt = now - st["last"]
        if dt <= 0:
            return 0.0
        speed = (self._downloaded - st["last_bytes"]) / dt
        st["last"], st["last_bytes"] = now, self._downloaded
        return speed

    def speed(self) -> float:
        return self._snapshot_speed()

    # ---------- 单块下载 ----------
    def _download_chunk(self, idx: int, start: int, end: int) -> int:
        part = self._part_path(idx)
        expected = end - start + 1
        if self.cancelled:
            raise Cancelled()
        if os.path.exists(part) and os.path.getsize(part) == expected:
            self._bump(expected)
            return expected

        last_end = start - 1
        for attempt in range(1, self.retries + 1):
            try:
                with _open(
                    self.effective_url,
                    self._headers({"Range": f"bytes={last_end + 1}-{end}"}),
                    self.timeout,
                    method="GET",
                ) as r:
                    mode = "ab" if (last_end + 1) > start else "wb"
                    with open(part, mode) as f:
                        while True:
                            buf = r.read(DEFAULT_CHUNK_SIZE)
                            if not buf:
                                break
                            f.write(buf)
                            last_end += len(buf)
                            self._bump(len(buf))
                            if self.cancelled:
                                raise Cancelled()
                return last_end - start + 1
            except Exception as e:
                if attempt == self.retries:
                    raise DownloadError(
                        f"分块 {idx} 下载失败（已重试 {self.retries} 次）: {e}"
                    )
                time.sleep(min(2 ** attempt, 8))
        return last_end - start + 1

    # ---------- 合并 ----------
    def _merge(self) -> None:
        with open(self.filepath, "wb") as out:
            for idx in range(self.threads):
                p = self._part_path(idx)
                if not os.path.exists(p):
                    raise DownloadError(f"分块文件缺失：{p}")
                with open(p, "rb") as f:
                    while True:
                        buf = f.read(DEFAULT_CHUNK_SIZE)
                        if not buf:
                            break
                        out.write(buf)

    # ---------- 主流程 ----------
    def download(self, on_progress=None) -> str:
        os.makedirs(self.save_dir, exist_ok=True)
        os.makedirs(self.part_dir, exist_ok=True)
        self.filename = self._safe_name(self.filename)

        # 网盘分享链接解析（蓝奏云等）：先解析成真实直链再下载
        if netdisk.is_supported(self.url):
            try:
                resolved = netdisk.resolve(self.url)
            except netdisk.NetdiskResolveError as e:
                raise DownloadError(f"网盘链接解析失败：{e}")
            if resolved:
                self.effective_url = resolved["url"]
                self.extra_headers = resolved.get("headers", {})
                self.filename = self._safe_name(self._guess_filename(resolved["url"]))

        total, ranged = self.probe()

        if total and os.path.exists(self.filepath) and os.path.getsize(self.filepath) == total:
            if on_progress:
                on_progress(total, total, 0.0)
            return self.filepath

        self._downloaded = 0
        self._lock_state = {"start": time.time(), "last": time.time(), "last_bytes": 0}
        self.cancelled = False

        done_ev = threading.Event()

        def _monitor() -> None:
            while not done_ev.is_set():
                if on_progress:
                    on_progress(self._downloaded, self.total, self._snapshot_speed())
                time.sleep(0.2)

        mon = threading.Thread(target=_monitor, daemon=True)
        mon.start()
        try:
            if ranged and total:
                ranges = self._split_ranges(total, self.threads)
                self.threads = len(ranges)
                with ThreadPoolExecutor(max_workers=self.threads) as ex:
                    futs = [ex.submit(self._download_chunk, i, s, e) for i, (s, e) in enumerate(ranges)]
                    for fut in as_completed(futs):
                        fut.result()
                self._merge()
            else:
                self._download_single()
        finally:
            done_ev.set()
            mon.join(timeout=1)

        self._cleanup_parts()
        done = self.total or self._downloaded
        if on_progress:
            on_progress(done, done, 0.0)
        return self.filepath

    def cancel(self) -> None:
        self.cancelled = True

    def _download_single(self) -> None:
        part = self._part_path(0)
        if self.cancelled:
            raise Cancelled()
        resume = os.path.exists(part) and os.path.getsize(part) > 0
        headers = {}
        if resume:
            headers["Range"] = f"bytes={os.path.getsize(part)}-"
        with _open(self.effective_url, self._headers(headers), self.timeout, method="GET") as r:
            cr = r.headers.get("Content-Range", "")
            if cr and "/" in cr and self.total == 0:
                self.total = int(cr.split("/")[-1])
            mode = "ab" if resume else "wb"
            with open(part, mode) as f:
                while True:
                    buf = r.read(DEFAULT_CHUNK_SIZE)
                    if not buf:
                        break
                    f.write(buf)
                    self._bump(len(buf))
                    if self.cancelled:
                        raise Cancelled()
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
        os.rename(part, self.filepath)
        _rmdir(self.part_dir)

    @staticmethod
    def _split_ranges(total: int, threads: int) -> list[tuple[int, int]]:
        threads = max(1, min(threads, total))
        base = total // threads
        rem = total % threads
        ranges = []
        cur = 0
        for i in range(threads):
            span = base + (1 if i < rem else 0)
            if span <= 0:
                break
            ranges.append((cur, cur + span - 1))
            cur += span
        return ranges

    def _cleanup_parts(self) -> None:
        for i in range(self.threads):
            p = self._part_path(i)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        _rmdir(self.part_dir)


def _rmdir(path: str) -> None:
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass
