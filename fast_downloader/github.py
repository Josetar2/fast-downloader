"""
github.py — GitHub 链接解析：把「网页链接」变成「下载器能直接下的地址」。

为什么需要：GitHub 上有三类长得完全不同的链接，直接丢给 HTTP 下载器结果天差地别：

1. 仓库 / 文件 / Release 页面  ——  是 HTML 网页，直接下只会得到一个 .html
2. Release 资产（真实文件）    ——  302 跳到 objects.githubusercontent.com，可下可分段
3. 源码归档 zip / tar.gz      ——  302 跳到 codeload.github.com，可下但服务端动态打包

本模块负责识别类型、把能推导的地址直接改写成下载直链（例如把
github.com/o/r/archive/refs/heads/main.zip 换成 codeload.github.com/o/r/zip/refs/heads/main，
少跳一次 github.com 主域），并对页面链接调用 API 列出可下载内容。

纯标准库实现，无第三方依赖。API 未认证时限速 60 次/小时，够用。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
UA = "FastDownloader (+https://github.com/Josetar2/fast-downloader)"

_GITHUB_HOSTS = ("github.com", "www.github.com")
_RAW_HOSTS = ("raw.githubusercontent.com", "raw.github.com")
_CODE_HOSTS = ("codeload.github.com",)

# 常见二进制资产扩展名：用于在多资产 Release 里挑「最像成品」的那个
_ARCHIVE_EXT = (".zip", ".7z", ".tar.gz", ".tgz", ".tar.xz", ".rar")
_WIN_HINT = ("win", "windows", "win64", "win32", "x64", "amd64", "msvc")


class GitHubResolveError(Exception):
    """GitHub 链接解析失败。"""


# ---------- 类型识别 ----------
def is_github(url: str) -> bool:
    """是否是本模块认识的 GitHub 域名（含 raw / codeload）。"""
    try:
        host = (urllib.parse.urlparse(url).netloc or "").lower().split(":")[0]
    except Exception:
        return False
    return host in _GITHUB_HOSTS or host in _RAW_HOSTS or host in _CODE_HOSTS


def classify(url: str) -> str:
    """把链接归类，调用方据此决定怎么处理。

    asset     Release 里的具体文件（真直链）
    archive   源码归档 zip / tar.gz
    raw       单文件原文
    release   Release 页面（latest / tag / 列表）
    repo      仓库首页
    tree      目录页面
    blob      文件页面
    other     其它 GitHub 页面（issue / pr / wiki …，基本没得下）
    """
    p = urllib.parse.urlparse(url)
    host = (p.netloc or "").lower().split(":")[0]
    path = p.path or "/"

    if host in _RAW_HOSTS:
        return "raw"
    if host in _CODE_HOSTS:
        # codeload.github.com/o/r/zip/refs/heads/main
        return "archive"

    parts = [s for s in path.split("/") if s]
    if len(parts) < 2:
        return "other"
    rest = "/" + "/".join(parts[2:])

    if re.match(r"^/releases/download/", rest):
        return "asset"
    if rest in ("/releases", "/releases/") or rest.startswith("/releases/"):
        return "release"
    if rest.startswith("/archive/"):
        return "archive"
    if rest.startswith("/raw/"):
        return "raw"
    if rest.startswith("/blob/"):
        return "blob"
    if rest.startswith("/tree/"):
        return "tree"
    if rest in ("", "/"):
        return "repo"
    return "other"


def _owner_repo(url: str):
    parts = [s for s in urllib.parse.urlparse(url).path.split("/") if s]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


# ---------- API ----------
def _api(path: str, timeout: int = 20) -> dict | list:
    req = urllib.request.Request(API + path, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise GitHubResolveError("仓库 / Release 不存在，或是私有仓库需要登录")
        if e.code in (403, 429):
            raise GitHubResolveError(
                "GitHub API 请求过于频繁被限流（未登录每小时 60 次），稍后再试")
        raise GitHubResolveError(f"GitHub API 返回 {e.code}")
    except urllib.error.URLError as e:
        raise GitHubResolveError(f"连不上 api.github.com：{e.reason}")


def _release_of(url: str) -> dict:
    """按页面类型取对应 Release 的元数据。"""
    owner, repo = _owner_repo(url)
    if not owner:
        raise GitHubResolveError("链接里缺少 用户名/仓库名")
    rest = "/" + "/".join(
        [s for s in urllib.parse.urlparse(url).path.split("/") if s][2:])

    if rest.rstrip("/") == "/releases/latest":
        return _api(f"/repos/{owner}/{repo}/releases/latest")
    m = re.match(r"^/releases/tag/(.+?)/?$", rest)
    if m:
        tag = urllib.parse.unquote(m.group(1))
        return _api(f"/repos/{owner}/{repo}/releases/tags/{tag}")
    # /releases 列表：取第一个非草稿非预览版
    data = _api(f"/repos/{owner}/{repo}/releases?per_page=10")
    for rel in data if isinstance(data, list) else []:
        if not rel.get("draft") and not rel.get("prerelease"):
            return rel
    if isinstance(data, list) and data:
        return data[0]
    raise GitHubResolveError("这个仓库还没有发布任何 Release")


def _score_asset(asset: dict) -> tuple:
    """给资产打分：当前系统能直接用的、体积大的优先。"""
    name = (asset.get("name") or "").lower()
    score = 0
    if os.name == "nt":
        score += 6 if any(k in name for k in _WIN_HINT) else 0
        if any(k in name for k in ("mac", "darwin", "linux", "android")):
            score -= 4
    elif os.name != "nt":
        if any(k in name for k in ("linux", "mac", "darwin", "tar.gz")):
            score += 3
        if "win" in name:
            score -= 4
    if name.endswith(".zip"):
        score += 2
    elif name.endswith(_ARCHIVE_EXT):
        score += 1
    # 体积作为次要权重（大文件通常是完整包）
    return (score, int(asset.get("size") or 0))


def _pick_asset(assets: list) -> dict | None:
    if not assets:
        return None
    return max(assets, key=_score_asset)


def list_assets(url: str) -> list[dict]:
    """列出一个 Release 页面里所有可下载文件（真资产，不含自动源码包）。"""
    if classify(url) not in ("release", "repo"):
        return []
    owner, repo = _owner_repo(url)
    if not owner:
        return []
    if classify(url) == "repo":
        try:
            rel = _api(f"/repos/{owner}/{repo}/releases/latest")
        except GitHubResolveError:
            return []
    else:
        rel = _release_of(url)
    return list(rel.get("assets") or [])


# ---------- 主入口 ----------
def resolve(url: str) -> dict | None:
    """把 GitHub 链接变成可直接下载的地址。

    返回 {'url': 直链, 'headers': {...}, 'filename': 建议文件名, 'note': 说明}
    不认识的链接返回 None（调用方按普通直链处理）。
    失败抛 GitHubResolveError。
    """
    kind = classify(url)
    p = urllib.parse.urlparse(url)
    path = p.path or "/"

    # 1) 源码归档：直接改写到 codeload，省掉 github.com 主域那一跳
    if kind == "archive":
        if (p.netloc or "").lower().split(":")[0] in _CODE_HOSTS:
            return _as_download(url, _name_from_path(path, "zip"), "")
        m = re.match(r"^/([^/]+)/([^/]+)/archive/(.+)$", path)
        if not m:
            return None
        owner, repo, ref = m.group(1), m.group(2), m.group(3).rstrip("/")
        ext = "tar.gz" if ref.endswith(".tar.gz") else "zip"
        ref = ref[: -len("." + ext)] if ref.endswith("." + ext) else ref
        if not ref:
            return None
        direct = f"{CODELOAD}/{owner}/{repo}/{ext}/{ref}"
        return _as_download(direct, _archive_name(repo, ref, ext),
                            "已转 codeload 归档直链")

    # 2) 文件页面 / 单文件原文：统一转成 raw 地址（blob 页是 HTML，不能直接下）
    if kind in ("raw", "blob"):
        if (p.netloc or "").lower().split(":")[0] in _RAW_HOSTS:
            return _as_download(url, _name_from_path(path, "bin"), "")
        m = re.match(r"^/([^/]+)/([^/]+)/(?:raw|blob)/(.+)$", path)
        if m:
            direct = f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
            note = "已转原始文件链接" if kind == "blob" else "已转原始文件"
            return _as_download(direct, _name_from_path(direct, "txt"), note)
        return None

    # 3) Release 资产直链：原样下（可能先跳 github.com 再跳对象存储）
    if kind == "asset":
        return _as_download(url, _name_from_path(path, "bin"), "")

    # 4) Release 页面 / 仓库首页 / 目录页：用 API 找可下载的东西
    if kind in ("release", "repo", "tree"):
        owner, repo = _owner_repo(url)
        if not owner:
            return None
        note = ""
        assets = []
        if kind in ("release", "repo"):
            try:
                assets = list_assets(url)
            except GitHubResolveError:
                assets = []
        picked = _pick_asset(assets)
        if picked:
            more = f"Release 自动选中最匹配文件（共 {len(assets)} 个）" if len(assets) > 1 else "Release 资产"
            return _as_download(picked["browser_download_url"], picked["name"], more)
        # 没有上传资产 → 退到源码包（codeload 直连，通常能下）
        ref = _ref_from(url)
        if not ref and kind in ("release", "repo"):
            try:
                info = _api(f"/repos/{owner}/{repo}/releases/latest")
                ref = info.get("tag_name") or ""
            except GitHubResolveError:
                ref = ""
        if not ref:
            try:
                ref = _api(f"/repos/{owner}/{repo}").get("default_branch") or "main"
            except GitHubResolveError:
                ref = "main"
        direct = f"{CODELOAD}/{owner}/{repo}/zip/refs/heads/{ref}"
        note = "无上传资产，改下源码包"
        return _as_download(direct, _archive_name(repo, ref, "zip"), note)

    return None


def _ref_from(url: str) -> str:
    """从 tree / blob 链接里取出分支或标签。"""
    m = re.search(r"/(?:tree|blob)/([^/]+)/", urllib.parse.urlparse(url).path)
    if m:
        return m.group(1)
    m = re.match(r"^/([^/]+)/([^/]+)/archive/(.+)$",
                 urllib.parse.urlparse(url).path)
    if m:
        ref = m.group(3)
        for suf in (".tar.gz", ".zip"):
            if ref.endswith(suf):
                ref = ref[: -len(suf)]
        return ref
    return ""


def _name_from_path(path: str, default_ext: str) -> str:
    """从 URL 路径推文件名；GitHub 的路径末段常常没有扩展名。"""
    last = [s for s in path.split("/") if s]
    if not last:
        return f"download.{default_ext}"
    name = urllib.parse.unquote(last[-1])
    if "." not in name:
        return f"{name}.{default_ext}"
    return name


def _archive_name(repo: str, ref: str, ext: str) -> str:
    """按 GitHub 的命名习惯给出源码包文件名：{仓库}-{分支或标签}.{扩展名}。"""
    tail = [s for s in ref.split("/") if s]
    label = tail[-1] if tail else "source"
    if label in ("refs", "heads", "tags"):
        label = "source"
    return f"{repo}-{label}.{ext}"


def _as_download(direct: str, filename: str, note: str) -> dict:
    return {
        "url": direct,
        "headers": {"User-Agent": UA},
        "filename": filename,
        "note": note,
        "kind": classify(direct),
    }


def describe_error(url: str, exc: Exception) -> str:
    """把底层网络错误翻译成用户看得懂的提示。"""
    text = str(exc)
    host = (urllib.parse.urlparse(url).netloc or "").lower()
    if "objects.githubusercontent.com" in host or "release-assets" in host:
        return ("GitHub 的文件存储域名（objects.githubusercontent.com）当前网络不可达，"
                "通常是代理 / 网络限制导致；换用能直连 GitHub 的网络，或在代理里放行该域名")
    if host in ("raw.githubusercontent.com", "github.com"):
        return (f"当前网络连不上 {host}（常见于代理拦截或 DNS 污染）；"
                f"源码包可改用 codeload 链接，例如 "
                f"https://codeload.github.com/用户名/仓库名/zip/refs/heads/main")
    return text
