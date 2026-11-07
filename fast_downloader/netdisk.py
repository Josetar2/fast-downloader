"""
netdisk.py — 直链型网盘（蓝奏云等）分享链接解析为真实 HTTP 直链。

为什么需要：蓝奏云 / 123pan 等国产网盘的"分享链接"是网页，不是文件地址；
真实下载地址带动态签名 / 302 跳转，需先解析才能用标准 HTTP 下载器直下。
本模块只负责"解析"，下载仍交给 core.Downloader。

支持：蓝奏云（lanzou.com / lanzoui.com / lanzoys.com 等镜像域名）
预留：123pan 等（签名较复杂，后续补充）

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LANZOU_HOSTS = (
    "lanzou.com", "lanzoui.com", "lanzoux.com",
    "lanzoys.com", "lanzouw.com", "lanzous.com",
)


class NetdiskResolveError(Exception):
    """网盘链接解析失败。"""


def is_supported(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(h in host for h in LANZOU_HOSTS)


def resolve(url: str) -> dict | None:
    """返回 {'url': 真实直链, 'headers': {下载时需要的额外请求头}}。

    不支持的链接返回 None（调用方应直接用原 URL 下载）。
    """
    host = urllib.parse.urlparse(url).netloc.lower()
    if any(h in host for h in LANZOU_HOSTS):
        return _resolve_lanzou(url)
    return None


class _RefererRedirect(urllib.request.HTTPRedirectHandler):
    """重定向时保留 Referer（蓝奏云最终直链跳转需要来源域名）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is not None:
            ref = req.headers.get("Referer")
            if ref and "Referer" not in newreq.headers:
                newreq.add_header("Referer", ref)
        return newreq


def _make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        _RefererRedirect,
    )


def _resolve_lanzou(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    opener = _make_opener()

    def fetch(u, referer=None):
        req = urllib.request.Request(u, headers={"User-Agent": UA})
        if referer:
            req.add_header("Referer", referer)
        return opener.open(req, timeout=30)

    # 1) 分享页
    try:
        resp = fetch(url)
    except urllib.error.HTTPError as e:
        raise NetdiskResolveError(f"蓝奏云分享页访问失败 ({e.code})")
    html = resp.read().decode("utf-8", "ignore")

    # 提取 iframe / 文件页地址（蓝奏云分享页内嵌文件页）
    m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
    if m:
        src = m.group(1)
        if src.startswith("//"):
            file_url = "https:" + src
        elif src.startswith("/"):
            file_url = base + src
        else:
            file_url = src
    else:
        file_url = url

    # 2) 文件页
    resp2 = fetch(file_url, referer=url)
    html2 = resp2.read().decode("utf-8", "ignore")

    def grab(name):
        mm = re.search(name + r"\s*[:=]\s*['\"]([^'\"]+)['\"]", html2)
        return mm.group(1) if mm else None

    sign = grab("sign")
    websign = grab("websign")
    websignkey = grab("websignkey") or ""
    action = grab("action") or "downprocess"
    if not sign:
        raise NetdiskResolveError("蓝奏云：未能提取 sign 参数（页面结构可能已变更）")

    # 3) ajaxm.php 拿 dom + url
    data = urllib.parse.urlencode({
        "action": action,
        "sign": sign,
        "websign": websign,
        "websignkey": websignkey,
        "ves": "1",
    }).encode()
    req = urllib.request.Request(base + "/ajaxm.php", data=data, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Referer", file_url)
    req.add_header("X-Requested-With", "XMLHttpRequest")
    try:
        r = opener.open(req, timeout=30)
        j = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        raise NetdiskResolveError(f"蓝奏云 ajaxm 请求失败: {e}")
    if j.get("zt") != 1:
        raise NetdiskResolveError(f"蓝奏云返回异常: {j}")
    dom = j.get("dom", "")
    real = j.get("url", "")
    if not real:
        raise NetdiskResolveError("蓝奏云：未返回真实地址")
    direct = dom + real

    # 4) 跟进 302 拿最终直链
    req2 = urllib.request.Request(
        direct, headers={"User-Agent": UA, "Referer": base + "/"}
    )
    try:
        r2 = opener.open(req2, timeout=30)
        final = r2.geturl()
    except urllib.error.HTTPError as e:
        final = e.headers.get("Location") or direct

    return {"url": final, "headers": {"Referer": base + "/", "User-Agent": UA}}
