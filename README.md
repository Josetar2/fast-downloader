# Fast Downloader

一个**不依赖任何第三方库**的高速多线程下载器：支持分块并发下载、断点续传、图形界面与命令行两种用法。

## 特性

- 多线程分块下载（基于 HTTP `Range`）
- 服务器不支持分块时自动降级为单线程流式下载
- 断点续传：中断后重跑会复用已下载的分块
- 实时进度 / 速度显示
- 图形界面（tkinter，无需额外依赖）+ 命令行两种用法
- **任务管理器式图形界面**：左侧导航（新建下载 / 任务列表 / 完成记录 / 设置），支持多任务并发下载、排队、取消，任务列表实时显示进度 / 速度 / 剩余时间
- 仅使用 Python 标准库，无需 `pip install`
- 支持蓝奏云等「直链型网盘」分享链接自动解析下载（粘贴分享页链接即可，自动提取真实直链）
- 现代扁平图标（蓝渐变圆角方块 + 下载箭头），纯标准库生成，已内嵌至 exe
- **macOS 风格界面**：无边框圆角窗口 + 红黄绿交通灯、浅灰侧栏、圆角胶囊导航、白色圆角卡片与蓝色圆角按钮，主色 `#007AFF`
- **窗口与内部布局自适应**：侧栏、卡片、输入框、任务行随窗口尺寸变化；窗口大小与位置自动记忆
- **高 DPI 清晰渲染**：exe 内嵌 PerMonitor 清单，Tk 按真实 DPI 缩放字体，同时把几何尺寸等比放大、加深文字与边框对比度，高缩放屏（125% / 150%）不发虚

## 安装

无需安装依赖，直接运行即可（要求 Python 3.8+）。

## 用法

图形界面：

```bash
python run.py
```

命令行：

```bash
python -m fast_downloader.cli "https://example.com/file.zip" -o ./downloads -n file.zip -t 8
```

参数：

| 参数 | 说明 | 默认 |
|------|------|------|
| `url` | 下载地址（必填） | — |
| `-o/--output` | 保存目录 | 当前目录 |
| `-n/--name` | 文件名（默认从 URL 推断） | 自动 |
| `-t/--threads` | 线程数 | 8 |

## 作为模块调用

```python
from fast_downloader import Downloader

dl = Downloader("https://example.com/file.zip", "./downloads", threads=8)
dl.download(on_progress=lambda d, t, s: print(d, t, s))
```

## 免安装下载（Windows / 给别人用）

不想装 Python？去仓库 **Releases** 页面下载，提供两种 Windows 构建：

- `FastDownloader.exe` —— **单文件版**，双击即用（默认下载到桌面）
- `FastDownloader_portable.zip` —— **便携版**，解压后得到一个文件夹，双击里面的 `FastDownloader.exe` 即用。**运行时不在系统盘产生任何临时 / 解压文件**，适合放 U 盘或任意目录随身携带

下载地址：`https://github.com/Josetar2/fast-downloader/releases`

仓库所有者发布新版本（本机终端，`gh` 已登录即可，无需 token 明文）：

```bash
cd "项目目录"
gh release create v1.4.0 dist/FastDownloader.exe dist/FastDownloader_portable.zip \
  --title "FastDownloader v1.4.0" \
  --notes "高速多线程下载器 · 侧边导航多任务管理界面 · 蓝奏云等直链网盘自动解析 · 新扁平图标 · 单文件版 + 便携版（无 Temp 残留）"
```

## 说明

部分网站（如百度网盘）会返回 403 禁止直链下载，这是服务器限制，本工具无法绕过。

## 打包为 exe（Windows）

需一个带 tkinter 的 Python（标准安装版即可），在**项目外**建一个虚拟环境以避免污染系统：

```bash
# 用你本机带 tkinter 的 python 创建 venv（放到非 C 盘更稳妥）
py -3.14 -m venv D:\fd-venv
D:\fd-venv\Scripts\pip install pyinstaller

# 进入本项目目录后打包（--windowed 不弹黑框，--onefile 单文件，--icon 内嵌图标）
D:\fd-venv\Scripts\pyinstaller --onefile --windowed --name FastDownloader --icon app.ico --manifest app.manifest --add-data "app.ico;." run.py
```

产物在 `dist/FastDownloader.exe`。直接双击运行即是图形界面；命令行用法：

```bash
FastDownloader.exe "https://example.com/file.zip" -o D:\Downloads -n file.zip -t 8
```

图形界面默认保存位置为「桌面」，可在窗口里改成任意目录。

