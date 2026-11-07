# PCL 高速下载器（独立版）

把 PCL 启动器「百宝箱 → 下载自定义文件」的高速多线程下载能力，抽成一个**不依赖 PCL、可独立运行的模块**，并开源。

## 特性

- 多线程分块下载（基于 HTTP `Range`）
- 服务器不支持分块时自动降级为单线程流式下载
- 断点续传：中断后重跑会复用已下载的分块
- 实时进度 / 速度显示
- 图形界面（tkinter，无需额外依赖）+ 命令行两种用法
- 仅依赖 `requests`

## 安装

```bash
pip install -r requirements.txt
```

## 用法

图形界面（模仿 PCL 的下载窗口）：

```bash
python run.py
```

命令行：

```bash
python -m pcl_fast_downloader.cli "https://example.com/file.zip" -o ./downloads -n file.zip -t 8
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
from pcl_fast_downloader import Downloader

dl = Downloader("https://example.com/file.zip", "./downloads", threads=8)
dl.download(on_progress=lambda d, t, s: print(d, t, s))
```

## 说明

部分网站（如百度网盘）会返回 403 禁止直链下载，这是服务器限制，本工具无法绕过。
