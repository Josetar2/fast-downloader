"""图形界面：浅色现代风格下载管理器（参考设计稿，tkinter 运行时纯标准库）。"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import Downloader, DownloadError
from . import netdisk

# ---------- 配色（对齐设计稿）----------
BG_MAIN = "#F0F2F5"
SIDEBAR = "#FFFFFF"
SIDE_LINE = "#EDEFF2"
CARD = "white"
BORDER = "#E5E6EB"
ACCENT = "#1E80FF"
ACCENT_D = "#1565E0"
TEXT = "#1f2329"
SUB = "#8a9099"
SUCCESS_BG = "#E8F8E8"
SUCCESS_FG = "#2ba471"
ROW_LINE = "#F2F3F5"
FONT = ("Microsoft YaHei UI", 11)
FONT_T = ("Microsoft YaHei UI", 15, "bold")
FONT_S = ("Microsoft YaHei UI", 13, "bold")


def _rr(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1 + r, x2, y2 - r,
           x2 - r, y2, x1 + r, y2, x1, y2 - r, x1, y1 + r]
    c.create_polygon(*pts, smooth=True, **kw)


class Card(tk.Frame):
    """白色圆角卡片（带轻微阴影），主体放在灰色主区域上。"""

    PAD = 14
    R = 10

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_MAIN, **kw)
        self._cv = tk.Canvas(self, bg=BG_MAIN, highlightthickness=0, borderwidth=0)
        self._cv.pack(fill="both", expand=True)
        self._body = tk.Frame(self._cv, bg=CARD)
        self._win = self._cv.create_window(self.PAD, self.PAD, window=self._body, anchor="nw")
        self.bind("<Configure>", self._redraw)

    def _redraw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self._cv.delete("all")
        p, r = self.PAD, self.R
        _rr(self._cv, p, p + 4, w - p, h - p + 4, r, fill="#dde1e7", outline="")
        _rr(self._cv, p, p, w - p, h - p, r, fill=CARD, outline=BORDER, width=1)
        self._cv.coords(self._win, p, p)
        self._cv.itemconfig(self._win, width=w - 2 * p, height=h - 2 * p)


def _fmt(n: float) -> str:
    if n <= 0:
        return "0 B"
    for u in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or u == "TiB":
            return f"{n:.2f} {u}" if u != "B" else f"{n:.0f} {u}"
        n /= 1024


def _fmt_time(s: float) -> str:
    if s <= 0:
        return "—"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _icon_color(name: str) -> str:
    n = (name or "").lower()
    if n.endswith((".exe", ".msi", ".apk")):
        return "#1E80FF"
    if n.endswith((".zip", ".rar", ".7z", ".tar", ".gz")):
        return "#FF9F2E"
    if n.endswith((".pdf", ".doc", ".docx", ".txt")):
        return "#2ba471"
    if n.endswith((".mp4", ".mkv", ".avi", ".mov")):
        return "#F5606B"
    return "#7C8594"


class Task:
    def __init__(self, url, save_dir, filename, threads):
        self.url = url
        self.save_dir = save_dir
        self.filename = filename
        self.threads = threads
        self.status = "排队中"
        self.total = 0
        self.downloaded = 0
        self.speed = 0.0
        self.error = ""
        self.started = 0.0
        self.finished = 0.0
        self.path = ""
        self.dl = None
        self.thread = None


class Manager:
    def __init__(self):
        self.tasks: list[Task] = []
        self.lock = threading.Lock()
        self.max_concurrent = 3

    def add(self, t: Task):
        with self.lock:
            self.tasks.append(t)
        self._pump()

    def _pump(self):
        with self.lock:
            active = [t for t in self.tasks if t.status == "下载中"]
            queued = [t for t in self.tasks if t.status == "排队中"]
            while len(active) < self.max_concurrent and queued:
                t = queued.pop(0)
                t.status = "下载中"
                t.thread = threading.Thread(target=self._run, args=(t,), daemon=True)
                t.thread.start()
                active.append(t)

    def _run(self, t: Task):
        try:
            t.dl = Downloader(t.url, t.save_dir, filename=t.filename or None, threads=t.threads)
            t.started = time.time()
            t.path = t.dl.download(
                on_progress=lambda d, tot, sp: (
                    setattr(t, "downloaded", d),
                    setattr(t, "total", tot),
                    setattr(t, "speed", sp),
                )
            )
            t.status = "已完成"
            t.finished = time.time()
        except Exception as e:
            t.error = str(e)
            t.status = "已取消" if "Cancelled" in type(e).__name__ else "失败"
            t.finished = time.time()
        finally:
            self._pump()


class TaskList(tk.Frame):
    """自绘可滚动任务列表，行内含胶囊进度条与状态标签。"""

    def __init__(self, parent, mgr, on_action):
        super().__init__(parent, bg=CARD)
        self.mgr = mgr
        self.on_action = on_action
        self.rows: dict[int, "TaskRow"] = {}
        self._canvas = tk.Canvas(self, bg=CARD, highlightthickness=0)
        self._sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=CARD)
        self._win = self._canvas.create_window(0, 0, window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._sb.pack(side="right", fill="y")
        self._inner.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._win, width=e.width))

    def refresh(self):
        with self.mgr.lock:
            tasks = list(self.mgr.tasks)
        # 只显示进行中/已完成两类（参考图：进行中在上，已完成在下）
        active = [t for t in tasks if t.status in ("排队中", "下载中")]
        done = [t for t in tasks if t.status in ("已完成", "失败", "已取消")]
        ordered = active + done
        seen = set()
        for idx, t in enumerate(ordered):
            key = id(t)
            seen.add(key)
            row = self.rows.get(key)
            if row is None:
                row = TaskRow(self._inner, t, self.on_action)
                row.pack(fill="x")
                self.rows[key] = row
            else:
                row.pack(fill="x")
            row.update(t, first=(idx == 0))
        # 移除已删除任务对应的行
        for key in list(self.rows):
            if key not in seen:
                self.rows[key].destroy()
                del self.rows[key]


class TaskRow(tk.Frame):
    def __init__(self, parent, task, on_action):
        super().__init__(parent, bg=CARD)
        self.task = task
        self.on_action = on_action
        self.columnconfigure(1, weight=1)

        self.icon = tk.Canvas(self, width=22, height=26, bg=CARD, highlightthickness=0)
        self.icon.grid(row=0, column=0, padx=(4, 10), pady=8)
        _rr(self.icon, 1, 4, 21, 24, 4, fill=_icon_color(task.filename or task.url), outline="")

        self.name = tk.Label(self, text="", bg=CARD, fg=TEXT, font=FONT, anchor="w")
        self.name.grid(row=0, column=1, sticky="w", pady=(8, 0))

        self.stat = tk.Label(self, text="", bg=CARD, font=("Microsoft YaHei UI", 10), width=8)
        self.stat.grid(row=0, column=2, padx=(10, 0), pady=8)

        self.pbar = tk.Canvas(self, width=130, height=16, bg=CARD, highlightthickness=0)
        self.pbar.grid(row=0, column=3, padx=(10, 0), pady=8)

        self.meta = tk.Label(self, text="", bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 10), width=22, anchor="w")
        self.meta.grid(row=0, column=4, padx=(10, 0), pady=8)

        self.act = tk.Button(self, text="取消", bg=CARD, fg=SUB,
                             font=("Microsoft YaHei UI", 10), relief="flat",
                             command=lambda: self.on_action("cancel", self.task))
        self.act.grid(row=0, column=5, padx=(10, 8), pady=8)

        sep = tk.Frame(self, bg=ROW_LINE, height=1)
        sep.grid(row=1, column=0, columnspan=6, sticky="ew", padx=4)

    def update(self, t: Task, first=False):
        self.task = t
        self.name.config(text=t.filename or t.url)
        self.icon.delete("all")
        _rr(self.icon, 1, 4, 21, 24, 4, fill=_icon_color(t.filename or t.url), outline="")

        # 状态
        if t.status == "已完成":
            self.stat.config(text="已完成", bg=SUCCESS_BG, fg=SUCCESS_FG)
        elif t.status == "下载中":
            self.stat.config(text="下载中", bg=CARD, fg=ACCENT)
        elif t.status == "排队中":
            self.stat.config(text="排队中", bg=CARD, fg=SUB)
        else:
            self.stat.config(text=t.status, bg=CARD, fg="#F5606B")

        # 进度条
        self.pbar.delete("all")
        pct = (t.downloaded / t.total * 100) if t.total else (0 if t.status != "下载中" else 0)
        w, h = 130, 16
        _rr(self.pbar, 0, 0, w, h, 8, fill="#E5E6EB", outline="")
        if pct > 0:
            _rr(self.pbar, 0, 0, max(16, w * pct / 100), h, 8, fill=ACCENT, outline="")
            self.pbar.create_text(w / 2, h / 2, text=f"{pct:.0f}%", fill="white",
                                  font=("Microsoft YaHei UI", 9, "bold"))

        # 右侧信息
        if t.status == "下载中":
            eta = (t.total - t.downloaded) / t.speed if (t.speed and t.total) else 0
            self.meta.config(text=f"{_fmt(t.speed)}/s  {_fmt_time(eta)}  {_fmt(t.total)}")
        elif t.status == "已完成":
            dur = (t.finished - t.started) if t.finished else 0
            self.meta.config(text=f"{_fmt(t.total)}  {_fmt_time(dur)}")
        else:
            self.meta.config(text=_fmt(t.total) if t.total else "未知大小")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("高速下载器")
        # 默认尺寸随屏幕自适应（约 70% 宽 / 80% 高，限制上下限）
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = max(900, min(1180, int(sw * 0.7)))
            h = max(620, min(780, int(sh * 0.82)))
            self.geometry(f"{w}x{h}")
        except Exception:
            self.geometry("1000x680")
        # 允许自由缩放，并设最小尺寸，避免缩太小导致布局崩坏
        self.resizable(True, True)
        self.minsize(860, 560)
        # 关闭时记住窗口位置/大小
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # DPI 缩放：让 Tk 按真实 DPI 设置字体尺寸，避免模糊/过小
        try:
            import ctypes
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if dpi and dpi > 0:
                self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.mgr = Manager()
        self.current = "新建下载"
        self._panels = {}

        ico = self._app_path("app.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_style()
        self._build_sidebar()
        self._build_content()
        self._build_new()
        self._build_tasks()
        self._build_done()
        self._build_settings()
        self._show("新建下载")
        self._center_on_screen()
        self._tick()

    # ---------- 路径 ----------
    def _app_path(self, name: str) -> str:
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            return os.path.join(base, name)
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)

    # ---------- 窗口定位（避免偏出屏幕/左侧被裁切）----------
    def _center_on_screen(self):
        self.update_idletasks()
        saved = self._load_geom()
        if saved:
            self.geometry(saved)
            self.update_idletasks()
            return
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            return
        w = self.winfo_width()
        h = self.winfo_height()
        # 限制不超出屏幕（高 DPI 下避免溢出），留出任务栏空间
        w = min(w, max(360, sw - 20))
        h = min(h, max(280, sh - 80))
        if w != self.winfo_width() or h != self.winfo_height():
            self.geometry(f"{w}x{h}")
            self.update_idletasks()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 窗口位置记忆（仅写在程序同目录，便携版不跨盘）----------
    def _config_path(self) -> str:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "fastdownloader.ini")

    def _load_geom(self):
        try:
            import re
            p = self._config_path()
            if not os.path.exists(p):
                return None
            with open(p, "r", encoding="utf-8") as f:
                data = f.read().strip()
            if re.match(r"^\d+x\d+[+-]\d+[+-]\d+$", data):
                return data
        except Exception:
            pass
        return None

    def _save_geom(self):
        try:
            self.update_idletasks()
            with open(self._config_path(), "w", encoding="utf-8") as f:
                f.write(self.geometry())
        except Exception:
            pass

    def _on_close(self):
        self._save_geom()
        self.destroy()

    # ---------- 样式 ----------
    def _build_style(self):
        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except Exception:
            self.style = ttk.Style(self)
        self.style.configure("TLabel", background=CARD, foreground=TEXT, font=FONT)
        self.style.configure("TEntry", font=FONT)
        self.style.configure("TButton", font=FONT)
        self.style.configure("TSpinbox", font=FONT)
        self.style.configure("TCombobox", font=FONT)
        self.style.configure("Accent.TButton", background=ACCENT, foreground="white",
                             font=("Microsoft YaHei UI", 11, "bold"))
        self.style.map("Accent.TButton", background=[("active", ACCENT_D), ("disabled", "#9bb8dc")])
        self.style.configure("Ghost.TButton", background=CARD, foreground=TEXT,
                             relief="solid", bordercolor=BORDER)
        self.style.configure("Link.TButton", background=CARD, foreground=ACCENT, relief="flat")
        self.style.map("Link.TButton", background=[("active", "#EAF2FF")])

    # ---------- 侧边栏 ----------
    def _build_sidebar(self):
        side = tk.Frame(self, width=150, bg=SIDEBAR)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(side, bg=SIDE_LINE, width=1).place(relx=1.0, y=0, relheight=1, anchor="ne")

        tk.Label(side, text="高速下载器", bg=SIDEBAR, fg=TEXT,
                 font=FONT_T).pack(anchor="w", padx=18, pady=(22, 4))
        tk.Label(side, text="Fast Downloader", bg=SIDEBAR, fg=SUB,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(0, 24))

        self._nav = {}
        for name, glyph in (("新建下载", "＋"), ("任务列表", "▤"),
                            ("完成记录", "✔"), ("设置", "⚙")):
            b = tk.Button(side, text=f"  {glyph}  {name}", bg=SIDEBAR, fg=TEXT,
                          font=FONT_S, anchor="w", relief="flat",
                          padx=16, pady=11, activebackground="#EAF2FF",
                          command=lambda n=name: self._show(n))
            b.pack(fill="x", padx=10, pady=3)
            self._nav[name] = b

    # ---------- 内容区 ----------
    def _build_content(self):
        self.content = tk.Frame(self, bg=BG_MAIN)
        self.content.pack(side="right", fill="both", expand=True)

    def _show(self, name):
        self.current = name
        for n, b in self._nav.items():
            sel = (n == name)
            b.config(bg=ACCENT if sel else SIDEBAR, fg="white" if sel else TEXT,
                     font=("Microsoft YaHei UI", 13, "bold") if sel else FONT_S)
        for f in self._panels.values():
            f.pack_forget()
        self._panels[name].pack(fill="both", expand=True, padx=22, pady=18)

    # ---------- 新建下载 ----------
    def _build_new(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["新建下载"] = wrap

        card = Card(wrap)
        card.pack(fill="x")
        body = card._body
        tk.Label(body, text="新建下载任务", bg=CARD, fg=TEXT, font=FONT_T).pack(anchor="w", padx=22, pady=(18, 6))

        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=22, pady=(6, 18))
        f.columnconfigure(0, weight=1)

        tk.Label(f, text="下载链接", bg=CARD, fg=TEXT, font=FONT, anchor="w").grid(row=0, column=0, sticky="w", pady=(4, 2))
        row0 = tk.Frame(f, bg=CARD)
        row0.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        row0.columnconfigure(0, weight=1)
        self.url_e = ttk.Entry(row0, font=FONT)
        self.url_e.grid(row=0, column=0, sticky="ew")
        ttk.Button(row0, text="解析", style="Link.TButton", width=8, command=self._resolve).grid(row=0, column=1, padx=(8, 0))

        tk.Label(f, text="保存位置", bg=CARD, fg=TEXT, font=FONT, anchor="w").grid(row=2, column=0, sticky="w", pady=(12, 2))
        row1 = tk.Frame(f, bg=CARD)
        row1.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        row1.columnconfigure(0, weight=1)
        self.save_e = ttk.Entry(row1, font=FONT)
        self.save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.save_e.grid(row=0, column=0, sticky="ew")
        ttk.Button(row1, text="浏览...", style="Ghost.TButton", width=8, command=self._choose_dir).grid(row=0, column=1, padx=(8, 0))

        tk.Label(f, text="文件名（留空自动）", bg=CARD, fg=TEXT, font=FONT, anchor="w").grid(row=4, column=0, sticky="w", pady=(12, 2))
        self.name_e = ttk.Entry(f, font=FONT)
        self.name_e.grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)

        tk.Label(f, text="线程数", bg=CARD, fg=TEXT, font=FONT, anchor="w").grid(row=6, column=0, sticky="w", pady=(12, 2))
        self.threads_e = ttk.Spinbox(f, from_=1, to=16, width=8, font=FONT)
        self.threads_e.set(8)
        self.threads_e.grid(row=7, column=0, sticky="w", pady=2)

        self.new_info = tk.Label(f, text="", bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 10), anchor="w")
        self.new_info.grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 4))

        btns = tk.Frame(f, bg=CARD)
        btns.grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(btns, text="开始下载", style="Accent.TButton", command=self._add_task).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="打开文件夹", style="Ghost.TButton", command=self._open_folder).pack(side="left")

    def _choose_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.save_e.delete(0, tk.END)
            self.save_e.insert(0, d)

    def _open_folder(self):
        d = self.save_e.get() or "."
        if os.path.isdir(d):
            if os.name == "nt":
                os.startfile(d)
            else:
                os.system(f'xdg-open "{d}"')

    def _resolve(self):
        url = self.url_e.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载链接")
            return
        try:
            eff, headers = url, {}
            name = Downloader._guess_filename(url)
            if netdisk.is_supported(url):
                r = netdisk.resolve(url)
                eff = r["url"]
                headers = r.get("headers", {})
                name = Downloader._guess_filename(eff)
            dl = Downloader(eff, self.save_e.get() or ".", filename=name, threads=8)
            dl.extra_headers = headers
            total, ranged = dl.probe()
            self.new_info.config(text=f"文件名：{name}    大小：{_fmt(total) if total else '未知'}    支持分块：{'是' if ranged else '否'}")
            if not self.name_e.get().strip():
                self.name_e.delete(0, tk.END)
                self.name_e.insert(0, name)
        except Exception as e:
            messagebox.showerror("解析失败", str(e))

    def _add_task(self):
        url = self.url_e.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载链接")
            return
        t = Task(url, self.save_e.get() or ".", self.name_e.get().strip() or None,
                 int(self.threads_e.get() or 8))
        self.mgr.add(t)
        self._show("任务列表")

    # ---------- 任务列表 ----------
    def _build_tasks(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["任务列表"] = wrap
        card = Card(wrap)
        card.pack(fill="both", expand=True)
        body = card._body
        tk.Label(body, text="任务列表", bg=CARD, fg=TEXT, font=FONT_T).pack(anchor="w", padx=22, pady=(18, 6))
        self.tasks_list = TaskList(body, self.mgr, self._on_task_action)
        self.tasks_list.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _on_task_action(self, action, task):
        if action == "cancel":
            if task.dl:
                task.dl.cancel()
            elif task.status == "排队中":
                task.status = "已取消"

    # ---------- 完成记录 ----------
    def _build_done(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["完成记录"] = wrap
        card = Card(wrap)
        card.pack(fill="both", expand=True)
        body = card._body
        tk.Label(body, text="完成记录", bg=CARD, fg=TEXT, font=FONT_T).pack(anchor="w", padx=22, pady=(18, 6))
        self.done_list = TaskList(body, self.mgr, lambda a, t: None)
        self.done_list.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    # ---------- 设置 ----------
    def _build_settings(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["设置"] = wrap
        card = Card(wrap)
        card.pack(fill="x")
        body = card._body
        tk.Label(body, text="设置", bg=CARD, fg=TEXT, font=FONT_T).pack(anchor="w", padx=22, pady=(18, 6))
        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=22, pady=(6, 18))

        tk.Label(f, text="最大同时下载数", bg=CARD, fg=TEXT, font=FONT).grid(row=0, column=0, sticky="w", pady=8)
        self.max_e = ttk.Spinbox(f, from_=1, to=10, width=8, font=FONT)
        self.max_e.set(self.mgr.max_concurrent)
        self.max_e.grid(row=0, column=1, padx=12, sticky="w")

        tk.Label(f, text="默认保存位置", bg=CARD, fg=TEXT, font=FONT).grid(row=1, column=0, sticky="w", pady=8)
        self.def_save_e = ttk.Entry(f, width=40, font=FONT)
        self.def_save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.def_save_e.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(f, text="浏览...", style="Ghost.TButton", command=self._choose_def).grid(row=2, column=2, padx=8)

        tk.Label(f, text="默认线程数", bg=CARD, fg=TEXT, font=FONT).grid(row=3, column=0, sticky="w", pady=8)
        self.def_threads_e = ttk.Spinbox(f, from_=1, to=16, width=8, font=FONT)
        self.def_threads_e.set(8)
        self.def_threads_e.grid(row=3, column=1, padx=12, sticky="w")

        ttk.Button(f, text="保存设置", style="Accent.TButton", command=self._save_settings).grid(row=4, column=0, sticky="w", pady=14)

    def _choose_def(self):
        d = filedialog.askdirectory()
        if d:
            self.def_save_e.delete(0, tk.END)
            self.def_save_e.insert(0, d)

    def _save_settings(self):
        try:
            self.mgr.max_concurrent = max(1, int(self.max_e.get() or 3))
        except Exception:
            pass
        self.save_e.delete(0, tk.END)
        self.save_e.insert(0, self.def_save_e.get())
        self.threads_e.set(self.def_threads_e.get())
        messagebox.showinfo("已保存", "设置已生效")

    # ---------- 刷新 ----------
    def _tick(self):
        if self.current == "任务列表":
            self.tasks_list.refresh()
        elif self.current == "完成记录":
            self.done_list.refresh()
        self.after(400, self._tick)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
