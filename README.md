# Fast Downloader

一个**不依赖任何第三方库**的高速多线程下载器：支持分块并发下载、断点续传、图形界面与命令行两种用法。

## 特性

- 多线程分块下载（基于 HTTP `Range`）
- 服务器不支持分块时自动降级为单线程流式下载
- 断点续传：中断后重跑会复用已下载的分块
- 实时进度 / 速度显示
- 图形界面（tkinter，无需额外依赖）+ 命令行两种用法
- 仅使用 Python 标准库，无需 `pip install`

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

## 说明

部分网站（如百度网盘）会返回 403 禁止直链下载，这是服务器限制，本工具无法绕过。

## 打包为 exe（Windows）

需一个带 tkinter 的 Python（标准安装版即可），在**项目外**建一个虚拟环境以避免污染系统：

```bash
# 用你本机带 tkinter 的 python 创建 venv（放到非 C 盘更稳妥）
py -3.14 -m venv D:\fd-venv
D:\fd-venv\Scripts\pip install pyinstaller

# 进入本项目目录后打包（--windowed 不弹黑框，--onefile 单文件）
D:\fd-venv\Scripts\pyinstaller --onefile --windowed --name FastDownloader run.py
```

产物在 `dist/FastDownloader.exe`。直接双击运行即是图形界面；命令行用法：

```bash
FastDownloader.exe "https://example.com/file.zip" -o D:\Downloads -n file.zip -t 8
```

图形界面默认保存位置为「桌面」，可在窗口里改成任意目录。

