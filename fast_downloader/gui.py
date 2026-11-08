"""图形界面：macOS 风格下载管理器（tkinter，运行时零第三方依赖）。"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import netdisk
from .core import Downloader, DownloadError

IS_WIN = sys.platform == "win32"

APP_VERSION = "1.4.0"

# 几何按真实 DPI 等比放大：字体由 tk scaling 放大，固定像素若不跟着放大，
# 高 DPI 屏上细线/小图标会显得发虚、拥挤。
SCALE = 1.0


def _s(v):
    return max(1, int(round(v * SCALE)))

# ---------- macOS 浅色设计令牌 ----------
TITLE_BG = "#F6F6F8"      # 标题栏
SIDEBAR = "#E9E9EF"       # 半透明感侧栏
BG_MAIN = "#F7F7F9"       # 内容区
CARD = "#FFFFFF"
BORDER = "#DEDEE4"
SEPARATOR = "#D2D2D9"
SHADOW1 = "#E9E9EF"
SHADOW2 = "#F0F0F4"
ACCENT = "#007AFF"
ACCENT_D = "#0067DB"
ACCENT_SOFT = "#D9E8FF"
TEXT = "#1D1D1F"
SUB = "#6E6E73"
SUCCESS_BG = "#DFF3E6"
SUCCESS_FG = "#1B8A4B"
ROW_LINE = "#F1F1F4"
TRACK = "#E7E7EC"
LAMP_RED = "#FF5F57"
LAMP_YELLOW = "#FEBC2E"
LAMP_GREEN = "#28C840"
FILE_TINT = "#0A84FF"

UI_FAM = "Segoe UI"
FONT = ("Segoe UI", 11)
FONT_T = ("Segoe UI", 16, "bold")
FONT_S = ("Segoe UI", 12)
FONT_SM = ("Segoe UI", 10)
FONT_XS = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI", 13)
FONT_BTN = ("Segoe UI", 11, "bold")


def _init_fonts(root):
    """挑一个最接近 SF Pro 的字体；中文由系统自动回退到雅黑。"""
    global UI_FAM, FONT, FONT_T, FONT_S, FONT_SM, FONT_XS, FONT_TITLE, FONT_BTN, SCALE
    try:
        import ctypes
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
    except Exception:
        dpi = 96
    SCALE = max(1.0, min(2.5, (dpi or 96) / 96.0))
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
    except Exception:
        fams = set()
    UI_FAM = ("Segoe UI" if "Segoe UI" in fams else
              "Microsoft YaHei UI" if "Microsoft YaHei UI" in fams else
              "TkDefaultFont")
    FONT = (UI_FAM, 11)
    FONT_T = (UI_FAM, 16, "bold")
    FONT_S = (UI_FAM, 12)
    FONT_SM = (UI_FAM, 10)
    FONT_XS = (UI_FAM, 10)
    FONT_TITLE = (UI_FAM, 13)
    FONT_BTN = (UI_FAM, 11, "bold")


def _win_api():
    """返回配置好 argtypes 的 user32，避免 64 位 HWND 被截断。"""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetParent.argtypes = [wintypes.HWND]
    u.GetParent.restype = wintypes.HWND
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u.SetWindowLongW.restype = ctypes.c_long
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.IsZoomed.restype = wintypes.BOOL
    u.ReleaseCapture.argtypes = []
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                               wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW.restype = wintypes.LPARAM
    return u


def _rr(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1 + r, x2, y2 - r,
           x2 - r, y2, x1 + r, y2, x1, y2 - r, x1, y1 + r]
    c.create_polygon(*pts, smooth=True, **kw)


def _solid_rr(c, x1, y1, x2, y2, r, fill, tags=None):
    """精确圆角矩形（4 个扇形 + 2 个矩形拼接），用于胶囊/按钮。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    opt = dict(fill=fill, outline="", width=0)
    if tags:
        opt["tags"] = tags
    c.create_rectangle(x1 + r, y1, x2 - r, y2, **opt)
    c.create_rectangle(x1, y1 + r, x2, y2 - r, **opt)
    c.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **opt)
    c.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **opt)
    c.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", **opt)
    c.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", **opt)


def _glyph(c, kind, x, y, color):
    w = 2
    if kind == "plus":
        c.create_line(x - 6, y, x + 6, y, fill=color, width=w, capstyle="round")
        c.create_line(x, y - 6, x, y + 6, fill=color, width=w, capstyle="round")
    elif kind == "list":
        for dy in (-5, 0, 5):
            c.create_oval(x - 7, y + dy - 1.5, x - 4, y + dy + 1.5,
                          fill=color, outline="")
            c.create_line(x - 1, y + dy, x + 7, y + dy, fill=color,
                          width=w, capstyle="round")
    elif kind == "check":
        c.create_oval(x - 8, y - 8, x + 8, y + 8, outline=color, width=w)
        c.create_line(x - 4, y, x - 1, y + 3, x + 5, y - 4, fill=color,
                      width=w, capstyle="round", joinstyle="round")
    elif kind == "gear":
        c.create_oval(x - 5, y - 5, x + 5, y + 5, outline=color, width=w)
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            c.create_line(x + math.cos(a) * 6, y + math.sin(a) * 6,
                          x + math.cos(a) * 9, y + math.sin(a) * 9,
                          fill=color, width=2, capstyle="round")


class MacButton(tk.Canvas):
    """macOS 风格圆角按钮：蓝底主按钮 / 白底次按钮 / 无框文字按钮。"""

    H = 32

    def __init__(self, parent, text, command, kind="secondary", width=100, bg=CARD):
        self.H = _s(32)
        super().__init__(parent, width=_s(width), height=self.H, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self.text, self.command, self.kind = text, command, kind
        self._bg = bg
        self._hover = False
        self._down = False
        self.bind("<Enter>", lambda e: self._state(hover=True))
        self.bind("<Leave>", lambda e: self._state(hover=False, down=False))
        self.bind("<Button-1>", lambda e: self._state(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _state(self, hover=None, down=None):
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self._draw()

    def _release(self, e):
        self._down = False
        self._draw()
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_reqwidth(), self.H
        if self.kind == "primary":
            fill = ACCENT_D if self._down else (ACCENT if not self._hover else "#3395FF")
            border = None
            fg = "white"
        elif self.kind == "link":
            fill = "#EEF5FF" if (self._hover or self._down) else self._bg
            border = None
            fg = ACCENT
        else:
            fill = "#EDEDF2" if self._down else ("#FBFBFD" if self._hover else "#FFFFFF")
            border = "#D1D1D6"
            fg = TEXT
        r = _s(7)
        _solid_rr(self, 0, 0, w, h, r, border or fill)
        _solid_rr(self, 1, 1, w - 1, h - 1, max(1, r - 1), fill)
        font = FONT_BTN if self.kind == "primary" else FONT
        self.create_text(w / 2, h / 2 + 0.5, text=self.text, fill=fg, font=font)
        self.configure(cursor="hand2")


def _make_entry(parent):
    return tk.Entry(parent, relief="flat", bd=0, bg="#FFFFFF", fg=TEXT,
                    font=FONT, insertbackground=ACCENT, highlightthickness=0,
                    selectbackground=ACCENT_SOFT, selectforeground=TEXT)


def _make_combo(parent, values, default):
    c = ttk.Combobox(parent, values=values, state="readonly", font=FONT,
                     style="Plain.TCombobox")
    c.set(default)
    return c


class Field(tk.Frame):
    """macOS 圆角输入容器：外框用 Canvas 画，内嵌无边框 Entry / Combobox。"""

    H = 34

    def __init__(self, parent, factory, width=None, bg=CARD):
        self.H = _s(34)
        super().__init__(parent, bg=bg, height=self.H)
        if width:
            self.configure(width=_s(width))
        self.pack_propagate(False)
        self._bg = bg
        self._focus = False
        self._cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._cv.pack(fill="both", expand=True)
        self.inner = factory(self._cv)
        self._win = self._cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<FocusIn>", lambda e: self._redraw(True))
        self.inner.bind("<FocusOut>", lambda e: self._redraw(False))
        self.bind("<Configure>", lambda e: self._draw())

    def _redraw(self, focus):
        self._focus = focus
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self._cv.delete("fieldbg")
        # 只画边框线，且必须后创建（位于内容窗口之上），
        # 否则会被不透明的 Entry 白底盖掉，只剩断续的线段。
        r = _s(7)
        _solid_rr(self._cv, 1, 1, w - 1, h - 1, r,
                  ACCENT if self._focus else "#BFC0C6", tags="fieldbg")
        _solid_rr(self._cv, 2, 2, w - 2, h - 2, max(1, r - 1),
                  "#FFFFFF", tags="fieldbg")
        self._cv.tag_lower("fieldbg", self._win)
        self._cv.coords(self._win, _s(5), _s(4))
        self._cv.itemconfig(self._win, width=w - 2 * _s(5), height=h - 2 * _s(4))

    # 代理常用方法，业务代码无需感知容器
    def get(self):
        return self.inner.get()

    def set(self, value):
        self.inner.set(value)

    def insert(self, *args):
        return self.inner.insert(*args)

    def delete(self, *args):
        return self.inner.delete(*args)


class Card(tk.Frame):
    """白色圆角卡片，两层极淡阴影（macOS 窗口卡片观感）。"""

    PAD = 12
    R = 12
    _registry: list["Card"] = []

    def __init__(self, parent, fit=False, **kw):
        super().__init__(parent, bg=BG_MAIN, **kw)
        self.PAD, self.R = _s(12), _s(12)
        self._fit = fit
        self._cv = tk.Canvas(self, bg=BG_MAIN, highlightthickness=0, borderwidth=0)
        self._cv.pack(fill="both", expand=True)
        self._body = tk.Frame(self._cv, bg=CARD)
        self._win = self._cv.create_window(self.PAD, self.PAD, window=self._body, anchor="nw")
        self.bind("<Configure>", self._redraw)
        Card._registry.append(self)

    def _redraw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        # fit 卡片：高度必须跟随内容自然高度重算。窗口缩放/DPI 变化后
        # 若沿用启动时的高度，底部的按钮行会被内容窗口裁掉。
        if self._fit:
            self._body.update_idletasks()
            need = self._body.winfo_reqheight() + 2 * self.PAD + _s(8)
            if abs(h - need) > 2:
                self._cv.configure(height=need)
        # create_window 生成的内容窗口也是 canvas item，delete("all") 会连它一起删，
        # 导致卡片内表单消失；这里只删背景 tag。
        self._cv.delete("cardbg")
        p, r = self.PAD, self.R
        _solid_rr(self._cv, p, p + _s(6), w - p, h - p + _s(6), r,
                  SHADOW2, tags="cardbg")
        _solid_rr(self._cv, p, p + _s(3), w - p, h - p + _s(3), r,
                  SHADOW1, tags="cardbg")
        _solid_rr(self._cv, p, p, w - p, h - p, r, BORDER, tags="cardbg")
        _solid_rr(self._cv, p + 1, p + 1, w - p - 1, h - p - 1,
                  max(1, r - 1), CARD, tags="cardbg")
        self._cv.tag_lower("cardbg", self._win)
        self._cv.coords(self._win, p, p)
        self._cv.itemconfig(self._win, width=w - 2 * p)
        if not self._fit:
            self._cv.itemconfig(self._win, height=h - 2 * p)

    def fit(self):
        if not self._fit:
            return
        self._body.update_idletasks()
        h = self._body.winfo_reqheight() + 2 * self.PAD + _s(8)
        self._cv.configure(height=h)


class TitleBar(tk.Frame):
    """自绘标题栏：交通灯 + 居中标题（系统标题栏已隐藏）。"""

    H = 44

    def __init__(self, app, page="新建下载"):
        self.H = _s(44)
        super().__init__(app, bg=TITLE_BG, height=self.H)
        self.app = app
        self.pack(side="top", fill="x")
        self.pack_propagate(False)
        self._page = page

        lamps = tk.Canvas(self, width=_s(88), height=self.H, bg=TITLE_BG,
                          highlightthickness=0, bd=0)
        lamps.pack(side="left", padx=(_s(10), 0))
        specs = ((LAMP_RED, "×", "#7A0000", app._close),
                 (LAMP_YELLOW, "−", "#7A4E00", app._minimize),
                 (LAMP_GREEN, "+", "#00420A", app._toggle_zoom))
        for i, (color, mark, ink, action) in enumerate(specs):
            x = _s(12) + i * _s(21)
            cy = self.H / 2
            oval = lamps.create_oval(x, cy - _s(6.5), x + _s(13), cy + _s(6.5),
                                     fill=color, outline="", width=0)
            txt = lamps.create_text(x + _s(6.5), cy - 0.5, text=mark, fill=ink,
                                    font=(UI_FAM, 9, "bold"), state="hidden")
            for item in (oval, txt):
                lamps.tag_bind(item, "<Enter>",
                               lambda e, t=txt: lamps.itemconfig(t, state="normal"))
                lamps.tag_bind(item, "<Leave>",
                               lambda e, t=txt: lamps.itemconfig(t, state="hidden"))
                lamps.tag_bind(item, "<Button-1>",
                               lambda e, a=action: (a(), "break")[1])
        self.lamps = lamps

        self.title = tk.Label(self, text=page, bg=TITLE_BG, fg="#48484E",
                              font=FONT_TITLE)
        self.title.place(relx=0.5, rely=0.5, anchor="center")

        tk.Frame(self, bg=SEPARATOR, height=max(1, _s(1))).place(
            relx=0, rely=1.0, relwidth=1, anchor="sw")

        for widget in (self, lamps, self.title):
            widget.bind("<Button-1>", self._press)
            widget.bind("<B1-Motion>", self._move)
            widget.bind("<Double-Button-1>", lambda e: app._toggle_zoom())

    def set_page(self, name):
        self._page = name
        self.title.config(text=name)

    def _press(self, e):
        # 交给 Windows 原生拖动循环（支持贴靠/阴影/多显示器），比自绘更顺滑
        h = getattr(self.app, "_hwnd", None)
        if IS_WIN and h:
            try:
                u = _win_api()
                u.ReleaseCapture()
                u.SendMessageW(h, 0x00A1, 2, 0)  # WM_NCLBUTTONDOWN / HTCAPTION
                return "break"
            except Exception:
                pass
        self._ox = e.x_root - self.app.winfo_rootx()
        self._oy = e.y_root - self.app.winfo_rooty()

    def _move(self, e):
        if IS_WIN and getattr(self.app, "_hwnd", None):
            return
        if not hasattr(self, "_ox"):
            return
        self.app.geometry(f"+{e.x_root - self._ox}+{e.y_root - self._oy}")


class NavItem(tk.Canvas):
    """macOS 侧栏圆角胶囊导航项。"""

    H = 36

    def __init__(self, parent, app, name, glyph, width):
        self.H = _s(36)
        super().__init__(parent, width=width, height=self.H, bg=SIDEBAR,
                         highlightthickness=0, bd=0, takefocus=0)
        self.app, self.name, self.glyph = app, name, glyph
        self._sel = False
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<Button-1>", lambda e: app._show(name))
        self.configure(cursor="hand2")

    def _set(self, selected=None, hover=None):
        if selected is not None:
            self._sel = selected
        if hover is not None:
            self._hover = hover
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        if self._sel:
            fill = ACCENT_SOFT
        elif self._hover:
            fill = "#DEDEE6"
        else:
            fill = SIDEBAR
        _solid_rr(self, 0, 0, w, self.H, _s(8), fill)
        _glyph(self, self.glyph, _s(22), self.H / 2,
               ACCENT_D if self._sel else "#5B5B63")
        self.create_text(_s(42), self.H / 2 + 0.5, text=self.name, anchor="w",
                         fill=ACCENT_D if self._sel else TEXT,
                         font=(UI_FAM, 12, "bold" if self._sel else "normal"))


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
        return "#0A84FF"
    if n.endswith((".zip", ".rar", ".7z", ".tar", ".gz")):
        return "#FF9F0A"
    if n.endswith((".pdf", ".doc", ".docx", ".txt")):
        return "#30B158"
    if n.endswith((".mp4", ".mkv", ".avi", ".mov")):
        return "#FF453A"
    return "#8E8E93"


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
    """自绘可滚动任务列表。"""

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
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._win, width=e.width))

    def refresh(self):
        with self.mgr.lock:
            tasks = list(self.mgr.tasks)
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

        self.icon = tk.Canvas(self, width=30, height=32, bg=CARD, highlightthickness=0)
        self.icon.grid(row=0, column=0, padx=(4, 12), pady=8)

        self.name = tk.Label(self, text="", bg=CARD, fg=TEXT, font=FONT, anchor="w")
        self.name.grid(row=0, column=1, sticky="w", pady=(8, 0))

        self.stat = tk.Canvas(self, width=64, height=22, bg=CARD, highlightthickness=0)
        self.stat.grid(row=0, column=2, padx=(10, 0), pady=8)

        self.pbar = tk.Canvas(self, width=104, height=8, bg=CARD, highlightthickness=0)
        self.pbar.grid(row=0, column=3, padx=(12, 0), pady=8)

        self.pct = tk.Label(self, text="", bg=CARD, fg=SUB, font=FONT_XS, width=5, anchor="w")
        self.pct.grid(row=0, column=4, padx=(6, 0), pady=8)

        self.meta = tk.Label(self, text="", bg=CARD, fg=SUB, font=FONT_SM,
                             width=24, anchor="w")
        self.meta.grid(row=0, column=5, padx=(10, 0), pady=8)

        self.act = tk.Label(self, text="取消", bg=CARD, fg=ACCENT, font=FONT_SM,
                            cursor="hand2")
        self.act.grid(row=0, column=6, padx=(10, 8), pady=8)
        self.act.bind("<Button-1>", lambda e: self.on_action("cancel", self.task))

        sep = tk.Frame(self, bg=ROW_LINE, height=1)
        sep.grid(row=1, column=0, columnspan=7, sticky="ew", padx=4)

    def update(self, t: Task, first=False):
        self.task = t
        self.name.config(text=t.filename or t.url)
        color = _icon_color(t.filename or t.url)
        self.icon.delete("all")
        _solid_rr(self.icon, 1, 2, 29, 30, 7, color)
        # 文件折角
        self.icon.create_polygon(19, 6, 25, 6, 25, 12, fill="#FFFFFF", outline="")
        self.icon.create_rectangle(8, 16, 22, 23, fill="#FFFFFF", outline="")

        self.stat.delete("all")
        label, bg, fg = {
            "已完成": ("已完成", SUCCESS_BG, SUCCESS_FG),
            "下载中": ("下载中", ACCENT_SOFT, ACCENT_D),
            "排队中": ("排队中", "#EFEFF3", SUB),
        }.get(t.status, (t.status, "#FFE8E7", "#D4443C"))
        _solid_rr(self.stat, 0, 0, 64, 22, 11, bg)
        self.stat.create_text(32, 11.5, text=label, fill=fg, font=FONT_XS)

        self.pbar.delete("all")
        pct = (t.downloaded / t.total * 100) if t.total else 0
        _solid_rr(self.pbar, 0, 0, 104, 8, 4, TRACK)
        if pct > 0:
            _solid_rr(self.pbar, 0, 0, max(8, 104 * pct / 100), 8, 4, ACCENT)
        self.pct.config(text=f"{pct:.0f}%" if pct else "")

        if t.status == "下载中":
            eta = (t.total - t.downloaded) / t.speed if (t.speed and t.total) else 0
            self.meta.config(text=f"{_fmt(t.speed)}/s  {_fmt_time(eta)}  {_fmt(t.total)}")
        elif t.status == "已完成":
            dur = (t.finished - t.started) if t.finished else 0
            self.meta.config(text=f"{_fmt(t.total)}  {_fmt_time(dur)}")
        else:
            self.meta.config(text=_fmt(t.total) if t.total else "未知大小")
        self.act.config(text="取消" if t.status in ("排队中", "下载中") else "",
                        fg=ACCENT)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("高速下载器")
        _init_fonts(self)  # 必须先算 SCALE，后面所有 _s() 几何才按真实 DPI 放大
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = max(_s(940), min(_s(1220), int(sw * 0.7)))
            h = max(_s(640), min(_s(820), int(sh * 0.82)))
            self.geometry(f"{w}x{h}")
        except Exception:
            self.geometry(f"{_s(1040)}x{_s(700)}")
        self.resizable(True, True)
        self.minsize(_s(900), _s(680))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # DPI 缩放：让 Tk 按真实 DPI 设置字体尺寸，避免模糊/过小
        try:
            import ctypes
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if dpi and dpi > 0:
                self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.mgr = Manager()
        self.current = "新建下载"
        self._panels = {}
        self._nav = {}
        self._hwnd = None
        self._zoomed = False

        ico = self._app_path("app.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_style()
        self.bind("<Configure>", self._on_resize)
        self.configure(bg=SEPARATOR)
        self._titlebar = TitleBar(self, self.current)
        self._body = tk.Frame(self, bg=BG_MAIN)
        self._body.pack(side="top", fill="both", expand=True, padx=1, pady=(0, 1))
        self._build_sidebar()
        self._build_content()
        self._build_new()
        self._build_tasks()
        self._build_done()
        self._build_settings()
        self._show(self.current)
        for c in Card._registry:
            c.fit()
        self._center_on_screen()
        # 隐藏 Windows 系统标题栏，保留系统边框/阴影/任务栏/最小化/缩放
        self.update_idletasks()
        self._mac_frame()
        self.after(180, self._mac_frame)
        self._tick()

    def _on_resize(self, e):
        """窗口缩放时侧栏与内容区一起跟随，避免固定宽度显得脱节。"""
        if e.widget is not self or not hasattr(self, "side"):
            return
        target = max(self._side_min, min(_s(280), int(e.width * 0.18)))
        if abs(target - self.side.winfo_width()) > 1:
            self.side.configure(width=target)

    # ---------- 无边框 macOS 窗口（仅 Windows 生效）----------
    def _mac_frame(self):
        if not IS_WIN:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u = _win_api()
            h = u.GetParent(self.winfo_id()) or self.winfo_id()
            self._hwnd = h
            GWL_STYLE = -16
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            style = u.GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF
            style &= ~WS_CAPTION
            style |= WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            if style >= 0x80000000:
                style -= 0x100000000
            u.SetWindowLongW(h, GWL_STYLE, style)
            # SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_FRAMECHANGED
            u.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
            # Windows 11：强制圆角窗口
            try:
                from ctypes import wintypes
                d = ctypes.windll.dwmapi
                d.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                    ctypes.c_void_p, wintypes.DWORD]
                pref = ctypes.c_int(2)  # DWMWCP_ROUND
                d.DwmSetWindowAttribute(h, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass
        except Exception:
            self._hwnd = None

    def _close(self):
        self._on_close()

    def _minimize(self):
        if IS_WIN and self._hwnd:
            try:
                _win_api().ShowWindow(self._hwnd, 6)  # SW_MINIMIZE
                return
            except Exception:
                pass
        self.iconify()

    def _toggle_zoom(self):
        if IS_WIN and self._hwnd:
            try:
                u = _win_api()
                if u.IsZoomed(self._hwnd):
                    u.ShowWindow(self._hwnd, 9)  # SW_RESTORE
                    self._zoomed = False
                else:
                    u.ShowWindow(self._hwnd, 3)  # SW_MAXIMIZE
                    self._zoomed = True
                return
            except Exception:
                pass
        self.attributes("-zoomed", not self.attributes("-zoomed"))

    # ---------- 路径 ----------
    def _app_path(self, name: str) -> str:
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            return os.path.join(base, name)
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)

    # ---------- 窗口定位 ----------
    def _center_on_screen(self):
        self.update_idletasks()
        saved = self._load_geom()
        if saved:
            self.geometry(saved)
            self.update_idletasks()
            return
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            return
        w, h = self.winfo_width(), self.winfo_height()
        w = min(w, max(360, sw - 20))
        h = min(h, max(280, sh - 80))
        if w != self.winfo_width() or h != self.winfo_height():
            self.geometry(f"{w}x{h}")
            self.update_idletasks()
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 窗口位置记忆（只写程序同目录，便携版不跨盘）----------
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
        try:
            if IS_WIN and self._hwnd and _win_api().IsZoomed(self._hwnd):
                _win_api().ShowWindow(self._hwnd, 9)
                self.update_idletasks()
        except Exception:
            pass
        self._save_geom()
        self.destroy()

    # ---------- ttk 样式（输入框 / 下拉 / 滚动条）----------
    def _build_style(self):
        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except Exception:
            self.style = ttk.Style(self)
        s = self.style
        s.configure("TLabel", background=CARD, foreground=TEXT, font=FONT)
        s.configure("TEntry", fieldbackground="#FFFFFF", foreground=TEXT,
                    bordercolor="#D1D1D6", lightcolor="#D1D1D6", darkcolor="#D1D1D6",
                    insertcolor=ACCENT, borderwidth=1, relief="solid", padding=6,
                    font=FONT)
        s.map("TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        s.configure("TCombobox", fieldbackground="#FFFFFF", foreground=TEXT,
                    background="#FFFFFF", bordercolor="#D1D1D6",
                    arrowcolor=SUB, borderwidth=1, padding=5, font=FONT)
        s.map("TCombobox", bordercolor=[("focus", ACCENT)],
              fieldbackground=[("readonly", "#FFFFFF")])
        s.configure("TSpinbox", fieldbackground="#FFFFFF", foreground=TEXT,
                    bordercolor="#D1D1D6", arrowcolor=SUB, borderwidth=1,
                    padding=5, font=FONT)
        s.configure("Plain.TCombobox", fieldbackground="#FFFFFF", foreground=TEXT,
                    background="#FFFFFF", bordercolor="#FFFFFF",
                    lightcolor="#FFFFFF", darkcolor="#FFFFFF",
                    arrowcolor=SUB, borderwidth=0, relief="flat",
                    padding=4, font=FONT)
        s.map("Plain.TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
              bordercolor=[("readonly", "#FFFFFF")])
        s.configure("TScrollbar", background="#E4E4EA", troughcolor=CARD,
                    bordercolor=CARD, arrowcolor=SUB, relief="flat", width=10)
        s.configure("Vertical.TScrollbar", background="#D8D8DF", troughcolor=CARD,
                    bordercolor=CARD, arrowcolor=SUB, relief="flat")

    # ---------- 侧边栏 ----------
    def _build_sidebar(self):
        import tkinter.font as tkfont

        def px(text, spec):
            try:
                return tkfont.Font(root=self, font=spec).measure(text)
            except Exception:
                return 0

        items = (("新建下载", "plus"), ("任务列表", "list"),
                 ("完成记录", "check"), ("设置", "gear"))
        need = max([px("高速下载器", (UI_FAM, 14, "bold")),
                    px("Fast Downloader", FONT_XS)]
                   + [42 + px(n, FONT_S) + 18 for n, _ in items])
        width = max(_s(206), min(_s(300), int(need)))
        self._side_min = width

        side = tk.Frame(self._body, width=width, bg=SIDEBAR)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.side = side
        tk.Frame(side, bg=SEPARATOR, width=1).place(
            relx=1.0, y=0, relheight=1, anchor="ne")

        head = tk.Frame(side, bg=SIDEBAR)
        head.pack(fill="x", padx=16, pady=(20, 16))
        ic = tk.Canvas(head, width=_s(38), height=_s(38), bg=SIDEBAR, highlightthickness=0)
        ic.pack(side="left", anchor="n", padx=(0, 10))
        _solid_rr(ic, 1, 1, _s(37), _s(37), _s(9), FILE_TINT)
        _solid_rr(ic, 1, 1, _s(37), _s(19), _s(9), "#3D9BFF")
        ic.create_rectangle(1, _s(16), _s(37), _s(28), fill=FILE_TINT, outline="")
        # 白色下载箭头 + 托盘
        ic.create_line(_s(19), _s(10), _s(19), _s(24), fill="white",
                       width=max(2, _s(2.6)), capstyle="round")
        ic.create_line(_s(13), _s(18), _s(19), _s(24), _s(25), _s(18),
                       fill="white", width=max(2, _s(2.6)),
                       capstyle="round", joinstyle="round")
        ic.create_line(_s(12), _s(29), _s(26), _s(29), fill="white",
                       width=max(2, _s(2.6)), capstyle="round")

        txt = tk.Frame(head, bg=SIDEBAR)
        txt.pack(side="left", fill="x")
        tk.Label(txt, text="高速下载器", bg=SIDEBAR, fg=TEXT,
                 font=(UI_FAM, 14, "bold"), anchor="w").pack(anchor="w", pady=(1, 0))
        tk.Label(txt, text="Fast Downloader", bg=SIDEBAR, fg=SUB,
                 font=FONT_XS, anchor="w").pack(anchor="w", pady=(2, 0))

        tk.Frame(side, bg="#D9D9E0", height=1).pack(fill="x", padx=16, pady=(0, 12))

        nav_wrap = tk.Frame(side, bg=SIDEBAR)
        nav_wrap.pack(fill="x", padx=10)
        for name, glyph in items:
            item = NavItem(nav_wrap, self, name, glyph, width - 20)
            item.pack(fill="x", pady=2)
            self._nav[name] = item

        tk.Label(side, text=f"v{APP_VERSION}", bg=SIDEBAR, fg="#A5A5AC",
                 font=FONT_XS).pack(side="bottom", anchor="w", padx=18, pady=(0, 16))

    # ---------- 内容区 ----------
    def _build_content(self):
        self.content = tk.Frame(self._body, bg=BG_MAIN)
        self.content.pack(side="right", fill="both", expand=True)

    def _show(self, name):
        self.current = name
        self._titlebar.set_page(name)
        for n, item in self._nav.items():
            item._set(selected=(n == name))
        for f in self._panels.values():
            f.pack_forget()
        self._panels[name].pack(fill="both", expand=True, padx=26, pady=22)

    # ---------- 新建下载 ----------
    def _build_new(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["新建下载"] = wrap
        card = Card(wrap, fit=True)
        card.pack(fill="x")
        body = card._body
        tk.Label(body, text="新建下载任务", bg=CARD, fg=TEXT,
                 font=FONT_T).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(body, text="粘贴直链或网盘分享链接，支持分块并发与断点续传",
                 bg=CARD, fg=SUB, font=FONT_SM).pack(anchor="w", padx=24, pady=(0, 14))

        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=24, pady=(0, 20))
        f.columnconfigure(0, weight=1)

        tk.Label(f, text="下载链接", bg=CARD, fg=TEXT, font=FONT,
                 anchor="w").grid(row=0, column=0, sticky="w", pady=(4, 4))
        row0 = tk.Frame(f, bg=CARD)
        row0.grid(row=1, column=0, columnspan=3, sticky="ew", pady=2)
        row0.columnconfigure(0, weight=1)
        self.url_e = Field(row0, _make_entry)
        self.url_e.grid(row=0, column=0, sticky="ew")
        MacButton(row0, "解析", self._resolve, kind="link", width=88,
                  bg=CARD).grid(row=0, column=1, padx=(8, 0))

        tk.Label(f, text="保存位置", bg=CARD, fg=TEXT, font=FONT,
                 anchor="w").grid(row=2, column=0, sticky="w", pady=(14, 4))
        row1 = tk.Frame(f, bg=CARD)
        row1.grid(row=3, column=0, columnspan=3, sticky="ew", pady=2)
        row1.columnconfigure(0, weight=1)
        self.save_e = Field(row1, _make_entry)
        self.save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.save_e.grid(row=0, column=0, sticky="ew")
        MacButton(row1, "浏览…", self._choose_dir, width=88,
                  bg=CARD).grid(row=0, column=1, padx=(8, 0))

        tk.Label(f, text="文件名（留空自动）", bg=CARD, fg=TEXT, font=FONT,
                 anchor="w").grid(row=4, column=0, sticky="w", pady=(14, 4))
        rown = tk.Frame(f, bg=CARD)
        rown.grid(row=5, column=0, columnspan=3, sticky="ew", pady=2)
        rown.columnconfigure(0, weight=1)
        rown.columnconfigure(1, minsize=96)  # 与带按钮的两行保持同一右边缘
        self.name_e = Field(rown, _make_entry)
        self.name_e.grid(row=0, column=0, sticky="ew")

        tk.Label(f, text="线程数", bg=CARD, fg=TEXT, font=FONT,
                 anchor="w").grid(row=6, column=0, sticky="w", pady=(14, 4))
        self.threads_e = Field(f, lambda c: _make_combo(
            c, [str(i) for i in range(1, 17)], "8"), width=116)
        self.threads_e.grid(row=7, column=0, sticky="w", pady=2)

        self.new_info = tk.Label(f, text="", bg=CARD, fg=SUB, font=FONT_SM, anchor="w")
        self.new_info.grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 4))

        btns = tk.Frame(f, bg=CARD)
        btns.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        MacButton(btns, "开始下载", self._add_task, kind="primary",
                  width=120, bg=CARD).pack(side="left", padx=(0, 10))
        MacButton(btns, "打开文件夹", self._open_folder, width=112,
                  bg=CARD).pack(side="left")

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
            self.new_info.config(
                text=f"文件名：{name}    大小：{_fmt(total) if total else '未知'}    "
                     f"支持分块：{'是' if ranged else '否'}")
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
        try:
            threads = int(self.threads_e.get() or 8)
        except Exception:
            threads = 8
        t = Task(url, self.save_e.get() or ".", self.name_e.get().strip() or None, threads)
        self.mgr.add(t)
        self._show("任务列表")

    # ---------- 任务列表 ----------
    def _build_tasks(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["任务列表"] = wrap
        card = Card(wrap)
        card.pack(fill="both", expand=True)
        body = card._body
        tk.Label(body, text="任务列表", bg=CARD, fg=TEXT,
                 font=FONT_T).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(body, text="正在下载与排队中的任务", bg=CARD, fg=SUB,
                 font=FONT_SM).pack(anchor="w", padx=24, pady=(0, 10))
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
        tk.Label(body, text="完成记录", bg=CARD, fg=TEXT,
                 font=FONT_T).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(body, text="已结束的全部任务", bg=CARD, fg=SUB,
                 font=FONT_SM).pack(anchor="w", padx=24, pady=(0, 10))
        self.done_list = TaskList(body, self.mgr, lambda a, t: None)
        self.done_list.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    # ---------- 设置 ----------
    def _build_settings(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["设置"] = wrap
        card = Card(wrap, fit=True)
        card.pack(fill="x")
        body = card._body
        tk.Label(body, text="设置", bg=CARD, fg=TEXT,
                 font=FONT_T).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(body, text="调整并发与默认下载参数", bg=CARD, fg=SUB,
                 font=FONT_SM).pack(anchor="w", padx=24, pady=(0, 14))
        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=24, pady=(0, 22))
        f.columnconfigure(0, minsize=150)
        f.columnconfigure(1, weight=1)

        tk.Label(f, text="最大同时下载数", bg=CARD, fg=TEXT,
                 font=FONT).grid(row=0, column=0, sticky="w", pady=9)
        self.max_e = Field(f, lambda c: _make_combo(
            c, [str(i) for i in range(1, 11)], str(self.mgr.max_concurrent)), width=116)
        self.max_e.grid(row=0, column=1, sticky="w", pady=9)

        tk.Label(f, text="默认保存位置", bg=CARD, fg=TEXT,
                 font=FONT).grid(row=1, column=0, sticky="w", pady=(14, 5))
        row = tk.Frame(f, bg=CARD)
        row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        row.columnconfigure(0, weight=1)
        self.def_save_e = Field(row, _make_entry)
        self.def_save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.def_save_e.grid(row=0, column=0, sticky="ew")
        MacButton(row, "浏览…", self._choose_def, width=88,
                  bg=CARD).grid(row=0, column=1, padx=(8, 0))

        tk.Label(f, text="默认线程数", bg=CARD, fg=TEXT,
                 font=FONT).grid(row=3, column=0, sticky="w", pady=(14, 5))
        self.def_threads_e = Field(f, lambda c: _make_combo(
            c, [str(i) for i in range(1, 17)], "8"), width=116)
        self.def_threads_e.grid(row=3, column=1, sticky="w", pady=5)

        MacButton(f, "保存设置", self._save_settings, kind="primary",
                  width=112, bg=CARD).grid(row=4, column=0, sticky="w", pady=(20, 0))

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
