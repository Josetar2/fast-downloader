"""图形界面：现代侧边导航 + 多任务并发下载器（tkinter，纯标准库运行时）。"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import Downloader, DownloadError
from . import netdisk

ACCENT = "#2f7ed8"
ACCENT_D = "#2566b8"
BG = "#f5f7fa"
SIDE_BG = "#1f2733"
SIDE_BG_HOVER = "#2b3543"
SIDE_SEL = "#2f7ed8"
TEXT = "#2b2f36"


def _app_path(name: str) -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)


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


class Task:
    def __init__(self, url: str, save_dir: str, filename: str | None, threads: int) -> None:
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
        self.dl: Downloader | None = None
        self.thread: threading.Thread | None = None


class Manager:
    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.lock = threading.Lock()
        self.max_concurrent = 3

    def add(self, t: Task) -> None:
        with self.lock:
            self.tasks.append(t)
        self._pump()

    def _pump(self) -> None:
        with self.lock:
            active = [t for t in self.tasks if t.status == "下载中"]
            queued = [t for t in self.tasks if t.status == "排队中"]
            while len(active) < self.max_concurrent and queued:
                t = queued.pop(0)
                t.status = "下载中"
                t.thread = threading.Thread(target=self._run, args=(t,), daemon=True)
                t.thread.start()
                active.append(t)

    def _run(self, t: Task) -> None:
        try:
            t.dl = Downloader(
                t.url, t.save_dir, filename=t.filename or None, threads=t.threads
            )
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
        except Exception as e:  # Cancelled 也是 Exception 子类
            t.error = str(e)
            t.status = "已取消" if "Cancelled" in type(e).__name__ else "失败"
            t.finished = time.time()
        finally:
            self._pump()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("高速下载器")
        self.geometry("880x560")
        self.configure(bg=BG)
        self.mgr = Manager()
        self.current = "新建下载"
        self._panels: dict[str, ttk.Frame] = {}

        ico = _app_path("app.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_style()
        self._build_layout()
        self._build_new()
        self._build_tasks()
        self._build_done()
        self._build_settings()
        self._show("新建下载")
        self._tick()

    # ---------- 样式 ----------
    def _build_style(self) -> None:
        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except Exception:
            self.style = ttk.Style(self)
        self.style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        self.style.configure("TEntry", font=("Microsoft YaHei UI", 10))
        self.style.configure("TButton", font=("Microsoft YaHei UI", 10))
        self.style.configure(
            "Accent.TButton", background=ACCENT, foreground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.style.map("Accent.TButton", background=[("active", ACCENT_D), ("disabled", "#9bb8dc")])
        self.style.configure("TSpinbox", font=("Microsoft YaHei UI", 10))
        self.style.configure(
            "Treeview", font=("Microsoft YaHei UI", 10), rowheight=26,
            background="white", fieldbackground="white",
        )
        self.style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("Side.TButton", background=SIDE_BG, foreground="#e8edf3",
                             font=("Microsoft YaHei UI", 11), anchor="w", relief="flat")
        self.style.map("Side.TButton", background=[("active", SIDE_BG_HOVER)])
        self.style.configure("Title.TLabel", background=SIDE_BG, foreground="white",
                             font=("Microsoft YaHei UI", 15, "bold"))

    # ---------- 布局 ----------
    def _build_layout(self) -> None:
        side = ttk.Frame(self, width=200, style="TFrame")
        side.configure(style="TFrame")
        side.pack(side="left", fill="y")
        side.configure()
        # 侧边栏底色
        side.config()
        side_frame = tk.Frame(side, width=200, bg=SIDE_BG)
        side_frame.pack(fill="y", expand=True)
        side_frame.pack_propagate(False)

        ttk.Label(side_frame, text="高速下载器", style="Title.TLabel").pack(
            anchor="w", padx=18, pady=(18, 4)
        )
        ttk.Label(side_frame, text="Fast Downloader", background=SIDE_BG,
                  foreground="#7e8a9c", font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=18, pady=(0, 18)
        )

        self._nav_btns: dict[str, tk.Button] = {}
        for name in ("新建下载", "任务列表", "完成记录", "设置"):
            b = tk.Button(
                side_frame, text=name, bg=SIDE_BG, fg="#e8edf3",
                font=("Microsoft YaHei UI", 11), anchor="w", relief="flat",
                padx=18, pady=9, activebackground=SIDE_BG_HOVER,
                command=lambda n=name: self._show(n),
            )
            b.pack(fill="x")
            self._nav_btns[name] = b

        # 内容区
        self.content = ttk.Frame(self, style="TFrame")
        self.content.pack(side="right", fill="both", expand=True)
        self.content.config()
        cframe = tk.Frame(self.content, bg=BG)
        cframe.pack(fill="both", expand=True)
        self._cframe = cframe

    def _show(self, name: str) -> None:
        self.current = name
        for n, b in self._nav_btns.items():
            b.config(bg=SIDE_SEL if n == name else SIDE_BG,
                     fg="white" if n == name else "#e8edf3",
                     font=("Microsoft YaHei UI", 11, "bold") if n == name else ("Microsoft YaHei UI", 11))
        for n, f in self._panels.items():
            f.pack_forget()
        self._panels[name].pack(fill="both", expand=True, padx=18, pady=16)

    # ---------- 新建下载 ----------
    def _build_new(self) -> None:
        p = ttk.Frame(self._cframe, style="TFrame")
        self._panels["新建下载"] = p
        f = tk.Frame(p, bg=BG)
        f.pack(fill="x")

        ttk.Label(f, text="下载链接").grid(row=0, column=0, sticky="w", padx=2, pady=(4, 2))
        self.url_e = ttk.Entry(f, width=58)
        self.url_e.grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(f, text="解析", width=8, command=self._resolve).grid(row=1, column=1, padx=(6, 0))

        ttk.Label(f, text="保存位置").grid(row=2, column=0, sticky="w", padx=2, pady=(8, 2))
        self.save_e = ttk.Entry(f, width=50)
        self.save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.save_e.grid(row=3, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(f, text="浏览...", width=8, command=self._choose_dir).grid(row=3, column=1, padx=(6, 0))

        ttk.Label(f, text="文件名（留空自动）").grid(row=4, column=0, sticky="w", padx=2, pady=(8, 2))
        ttk.Label(f, text="线程数").grid(row=4, column=1, sticky="w", padx=6, pady=(8, 2))
        self.name_e = ttk.Entry(f, width=40)
        self.name_e.grid(row=5, column=0, sticky="ew", padx=2, pady=2)
        self.threads_e = ttk.Spinbox(f, from_=1, to=16, width=8)
        self.threads_e.set(8)
        self.threads_e.grid(row=5, column=1, padx=6, pady=2, sticky="w")

        self.new_info = ttk.Label(f, text="", foreground="#5a6472")
        self.new_info.grid(row=6, column=0, columnspan=2, sticky="w", padx=2, pady=(8, 2))

        row = ttk.Frame(f, style="TFrame")
        row.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(row, text="开始下载", style="Accent.TButton", command=self._add_task).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="打开文件夹", command=self._open_folder).pack(side="left")

        f.columnconfigure(0, weight=1)

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.save_e.delete(0, tk.END)
            self.save_e.insert(0, d)

    def _open_folder(self) -> None:
        d = self.save_e.get() or "."
        if os.path.isdir(d):
            if os.name == "nt":
                os.startfile(d)
            else:
                os.system(f'xdg-open "{d}"')

    def _resolve(self) -> None:
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
            self.new_info.config(
                text=f"文件名：{name}    大小：{_fmt(total) if total else '未知'}    "
                      f"支持分块：{'是' if ranged else '否'}"
            )
            if not self.name_e.get().strip():
                self.name_e.delete(0, tk.END)
                self.name_e.insert(0, name)
        except Exception as e:
            messagebox.showerror("解析失败", str(e))

    def _add_task(self) -> None:
        url = self.url_e.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载链接")
            return
        t = Task(
            url,
            self.save_e.get() or ".",
            self.name_e.get().strip() or None,
            int(self.threads_e.get() or 8),
        )
        self.mgr.add(t)
        self._show("任务列表")

    # ---------- 任务列表 ----------
    def _build_tasks(self) -> None:
        p = ttk.Frame(self._cframe, style="TFrame")
        self._panels["任务列表"] = p
        cols = ("文件名", "状态", "进度", "速度", "剩余时间", "大小")
        self.tasks_tv = ttk.Treeview(p, columns=cols, show="headings", height=14)
        widths = (240, 80, 90, 110, 90, 100)
        for c, w in zip(cols, widths):
            self.tasks_tv.heading(c, text=c)
            self.tasks_tv.column(c, width=w, anchor="w")
        self.tasks_tv.pack(fill="both", expand=True)

        row = ttk.Frame(p, style="TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="取消选中", command=self._cancel_sel).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="删除选中", command=self._del_sel).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="打开所在文件夹", command=self._open_sel).pack(side="left")

    def _cancel_sel(self) -> None:
        for iid in self.tasks_tv.selection():
            t = self.tasks_tv.item(iid, "values")
            for task in self.mgr.tasks:
                if task.filename == t[0] or task.url == t[0]:
                    if task.dl:
                        task.dl.cancel()
                    elif task.status == "排队中":
                        task.status = "已取消"

    def _del_sel(self) -> None:
        sel = list(self.tasks_tv.selection())
        if not sel:
            return
        with self.mgr.lock:
            for iid in sel:
                v = self.tasks_tv.item(iid, "values")
                self.mgr.tasks = [
                    t for t in self.mgr.tasks
                    if not (t.filename == v[0] or t.url == v[0])
                ]

    def _open_sel(self) -> None:
        for iid in self.tasks_tv.selection():
            v = self.tasks_tv.item(iid, "values")
            for task in self.mgr.tasks:
                if (task.filename == v[0] or task.url == v[0]) and os.path.isdir(task.save_dir):
                    if os.name == "nt":
                        os.startfile(task.save_dir)
                    break

    # ---------- 完成记录 ----------
    def _build_done(self) -> None:
        p = ttk.Frame(self._cframe, style="TFrame")
        self._panels["完成记录"] = p
        cols = ("文件名", "大小", "用时", "状态")
        self.done_tv = ttk.Treeview(p, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (300, 120, 120, 100)):
            self.done_tv.heading(c, text=c)
            self.done_tv.column(c, width=w, anchor="w")
        self.done_tv.pack(fill="both", expand=True)

    # ---------- 设置 ----------
    def _build_settings(self) -> None:
        p = ttk.Frame(self._cframe, style="TFrame")
        self._panels["设置"] = p
        f = tk.Frame(p, bg=BG)
        f.pack(fill="x", pady=4)

        ttk.Label(f, text="最大同时下载数").grid(row=0, column=0, sticky="w", padx=2, pady=(4, 2))
        self.max_e = ttk.Spinbox(f, from_=1, to=10, width=8)
        self.max_e.set(self.mgr.max_concurrent)
        self.max_e.grid(row=0, column=1, padx=8, sticky="w")

        ttk.Label(f, text="默认保存位置").grid(row=1, column=0, sticky="w", padx=2, pady=(10, 2))
        self.def_save_e = ttk.Entry(f, width=40)
        self.def_save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.def_save_e.grid(row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        ttk.Button(f, text="浏览...", command=self._choose_def).grid(row=2, column=2, padx=6)

        ttk.Label(f, text="默认线程数").grid(row=3, column=0, sticky="w", padx=2, pady=(10, 2))
        self.def_threads_e = ttk.Spinbox(f, from_=1, to=16, width=8)
        self.def_threads_e.set(8)
        self.def_threads_e.grid(row=3, column=1, padx=8, sticky="w")

        ttk.Button(f, text="保存设置", style="Accent.TButton", command=self._save_settings).grid(
            row=4, column=0, sticky="w", pady=(14, 0)
        )

    def _choose_def(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.def_save_e.delete(0, tk.END)
            self.def_save_e.insert(0, d)

    def _save_settings(self) -> None:
        try:
            self.mgr.max_concurrent = max(1, int(self.max_e.get() or 3))
        except Exception:
            pass
        self.save_e.delete(0, tk.END)
        self.save_e.insert(0, self.def_save_e.get())
        self.threads_e.set(self.def_threads_e.get())
        messagebox.showinfo("已保存", "设置已生效")

    # ---------- 刷新 ----------
    def _tick(self) -> None:
        if self.current in ("任务列表", "完成记录"):
            with self.mgr.lock:
                tasks = list(self.mgr.tasks)
            if self.current == "任务列表":
                self._render_tasks(tasks)
            else:
                self._render_done(tasks)
        self.after(350, self._tick)

    def _render_tasks(self, tasks: list[Task]) -> None:
        # 清空后用排序后数据重绘
        active = [t for t in tasks if t.status in ("排队中", "下载中")]
        self.tasks_tv.delete(*self.tasks_tv.get_children())
        for t in active:
            pct = (t.downloaded / t.total * 100) if t.total else 0
            eta = (t.total - t.downloaded) / t.speed if (t.speed and t.total) else 0
            self.tasks_tv.insert("", "end", values=(
                t.filename or t.url,
                t.status,
                f"{pct:.1f}%" if t.total else ("—" if t.status == "下载中" else "0%"),
                _fmt(t.speed) + "/s" if t.speed else "—",
                _fmt_time(eta),
                _fmt(t.total) if t.total else "未知",
            ))

    def _render_done(self, tasks: list[Task]) -> None:
        fin = [t for t in tasks if t.status in ("已完成", "失败", "已取消")]
        self.done_tv.delete(*self.done_tv.get_children())
        for t in fin:
            dur = (t.finished - t.started) if t.finished else 0
            self.done_tv.insert("", "end", values=(
                t.filename or t.url,
                _fmt(t.total) if t.total else "—",
                _fmt_time(dur),
                t.status,
            ))


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
