"""图形界面：多线程高速下载器窗口（tkinter，无需额外依赖）。"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .core import Downloader, DownloadError, Cancelled


ACCENT = "#2f7ed8"
BG = "#f5f7fa"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("高速下载器")
        self.geometry("620x470")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._dl = None
        self._build_style()
        self._build()

    def _build_style(self) -> None:
        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except Exception:
            self.style = ttk.Style(self)
        self.style.configure("TLabel", background=BG, font=("Microsoft YaHei UI", 10))
        self.style.configure(
            "Title.TLabel",
            background=BG,
            foreground=ACCENT,
            font=("Microsoft YaHei UI", 16, "bold"),
        )
        self.style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#2566b8"), ("disabled", "#9bb8dc")],
        )
        self.style.configure("TButton", font=("Microsoft YaHei UI", 10))
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e3e8ef",
            background=ACCENT,
            thickness=18,
        )

    def _build(self) -> None:
        pad = {"padx": 14, "pady": 5}
        ttk.Label(self, text="高速下载器", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 2)
        )

        ttk.Label(self, text="下载链接").grid(row=1, column=0, sticky="w", **pad)
        self.url = ttk.Entry(self, width=64)
        self.url.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(self, text="保存位置").grid(row=3, column=0, sticky="w", **pad)
        self.save = ttk.Entry(self, width=52)
        self.save.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.save.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(self, text="浏览...", command=self._choose_dir).grid(
            row=4, column=2, sticky="e", **pad
        )

        ttk.Label(self, text="文件名（留空自动）").grid(row=5, column=0, sticky="w", **pad)
        ttk.Label(self, text="线程数").grid(row=5, column=2, sticky="w", **pad)
        self.name = ttk.Entry(self, width=40)
        self.name.grid(row=6, column=0, columnspan=2, sticky="ew", **pad)
        self.threads = ttk.Spinbox(self, from_=1, to=16, width=6)
        self.threads.set(8)
        self.threads.grid(row=6, column=2, sticky="w", **pad)

        self.progress = ttk.Progressbar(
            self, orient="horizontal", mode="determinate", length=580
        )
        self.progress.grid(row=7, column=0, columnspan=3, **pad)
        self.info = ttk.Label(self, text="就绪")
        self.info.grid(row=8, column=0, columnspan=3, sticky="w", **pad)

        self.btn_start = ttk.Button(
            self, text="开始下载", style="Accent.TButton", command=self._start
        )
        self.btn_start.grid(row=9, column=0, sticky="w", **pad)
        self.btn_cancel = ttk.Button(
            self, text="取消", state="disabled", command=self._cancel
        )
        self.btn_cancel.grid(row=9, column=1, sticky="w", **pad)
        ttk.Button(self, text="打开文件夹", command=self._open_folder).grid(
            row=9, column=2, sticky="e", **pad
        )

        self.log = scrolledtext.ScrolledText(
            self, height=8, state="disabled", font=("Consolas", 9)
        )
        self.log.grid(row=10, column=0, columnspan=3, sticky="nsew", padx=14, pady=(2, 12))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(10, weight=1)

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.save.delete(0, tk.END)
            self.save.insert(0, d)

    def _open_folder(self) -> None:
        d = self.save.get() or "."
        if os.path.isdir(d):
            if os.name == "nt":
                os.startfile(d)
            else:
                os.system(f'xdg-open "{d}"')

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _set_info(self, text: str) -> None:
        self.info.configure(text=text)

    def _start(self) -> None:
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载链接")
            return
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self._log(f"开始：{url}")
        threading.Thread(target=self._run, daemon=True).start()

    def _cancel(self) -> None:
        if self._dl:
            self._dl.cancel()
            self._log("已发送取消请求...")

    @staticmethod
    def _fmt(n: float) -> str:
        for u in ("B", "KiB", "MiB", "GiB", "TiB"):
            if n < 1024 or u == "TiB":
                return f"{n:.2f} {u}"
            n /= 1024

    def _on_progress(self, d: int, t: int, speed: float) -> None:
        self.after(0, self._update_ui, d, t, speed)

    def _update_ui(self, d: int, t: int, speed: float) -> None:
        if t:
            pct = d / t * 100
            self.progress["mode"] = "determinate"
            self.progress["value"] = pct
            remain = (t - d) / speed if speed > 0 else 0
            self._set_info(
                f"{pct:.1f}%  {self._fmt(d)}/{self._fmt(t)}  {self._fmt(speed)}/s  剩余 {remain:.0f}s"
            )
        else:
            self.progress["mode"] = "indeterminate"
            self.progress.start(20)
            self._set_info(f"已下载 {self._fmt(d)}  {self._fmt(speed)}/s")

    def _run(self) -> None:
        try:
            self._dl = Downloader(
                self.url.get().strip(),
                self.save.get() or ".",
                filename=self.name.get().strip() or None,
                threads=int(self.threads.get() or 8),
            )
            total, ranged = self._dl.probe()
            self.after(
                0,
                self._log,
                f"大小：{self._fmt(total) if total else '未知'}  分块：{'是' if ranged else '否'}",
            )
            path = self._dl.download(on_progress=self._on_progress)
            self.after(0, self._log, f"完成：{path}")
            self.after(0, lambda: messagebox.showinfo("完成", f"已保存到：\n{path}"))
        except Cancelled:
            self.after(0, self._log, "已取消")
        except DownloadError as e:
            self.after(0, self._log, f"失败：{e}")
            self.after(0, lambda: messagebox.showerror("下载失败", str(e)))
        finally:
            self.after(0, lambda: self.btn_start.configure(state="normal"))
            self.after(0, lambda: self.btn_cancel.configure(state="disabled"))
            self.after(0, self.progress.stop)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
