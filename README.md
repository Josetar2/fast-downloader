# Fast Downloader

多线程下载器。只依赖 Python 标准库，不需要 `pip install`。

## 特性

- HTTP Range 分块并发，默认 16 线程、上限 128；每块不小于 2 MB，线程数按文件大小自动收敛
- 服务器不支持 Range 时降级为单线程流式下载
- 断点续传：重跑会复用已下载的分块
- 链接解析：蓝奏云等直链型网盘，以及 GitHub（仓库首页 / Release / 源码归档 / 文件页面）
- 文件名优先取 `Content-Disposition`；网页地址（`text/html`）会被拦下，而不是静默存成一个 html
- tkinter 图形界面：新建 / 任务列表 / 完成记录 / 设置，Windows 原生窗口，柔和圆角
- 三档响应式布局，窗口能缩到约一张信用卡大小
- 高 DPI 清晰渲染（exe 内嵌 PerMonitor 清单）
- exe 运行时不在系统盘产生临时文件

## 用法

图形界面：

```bash
python run.py
```

命令行：

```bash
python -m fast_downloader.cli "https://example.com/file.zip" -o ./downloads -n file.zip -t 16
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `url` | 下载地址 | — |
| `-o/--output` | 保存目录 | 当前目录 |
| `-n/--name` | 文件名 | 从响应头或 URL 推断 |
| `-t/--threads` | 线程数 | 16（上限 128，实际分块数按文件大小收敛） |

作为模块调用：

```python
from fast_downloader import Downloader

Downloader("https://example.com/file.zip", "./downloads", threads=16).download()
```

## 拿 exe

Releases 页面有两种 Windows 构建：

- `FastDownloader.exe` —— 单文件，双击即用
- `FastDownloader_portable.zip` —— 解压后双击里面的 exe，运行时不在系统盘写临时文件，适合放 U 盘

https://github.com/Josetar2/fast-downloader/releases

## 已知限制

- 百度网盘这类站点会返回 403 禁止直链下载，是服务器限制，绕不过
- GitHub 的源码归档是服务端动态打包，不返回 `Content-Length`，只能单线程下载
- GitHub 的文件存储域名（`release-assets.githubusercontent.com`）在部分网络下不可达；程序会自动改走 `api.github.com` 换签名，仍不通时只能改用源码包链接

## 打包

在项目外建虚拟环境，装 PyInstaller 后执行：

```bash
pyinstaller --onefile --windowed --name FastDownloader \
  --icon app.ico --manifest app.manifest --add-data "app.ico;." run.py
```

产物在 `dist/FastDownloader.exe`。

## 发布

维护者发版（本机已登录 `gh` 时）：

```bash
gh release create v1.5.4 dist/FastDownloader.exe dist/FastDownloader_portable.zip \
  --title "FastDownloader v1.5.4" \
  --notes "一句话说清这版改了什么"
```
