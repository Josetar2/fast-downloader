"""图形界面：模仿 PCL「下载自定义文件」窗口（tkinter，无需额外依赖）。"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import Downloader, DownloadError


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PCL 高速下载器（独立版）")
        self.geometry("560x300")
        self.resizable(False, False)

        self._build()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}

        tk.Label(self, text="下载地址：").grid(row=0, column=0, sticky="w", **pad)
        self.url = tk.Entry(self, width=52)
        self.url.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        tk.Label(self, text="保存到：").grid(row=1, column=0, sticky="w", **pad)
        self.save = tk.Entry(self, width=42)
        self.save.insert(0, os.path.join(os.path.expanduser("~"), "Downloads"))
        self.save.grid(row=1, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择", command=self._choose_dir).grid(row=1, column=2, **pad)

        tk.Label(self, text="文件名：").grid(row=2, column=0, sticky="w", **pad)
        self.name = tk.Entry(self, width=52)
        self.name.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        self.progress = ttk.Progressbar(self, length=520, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=3, **pad)

        self.status = tk.Label(self, text="就绪", anchor="w")
        self.status.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        self.btn_start = tk.Button(self, text="开始下载", command=self._start, width=14)
        self.btn_start.grid(row=5, column=1, sticky="e", **pad)
        tk.Button(self, text="打开文件夹", command=self._open_folder, width=14).grid(
            row=5, column=2, sticky="w", **pad
        )

        self.columnconfigure(1, weight=1)

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.save.delete(0, tk.END)
            self.save.insert(0, d)

    def _open_folder(self) -> None:
        d = self.save.get() or "."
        if os.path.isdir(d):
            os.startfile(d) if os.name == "nt" else os.system(f'xdg-open "{d}"')

    def _start(self) -> None:
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载地址")
            return
        self.btn_start.config(state="disabled")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            dl = Downloader(
                self.url.get().strip(),
                self.save.get() or ".",
                filename=self.name.get().strip() or None,
            )
            total, _ = dl.probe()

            def on_progress(d, t, speed):
                pct = (d / t * 100) if t else 0
                self.progress["value"] = pct
                self.status.config(
                    text=f"{pct:.1f}%  {d / 1048576:.1f}/{ (t/1048576) if t else 0:.1f} MiB  {speed/1048576:.1f} MiB/s"
                )

            path = dl.download(on_progress=on_progress)
            self.status.config(text=f"完成：{path}")
            messagebox.showinfo("完成", f"已保存到：\n{path}")
        except DownloadError as e:
            self.status.config(text=f"失败：{e}")
            messagebox.showerror("下载失败", str(e))
        finally:
            self.btn_start.config(state="normal")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
