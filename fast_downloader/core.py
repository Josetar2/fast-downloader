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
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import github, netdisk

DEFAULT_UA = "FastDownloader/1.0 (+https://github.com/)"
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024  # 1 MiB 读取缓冲

# 线程数：默认 16（一般带宽下已能跑满），上限 128（应对单连接被限速的网盘/CDN）。
DEFAULT_THREADS = 16
MAX_THREADS = 128
# 每个分块的最小字节数。线程数 = 分块数，块太小则「建立连接 + TLS 握手」
# 的开销会超过传输本身，也会让临时文件数量暴涨、合并变慢，因此按文件大小
# 自动收敛实际分块数（2 MB 以下不再切分）。
MIN_CHUNK_SIZE = 2 * 1024 * 1024


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


class _KeepMethodRedirect(urllib.request.HTTPRedirectHandler):
    """跟随 302 时保留原始请求方法。

    urllib 默认的 redirect_request 重建 Request 时没带 method，HEAD 会被悄悄
    改成 GET —— 结果是「探测文件大小」变成「真的开始下载整个文件」。GitHub 的
    下载链接全部靠 302 跳转，这个坑尤其明显，所以这里显式把方法传回去。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.method = req.get_method()
        return new


_OPENER = urllib.request.build_opener(_KeepMethodRedirect)


def _open(url: str, headers: dict, timeout: int, method: str = "GET"):
    req = urllib.request.Request(url, headers=headers, method=method)
    return _OPENER.open(req, timeout=timeout)


class Downloader:
    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: str | None = None,
        threads: int = DEFAULT_THREADS,
        timeout: int = 30,
        retries: int = 5,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self.url = url
        self.save_dir = save_dir
        # 没手动给文件名时记为「自动」，后面允许被 Content-Disposition /
        # GitHub 解析结果覆盖成真实文件名
        self._auto_name = not filename
        self.filename = filename or self._guess_filename(url)
        self.threads = max(1, min(int(threads), MAX_THREADS))
        self.timeout = timeout
        self.retries = retries

        self.filepath = os.path.join(save_dir, self.filename)
        self.part_dir = self.filepath + ".parts"
        self.total = 0
        self.supports_range = False
        self._ua = user_agent
        self.effective_url = url
        self.extra_headers = {}
        self._content_type = ""
        self.resolve_note = ""
        self._prepared = False

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
    @staticmethod
    def _filename_from_cd(cd: str) -> str | None:
        """从 Content-Disposition 里取服务端给的真实文件名。

        GitHub 的源码包地址（codeload.github.com/o/r/zip/refs/heads/main）路径
        末段只有分支名，不带扩展名；真实文件名藏在响应头里，不取就会存成一个
        没有后缀的 `main`。
        """
        if not cd:
            return None
        m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)?''([^;]+)", cd)
        if m:
            return urllib.parse.unquote(m.group(1).strip().strip('"'))
        m = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r"filename\s*=\s*([^;]+)", cd, re.I)
        return m.group(1).strip().strip('"') if m else None

    def _sync_paths(self) -> None:
        self.filepath = os.path.join(self.save_dir, self._safe_name(self.filename))
        self.filename = os.path.basename(self.filepath)
        self.part_dir = self.filepath + ".parts"

    def probe(self) -> tuple[int, bool]:
        # 探测只是"问问有多大"，不该让界面等太久。
        t_probe = min(self.timeout, 8)
        length, accept, ctype, cdisp = 0, "", "", ""
        unreachable = False
        try:
            with _open(self.effective_url, self._headers(), t_probe, method="HEAD") as r:
                length = int(r.headers.get("Content-Length", "0") or 0)
                accept = (r.headers.get("Accept-Ranges", "") or "").lower()
                ctype = (r.headers.get("Content-Type", "") or "").lower()
                cdisp = r.headers.get("Content-Disposition", "") or ""
        except urllib.error.HTTPError:
            pass          # 服务器不支持 HEAD，下面用 Range 再问一次
        except Exception:
            unreachable = True

        self._content_type = ctype
        name = self._filename_from_cd(cdisp)
        if name and self._auto_name:
            self.filename = name
            self._sync_paths()

        # 连都连不上，再探一次只是白等一个超时
        if not unreachable and not (length and accept == "bytes"):
            try:
                with _open(
                    self.effective_url,
                    self._headers({"Range": "bytes=0-0"}),
                    t_probe,
                    method="GET",
                ) as r:
                    cr = r.headers.get("Content-Range", "")
                    if cr and "/" in cr:
                        length = int(cr.split("/")[-1])
                        accept = "bytes"
                    # HEAD 不被支持时，这里也能顺手补到类型与文件名
                    self._content_type = self._content_type or (
                        r.headers.get("Content-Type", "") or "").lower()
                    if self._auto_name:
                        n2 = self._filename_from_cd(
                            r.headers.get("Content-Disposition", "") or "")
                        if n2:
                            self.filename = n2
                            self._sync_paths()
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

    def _explain(self, exc: Exception) -> str:
        """把底层网络异常翻译成人话；GitHub 域名有针对性提示。"""
        return github.describe_error(self.effective_url, exc) or str(exc)

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
            except Cancelled:
                raise
            except Exception as e:
                if attempt == self.retries:
                    raise DownloadError(
                        f"分块 {idx} 下载失败（已重试 {self.retries} 次）："
                        + self._explain(e))
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
    def prepare(self) -> None:
        """把「网页链接」解析成真实文件地址并确定文件名。

        GitHub 页面 / 蓝奏云分享页都属于这种情况：用户看到的是网页，
        下载器要的是带 302 跳转的真实文件地址。可重复调用（幂等）。
        """
        if self._prepared:
            return
        self._prepared = True
        if github.is_github(self.url):
            try:
                res = github.resolve(self.url)
            except github.GitHubResolveError as e:
                raise DownloadError(f"GitHub 链接解析失败：{e}")
            if res:
                self.effective_url = res["url"]
                if res.get("headers"):
                    self.extra_headers.update(res["headers"])
                self.resolve_note = res.get("note") or ""
                if res.get("filename") and self._auto_name:
                    self.filename = res["filename"]
        elif netdisk.is_supported(self.url):
            try:
                resolved = netdisk.resolve(self.url)
            except netdisk.NetdiskResolveError as e:
                raise DownloadError(f"网盘链接解析失败：{e}")
            if resolved:
                self.effective_url = resolved["url"]
                self.extra_headers = resolved.get("headers", {})
                self.resolve_note = "已解析网盘分享链接"
                if self._auto_name:
                    self.filename = self._guess_filename(resolved["url"])
        self._sync_paths()

    def download(self, on_progress=None) -> str:
        os.makedirs(self.save_dir, exist_ok=True)
        self.prepare()
        total, ranged = self.probe()

        # 网页地址不是文件：直接下一个 .html 只会让人困惑，这里明确拦下来
        if self._content_type.startswith("text/html"):
            low = self.filename.lower()
            if not low.endswith((".html", ".htm")):
                hint = ""
                if github.is_github(self.url):
                    hint = ("；GitHub 页面链接不能直接当文件下载，Release 请用 "
                            "…/releases/latest 或具体资产链接，单文件请用 raw 地址")
                raise DownloadError(
                    f"这个地址返回的是网页（text/html），不是文件{hint}")

        # 文件名可能在探测阶段被服务端改写，重新对齐路径再建临时目录
        self._sync_paths()
        os.makedirs(self.part_dir, exist_ok=True)

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
        try:
            r = _open(self.effective_url, self._headers(headers), self.timeout,
                      method="GET")
        except Cancelled:
            raise
        except Exception as e:
            _rmdir(self.part_dir)
            raise DownloadError("连接失败：" + self._explain(e))
        with r:
            cr = r.headers.get("Content-Range", "")
            if cr and "/" in cr and self.total == 0:
                self.total = int(cr.split("/")[-1])
            if not self.total:
                self.total = int(r.headers.get("Content-Length", "0") or 0)
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
        """把 [0, total) 切成至多 threads 段。

        除了总字节数，还按 min_chunk_size 收敛段数：块太小会让建连/TLS 握手
        开销超过传输本身，临时文件与合并次数也随之暴涨。例如 100 MB 文件
        即使选 128 线程，也只会切 50 块（每块 2 MB）。
        """
        threads = max(1, min(int(threads), MAX_THREADS))
        if total > 0:
            threads = min(threads, max(1, total // MIN_CHUNK_SIZE))
        threads = max(1, min(threads, total or 1))
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
