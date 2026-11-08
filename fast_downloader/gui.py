"""图形界面：Windows 简约矢量风格下载管理器（tkinter，运行时零第三方依赖）。"""

from __future__ import annotations

import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import github, netdisk
from .core import DEFAULT_THREADS, MAX_THREADS, Downloader, DownloadError

APP_VERSION = "1.5.3"

# 默认窗口尺寸：1000×600 物理像素（用户指定够用的尺寸）。
DEFAULT_W, DEFAULT_H = 1000, 600
# 窗口位置记忆文件的格式版本。旧版只写 "1500x1020+530+290"，
# 改默认尺寸后若继续沿用旧记录，新装的程序仍会按老尺寸打开，因此换格式一次性重来。
GEOM_VERSION = "v2"

# 线程数下拉档位：不给 1~128 全列（太长、还会诱导选无意义的碎块），
# 只给工程上真正有区别的几档，选满 128 时也会按文件大小自动收敛分块数。
THREAD_CHOICES = ["8", "16", "24", "32", "48", "64", "96", "128"]

# 几何按真实 DPI 等比放大：字体由 tk scaling 放大，固定像素若不跟着放大，
# 高 DPI 屏上细线/小图标会显得发虚、拥挤。
SCALE = 1.0
PADX = 24
PADY = 20
CARD_PAD = 12


def _s(v):
    return max(1, int(round(v * SCALE)))


# ---------- 柔和矢量设计令牌：圆角 + 低对比 + 极轻投影，不用任何图片资源 ----------
SIDEBAR = "#FBFCFD"       # 左侧导航（几乎与内容区同色，靠明度差分层）
BG_MAIN = "#F2F4F7"       # 内容区底色
CARD = "#FFFFFF"          # 卡片 / 输入区
BORDER = "#EAEEF3"        # 卡片描边（很淡，主要靠投影分层）
SHADOW = "#E3E8EF"        # 卡片底部 2px 投影
SEPARATOR = "#EFF2F6"     # 分隔线
FIELD_BG = "#F2F4F8"      # 输入框填充色（无描边，焦点时才描边）
FIELD_HOVER = "#ECF0F5"
FIELD_BORDER = "#D8DFE8"
ACCENT = "#3A76E8"        # 柔和强调蓝
ACCENT_D = "#2761CC"
ACCENT_SOFT = "#EAF1FD"
TEXT = "#23272E"
LABEL = "#3F4650"      # 表单标签：比正文轻一档
SUB = "#7C8490"
SUCCESS_BG = "#E7F6ED"
SUCCESS_FG = "#2C7A50"
ROW_LINE = "#F2F5F9"
TRACK = "#EBF0F6"
FILE_TINT = "#3A76E8"

# 圆角半径：卡片大、输入/按钮中、导航小，形成统一的柔和节奏
CARD_R = 14
FIELD_R = 9
BTN_R = 9
NAV_R = 9

UI_FAM = "Segoe UI"
FONT = ("Segoe UI", 11)
FONT_T = ("Segoe UI", 16, "bold")
FONT_S = ("Segoe UI", 12)
FONT_SM = ("Segoe UI", 10)
FONT_XS = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI", 13)
FONT_BTN = ("Segoe UI", 11, "bold")


def _init_fonts(root):
    """使用系统原生 UI 字体（中文自动回退雅黑），并按真实 DPI 计算缩放。"""
    global UI_FAM, FONT, FONT_T, FONT_S, FONT_SM, FONT_XS, FONT_TITLE, FONT_BTN
    global SCALE, PADX, PADY, CARD_PAD
    try:
        import ctypes
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
    except Exception:
        dpi = 96
    SCALE = max(1.0, min(2.5, (dpi or 96) / 96.0))
    PADX, PADY, CARD_PAD = _s(24), _s(20), _s(12)
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


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    """两色线性混合，用来做悬停过渡与极轻投影。"""
    t = max(0.0, min(1.0, t))
    pa, pb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(
        int(round(x + (y - x) * t)) for x, y in zip(pa, pb))


def _box(c, x1, y1, x2, y2, fill, outline=None, width=1, tags=None, r=0):
    """圆角矩形：矢量风格的基本构件。r=0 退化为直角。"""
    kw = {"fill": fill or "", "outline": outline or "", "width": width}
    if tags:
        kw["tags"] = tags
    r = int(r)
    if r <= 0:
        return c.create_rectangle(x1, y1, x2, y2, **kw)
    r = min(r, int((x2 - x1) // 2), int((y2 - y1) // 2))
    if r <= 0:
        return c.create_rectangle(x1, y1, x2, y2, **kw)
    pts = []
    steps = 7
    for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                       (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for i in range(steps + 1):
            a = math.radians(a0 + 90.0 * i / steps)
            pts.extend((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return c.create_polygon(pts, **kw)


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


class FlatButton(tk.Canvas):
    """柔和矢量按钮：圆角、无硬描边，悬停与按下带 60ms 颜色过渡。"""

    H = 34

    def __init__(self, parent, text, command, kind="secondary", width=100, bg=CARD):
        self.H = _s(34)
        super().__init__(parent, width=_s(width), height=self.H, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self.text, self.command, self.kind = text, command, kind
        self._bg = bg
        self._hover = False
        self._down = False
        self._shown = None      # 当前正在显示的 (fill, fg)
        self._job = None
        self.bind("<Enter>", lambda e: self._state(hover=True))
        self.bind("<Leave>", lambda e: self._state(hover=False, down=False))
        self.bind("<Button-1>", lambda e: self._state(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.configure(cursor="hand2")
        self._animate(instant=True)

    def _state(self, hover=None, down=None):
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self._animate()

    def _release(self, e):
        self._down = False
        self._animate()
        if self.command:
            self.command()

    def resize(self, width):
        """窄窗口下让主按钮跟着变宽，始终保持饱满的一行。"""
        w = max(_s(48), int(width))
        if abs(w - self.winfo_reqwidth()) > 1:
            self.configure(width=w)
            self._paint()

    def _target(self):
        """返回 (fill, fg)；fill 为 None 表示不铺底色（文字按钮常态）。"""
        if self.kind == "primary":
            if self._down:
                return (ACCENT_D, "#FFFFFF")
            if self._hover:
                return (_mix(ACCENT, "#FFFFFF", 0.12), "#FFFFFF")
            return (ACCENT, "#FFFFFF")
        if self.kind == "link":
            if self._hover or self._down:
                return (ACCENT_SOFT, ACCENT_D)
            return (None, ACCENT_D)
        if self._down:
            return ("#DCE3EC", TEXT)
        if self._hover:
            return ("#E7ECF3", TEXT)
        return ("#EFF2F7", TEXT)

    def _animate(self, instant=False):
        target = self._target()
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if instant or self._shown is None or self._shown == target:
            self._shown = target
            self._paint()
            return
        start = self._shown
        steps, state = 4, {"i": 0}

        def step():
            state["i"] += 1
            t = state["i"] / steps
            fill = target[0]
            if start[0] and target[0]:
                fill = _mix(start[0], target[0], t)
            self._shown = (fill, target[1])
            self._paint()
            if state["i"] < steps and self.winfo_exists():
                self._job = self.after(15, step)
            else:
                self._shown = target
                self._job = None
                self._paint()

        self._job = self.after(8, step)

    def _paint(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = self.winfo_reqwidth(), self.H
        fill, fg = self._shown or self._target()
        if fill:
            _box(self, 0, 0, w, h, fill, r=BTN_R * SCALE)
        self.create_text(w / 2, h / 2 + 0.5, text=self.text, fill=fg,
                         font=FONT_BTN if self.kind == "primary" else FONT)

    _draw = _paint



def _make_entry(parent):
    return tk.Entry(parent, relief="flat", bd=0, bg=CARD, fg=TEXT,
                    font=FONT, insertbackground=ACCENT, highlightthickness=0,
                    selectbackground=ACCENT_SOFT, selectforeground=TEXT)


def _make_combo(parent, values, default):
    c = ttk.Combobox(parent, values=values, state="readonly", font=FONT,
                     style="Plain.TCombobox")
    c.set(default)
    return c


def _ui_threads(value=None) -> int:
    """把下拉字符串收敛成合法线程数：空值走默认，越界夹到 [1, MAX_THREADS]。"""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_THREADS
    return max(1, min(n, MAX_THREADS))


class Field(tk.Frame):
    """柔和输入框：默认浅灰填充、无描边；获得焦点时变白并浮出一圈强调色。

    容器是自绘 Canvas，内嵌无边框 Entry / Combobox，视觉上完全融为一体。
    """

    H = 36

    def __init__(self, parent, factory, width=None, bg=CARD):
        self.H = _s(36)
        super().__init__(parent, bg=bg, height=self.H)
        if width:
            self.configure(width=_s(width))
        self.pack_propagate(False)
        self._bg = bg
        self._focus = False
        self._hover = False
        self._cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._cv.pack(fill="both", expand=True)
        self.inner = factory(self._cv)
        self._win = self._cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<FocusIn>", lambda e: self._redraw(True))
        self.inner.bind("<FocusOut>", lambda e: self._redraw(False))
        self._cv.bind("<Enter>", lambda e: self._enter(True))
        self._cv.bind("<Leave>", lambda e: self._enter(False))
        self.bind("<Configure>", lambda e: self._draw())

    def _enter(self, flag):
        self._hover = flag
        self._draw()

    def _redraw(self, focus):
        self._focus = focus
        self._draw()

    def _tint(self):
        if self._focus:
            return CARD
        return FIELD_HOVER if self._hover else FIELD_BG

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        tint = self._tint()
        self._cv.delete("fieldbg")
        # 焦点态：先铺一圈强调色，再盖住内层，得到 1px 圆角描边
        if self._focus:
            _box(self._cv, 0, 0, w, h, ACCENT, r=_s(FIELD_R), tags="fieldbg")
            _box(self._cv, 1, 1, w - 1, h - 1, CARD, r=_s(FIELD_R) - 1,
                 tags="fieldbg")
        else:
            _box(self._cv, 0, 0, w, h, tint, r=_s(FIELD_R), tags="fieldbg")
        self._cv.tag_lower("fieldbg", self._win)
        self._cv.coords(self._win, _s(11), _s(5))
        self._cv.itemconfig(self._win, width=max(_s(10), w - 2 * _s(11)),
                            height=max(_s(10), h - 2 * _s(5)))
        self._paint_inner(tint)

    def _paint_inner(self, tint):
        """让内嵌控件底色跟着容器走，圆角之外不会露出方块。"""
        inner = self.inner
        try:
            if isinstance(inner, ttk.Combobox):
                inner.configure(style="Focus.TCombobox" if self._focus
                                else "Fill.TCombobox")
            else:
                inner.configure(bg=tint,
                                insertbackground=ACCENT if self._focus else TEXT,
                                selectbackground=ACCENT_SOFT)
        except Exception:
            pass


    # 代理常用方法，业务代码无需感知容器
    def get(self):
        return self.inner.get()

    def set(self, value):
        self.inner.set(value)

    def insert(self, *args):
        return self.inner.insert(*args)

    def delete(self, *args):
        return self.inner.delete(*args)


class ThinBar(tk.Canvas):
    """极简纵向滚动条：只有一根圆头细滑块，无箭头、无槽线、无边框。"""

    def __init__(self, parent, command=None, bg=CARD, **kw):
        self._bw = max(3, _s(6))
        super().__init__(parent, width=_s(10), bg=bg,
                         highlightthickness=0, borderwidth=0, takefocus=0, **kw)
        self._cmd = command
        self._first, self._last = 0.0, 1.0
        self._hover = False
        self._grab = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._drop)

    # 作为 canvas 的 yscrollcommand 使用
    def set(self, first, last):
        try:
            first, last = float(first), float(last)
        except (TypeError, ValueError):
            return
        if abs(first - self._first) < 1e-4 and abs(last - self._last) < 1e-4:
            return
        self._first, self._last = first, last
        self._draw()

    def _set_hover(self, flag):
        self._hover = bool(flag)
        self._draw()

    def _geom(self):
        h = max(1, self.winfo_height())
        span = max(0.02, self._last - self._first)
        kh = max(span * h, _s(26))
        rest = h - kh
        ky = 0.0 if span >= 1 else self._first / max(1e-6, 1 - span) * rest
        return h, kh, ky

    def _draw(self):
        self.delete("all")
        h, kh, ky = self._geom()
        if h < 14 or self._last - self._first >= 0.9995:
            return
        x = self.winfo_width() / 2
        col = "#9C9CA5" if (self._hover or self._grab is not None) else "#CFCFD6"
        inset = min(_s(3), kh / 4)
        self.create_line(x, ky + inset, x, ky + kh - inset,
                         width=self._bw, fill=col, capstyle="round")

    def _press(self, e):
        h, kh, ky = self._geom()
        if ky <= e.y <= ky + kh:
            self._grab = e.y - ky
        else:
            self._grab = kh / 2
            self._scroll(e.y)
        self._draw()

    def _move(self, e):
        if self._grab is None:
            return
        self._scroll(e.y)

    def _drop(self, e):
        self._grab = None
        self._draw()

    def _scroll(self, y):
        h, kh, ky = self._geom()
        if h <= kh or self._last - self._first >= 1 or not self._cmd:
            return
        pos = (y - self._grab) / max(1.0, h - kh)
        self._cmd("moveto", min(1.0, max(0.0, pos)))


class Card(tk.Frame):
    """白色圆角卡片。fit 卡片高度贴合内容（窗口太矮时收缩并浮出细滑块），
    maxw 用来限制内容列宽，避免宽窗口下表单被拉成一条长线。"""

    PAD = 12
    _registry: list["Card"] = []

    def __init__(self, parent, fit=False, maxw=0, **kw):
        super().__init__(parent, bg=BG_MAIN, **kw)
        self.PAD = _s(12)
        self._fit = fit
        self._maxw = int(maxw)
        self._busy = False
        self._sb_on = False
        self._rechecking = False
        self._pend = 0
        # fit 卡片不设固定高度，交给 pack(expand=True) 跟随窗口高度
        self._cv = tk.Canvas(self, bg=BG_MAIN, highlightthickness=0,
                             borderwidth=0, height=265)
        # 滑块浮在卡片上（place 覆盖），不参与布局，避免收缩/展开抖动
        self._sb = ThinBar(self._cv, command=self._cv.yview, bg=CARD)
        self._cv.configure(yscrollcommand=self._sb.set)
        self._cv.pack(fill="both", expand=True)
        self._body = tk.Frame(self._cv, bg=CARD)
        self._win = self._cv.create_window(self.PAD, self.PAD,
                                           window=self._body, anchor="nw")
        # 四个角落遮罩：Tk 的 canvas item 盖不住 create_window 的子窗口，
        # 只有「同级的独立控件」才能压在上面，因此用 4 个小画布还原圆角。
        self._corners = [tk.Canvas(self, bg=CARD, highlightthickness=0,
                                   bd=0, takefocus=0) for _ in range(4)]
        self.bind("<Configure>", self._redraw)
        self._body.bind("<Configure>", self._redraw)
        Card._registry.append(self)

    def _redraw(self, e=None):
        if self._busy:
            return
        self._busy = True
        try:
            self._redraw_inner()
        finally:
            self._busy = False

    def _redraw_inner(self):
        w = self._cv.winfo_width()
        if w < 4:
            return
        self._body.update_idletasks()
        p = self.PAD
        content_h = self._body.winfo_reqheight() + 2 * p + _s(8)
        content_w = self._body.winfo_reqwidth() + 2 * p
        if self._fit:
            # 高度贴合内容：窗口够高时卡片不被拉满，整页更松弛
            avail = self.master.winfo_height()
            want = content_h if avail <= 1 else min(content_h, avail)
            try:
                if abs(int(self._cv.cget("height")) - want) > 1:
                    self._cv.configure(height=want)
                    self.update_idletasks()
            except Exception:
                pass
        h = self._cv.winfo_height()
        if h < 4:
            return
        need_sb = bool(self._fit and content_h > h + 2)
        if need_sb != self._sb_on:
            self._sb_on = need_sb
            if need_sb:
                top = p + _s(CARD_R)
                self._sb.place(in_=self._cv, relx=1.0, x=-(p + _s(11)), y=top,
                               width=_s(10),
                               height=max(_s(20), h - top - p))
                # 启动瞬间窗口尺寸还没稳定，容易误判；一次延迟复核即可纠正
                if not self._rechecking:
                    self._rechecking = True
                    self.after(90, self._recheck)
            else:
                self._sb.place_forget()
        elif need_sb:
            top = p + _s(CARD_R)
            self._sb.place_configure(in_=self._cv, relx=1.0, x=-(p + _s(11)),
                                     y=top, width=_s(10),
                                     height=max(_s(20), h - top - p))
        # create_window 生成的内容窗口也是 canvas item，delete("all") 会连它一起删，
        # 导致卡片内表单消失；这里只删背景 tag。
        self._cv.delete("cardbg")
        r = _s(CARD_R)
        # 先铺 2px 下坠的极淡投影，再压上白色圆角卡片，得到"浮起"的柔和层次
        _box(self._cv, p, p + _s(2), w - p, h - p + _s(2), SHADOW, r=r,
             tags="cardbg")
        _box(self._cv, p, p, w - p, h - p, CARD, BORDER, 1, r=r, tags="cardbg")
        # 内嵌内容窗口是直角的，会盖住圆角：用四个角落小画布把它遮回圆角
        size = r + 2
        for cw, quad in zip(self._corners, ("nw", "ne", "sw", "se")):
            cx = p if quad in ("nw", "sw") else w - p - size
            cy = p if quad in ("nw", "ne") else h - p - size
            cw.place(in_=self._cv, x=cx, y=cy, width=size, height=size)
            self._paint_corner(cw, r, quad)
        self._cv.tag_lower("cardbg", self._win)

        inner_w = max(_s(40), w - 2 * p)
        if self._maxw:
            inner_w = min(inner_w, self._maxw)
        self._cv.coords(self._win, p + max(0, (w - 2 * p - inner_w) // 2), p)
        self._cv.itemconfig(self._win, width=inner_w)
        self._cv.itemconfig(self._win, height=(
            self._body.winfo_reqheight() if self._fit else max(_s(40), h - 2 * p)))
        # 内容窗口的宽度要晚一拍才落到 Frame 上：补一拍重绘让列宽收敛，
        # 最多补两次，避免尺寸抖动时陷入无限重绘。
        if abs(self._body.winfo_width() - inner_w) > 1:
            if self._pend < 2:
                self._pend += 1
                self.after(1, self._pending_redraw)
        else:
            self._pend = 0
        self._cv.configure(scrollregion=(0, 0, max(w, content_w),
                                         max(h, content_h)))
        if self._sb_on:
            # ThinBar 本身是 Canvas，.lift() 会落到 tag_raise 上，这里直接 raise 窗口
            self._sb.tk.call("raise", self._sb._w)

    @staticmethod
    def _paint_corner(cw, r, quad):
        """在小方块的角落画出「圆角外侧的月牙」，用来盖住直角内容窗口的角。"""
        cw.delete("all")
        # 角点 P、圆心 C、两条边的方向向量（局部坐标，方块尺寸 r+2）
        P, C, u1, u2 = {
            "nw": ((0, 0), (r, r), (0, -1), (-1, 0)),
            "ne": ((r, 0), (0, r), (0, -1), (1, 0)),
            "sw": ((0, r), (r, 0), (0, 1), (-1, 0)),
            "se": ((r, r), (0, 0), (0, 1), (1, 0)),
        }[quad]
        cx, cy = C
        t1 = (cx + u1[0] * r, cy + u1[1] * r)
        t2 = (cx + u2[0] * r, cy + u2[1] * r)
        a1 = math.atan2(t1[1] - cy, t1[0] - cx)
        a2 = math.atan2(t2[1] - cy, t2[0] - cx)
        d = a2 - a1
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        steps = 9
        arc = []
        for i in range(steps + 1):
            a = a1 + d * i / steps
            arc.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        pts = [P] + arc
        flat = [v for pt in pts for v in pt]
        cw.create_polygon(flat, fill=BG_MAIN, outline="")
        cw.create_line([v for pt in arc for v in pt], fill=BORDER, width=1,
                       smooth=True)

    def _pending_redraw(self):
        self._pend = 0
        self._redraw()

    def _recheck(self):
        self._rechecking = False
        self._redraw()

    def set_density(self, pad, body_pad):
        """窗口变小时收紧卡片内外边距，让内容始终贴着可用空间排布。"""
        pad, body_pad = int(pad), int(body_pad)
        if pad == getattr(self, "_pad", None) and body_pad == getattr(self, "_body_pad", None):
            return
        self._pad, self._body_pad = pad, body_pad
        self.PAD = pad
        # 直角卡片不需要圆角半径
        for ch in self._body.winfo_children():
            try:
                mgr = ch.winfo_manager()
                if mgr == "pack":
                    ch.pack_configure(padx=body_pad)
                elif mgr == "grid":
                    ch.grid_configure(padx=body_pad)
            except Exception:
                pass
        self._redraw()

    def fit(self):
        self._redraw()


class NavItem(tk.Canvas):
    """柔和导航项：选中时一整块圆角浅蓝底 + 强调色文字，无竖条无描边。"""

    H = 38

    def __init__(self, parent, app, name, glyph, width):
        self.H = _s(38)
        super().__init__(parent, width=width, height=self.H, bg=SIDEBAR,
                         highlightthickness=0, bd=0, takefocus=0)
        self.app, self.name, self.glyph = app, name, glyph
        self._sel = False
        self._hover = False
        self._compact = False
        self._shown = None
        self._job = None
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
        self._animate()

    def _target(self):
        if self._sel:
            return ACCENT_SOFT
        if self._hover:
            return "#EFF3F8"
        return None

    def _animate(self):
        target = self._target()
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        start = self._shown
        if start == target:
            return
        steps, state = 4, {"i": 0}

        def step():
            state["i"] += 1
            t = state["i"] / steps
            if start and target:
                self._shown = _mix(start, target, t)
            elif target is None:
                # 淡出：从当前色过渡到侧栏底色，肉眼看起来像渐隐
                self._shown = _mix(start, SIDEBAR, t) if start else None
            else:
                self._shown = _mix(SIDEBAR, target, t) if not start else target
            self._draw()
            if state["i"] < steps and self.winfo_exists():
                self._job = self.after(15, step)
            else:
                self._shown = target
                self._job = None
                self._draw()

        self._job = self.after(8, step)

    def set_compact(self, flag):
        flag = bool(flag)
        if flag != self._compact:
            self._compact = flag
            self.H = _s(32) if flag else _s(38)
            self.configure(height=self.H)
            try:
                self.pack_configure(pady=_s(2) if flag else _s(3))
            except Exception:
                pass
            self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        h = self.H
        pad = _s(4)
        fill = self._shown
        if fill:
            _box(self, pad, _s(1), w - pad, h - _s(1), fill, r=_s(NAV_R))
        ink = ACCENT_D if self._sel else "#5C636E"
        if self._compact:
            _glyph(self, self.glyph, w / 2, h / 2, ink)
        else:
            _glyph(self, self.glyph, _s(26), h / 2, ink)
            self.create_text(_s(46), h / 2 + 0.5, text=self.name, anchor="w",
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


_ELIDE_FONTS = {}


def _elide(text, maxw, font):
    """按像素宽度截断并补省略号，避免文件名被硬切成半截。"""
    if maxw <= 8 or not text:
        return text
    key = tuple(font)
    f = _ELIDE_FONTS.get(key)
    if f is None:
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(font=font)
        except Exception:
            return text
        _ELIDE_FONTS[key] = f
    if f.measure(text) <= maxw:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(text[:mid] + "…") <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


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
        self._sb = ThinBar(self, command=self._canvas.yview, bg=CARD)
        self._inner = tk.Frame(self._canvas, bg=CARD)
        self._win = self._canvas.create_window(0, 0, window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._sb.pack(side="right", fill="y", padx=(0, _s(4)), pady=_s(2))
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
        self._mode = None
        self.bind("<Configure>", self._adapt)

        self.icon = tk.Canvas(self, width=_s(32), height=_s(34), bg=CARD,
                              highlightthickness=0)
        self.icon.grid(row=0, column=0, padx=(_s(4), _s(12)), pady=_s(8))

        # width=1：把请求宽度压到最小，余量全部由列权重给文件名列，
        # 这样每行的状态/进度/操作列都精确对齐，不会随文件名长短左右晃
        self.name = tk.Label(self, text="", bg=CARD, fg=LABEL, font=FONT,
                             anchor="w", width=1)
        self.name.grid(row=0, column=1, sticky="we", pady=(_s(8), 0))
        self.name.bind("<Configure>", self._fit_name)
        self._full_name = ""

        self.stat = tk.Canvas(self, width=_s(66), height=_s(24), bg=CARD,
                              highlightthickness=0)
        self.stat.grid(row=0, column=2, padx=(_s(10), 0), pady=_s(8))

        self.pbar = tk.Canvas(self, width=_s(104), height=_s(8), bg=CARD,
                              highlightthickness=0)
        self.pbar.grid(row=0, column=3, padx=(_s(12), 0), pady=_s(8))

        self.pct = tk.Label(self, text="", bg=CARD, fg=SUB, font=FONT_XS,
                            width=5, anchor="w")
        self.pct.grid(row=0, column=4, padx=(_s(6), 0), pady=_s(8))

        self.meta = tk.Label(self, text="", bg=CARD, fg=SUB, font=FONT_SM,
                             width=24, anchor="w")
        self.meta.grid(row=0, column=5, padx=(_s(10), 0), pady=_s(8))

        # 固定宽度：没任务可取消时空着也不让整行列宽跳动
        self.act = tk.Label(self, text="取消", bg=CARD, fg=ACCENT, font=FONT_SM,
                            cursor="hand2", width=4, anchor="e")
        self.act.grid(row=0, column=6, padx=(_s(10), _s(8)), pady=_s(8))
        self.act.bind("<Button-1>", lambda e: self.on_action("cancel", self.task))
        self.act.bind("<Enter>", lambda e: self.act.configure(fg=ACCENT_D))
        self.act.bind("<Leave>", lambda e: self.act.configure(fg=ACCENT))

        sep = tk.Frame(self, bg=ROW_LINE, height=1)
        sep.grid(row=1, column=0, columnspan=7, sticky="ew", padx=_s(14))

    def _adapt(self, e=None):
        """窗口变窄时按可用宽度收起次要信息列，主文件名永远占满剩余空间。"""
        w = self.winfo_width()
        if w < 20:
            return
        mode = 2 if w < _s(420) else (1 if w < _s(700) else 0)
        if mode == self._mode:
            return
        self._mode = mode
        # 进度条是最关键的信息，中等宽度也要留着；只有极窄时才只保留状态与文件名
        for widget, visible in ((self.meta, mode == 0),
                                (self.pbar, mode <= 1),
                                (self.pct, mode <= 1),
                                (self.stat, True)):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        self._fit_name()

    def _fit_name(self, e=None):
        w = e.width if e is not None else self.name.winfo_width()
        self.name.config(text=_elide(self._full_name, max(0, w - _s(2)), FONT))

    def update(self, t: Task, first=False):
        self.task = t
        self._full_name = t.filename or t.url
        self._fit_name()
        color = _icon_color(t.filename or t.url)
        self.icon.delete("all")
        # 圆角色块 + 细线文档：比纯线框更有分量，也不至于花哨
        _box(self.icon, _s(2), _s(2), _s(30), _s(32),
             _mix(color, "#FFFFFF", 0.86), r=_s(9))
        self.icon.create_rectangle(_s(10), _s(10), _s(22), _s(25),
                                   outline=color, width=max(1, _s(1.4)))
        self.icon.create_line(_s(17), _s(10), _s(17), _s(14), _s(22), _s(14),
                              fill=color, width=max(1, _s(1.4)),
                              joinstyle="round")
        self.icon.create_line(_s(12), _s(18), _s(20), _s(18), fill=color,
                              width=max(1, _s(1.2)), capstyle="round")
        self.icon.create_line(_s(12), _s(21), _s(18), _s(21), fill=color,
                              width=max(1, _s(1.2)), capstyle="round")

        self.stat.delete("all")
        label, bg, fg = {
            "已完成": ("已完成", SUCCESS_BG, SUCCESS_FG),
            "下载中": ("下载中", ACCENT_SOFT, ACCENT_D),
            "排队中": ("排队中", "#F1F3F7", SUB),
        }.get(t.status, (t.status, "#FDEDEC", "#C94A42"))
        h = _s(24)
        _box(self.stat, 0, _s(1), _s(66), h - _s(1), bg, r=h // 2 - 1)
        self.stat.create_text(_s(33), h / 2, text=label, fill=fg, font=FONT_XS)

        self.pbar.delete("all")
        pct = (t.downloaded / t.total * 100) if t.total else 0
        w, bh = _s(104), _s(8)
        _box(self.pbar, 0, 0, w, bh, TRACK, r=bh // 2)
        if pct > 0:
            _box(self.pbar, 0, 0, max(bh, w * pct / 100), bh, ACCENT, r=bh // 2)
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
        # 默认窗口 1000×600 物理像素（用户指定的大小），屏幕比这小则内缩。
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        w = min(DEFAULT_W, max(360, sw - _s(40)))
        h = min(DEFAULT_H, max(280, sh - _s(80)))
        self.geometry(f"{w}x{h}")
        self.resizable(True, True)
        # 最小约一张身份证（85.6×54mm ≈ 320×210 逻辑像素），主打简约。
        # 不再把 minsize 定到 900×680，窗口可真正自由地缩到很小。
        self.minsize(_s(320), _s(210))
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
        # 响应式布局状态
        self._mode = None          # 0 完整 / 1 紧凑 / 2 极简（身份证大小）
        self._compact = None
        self._last_size = None
        self._cur_pad = None
        self._cur_pady = None
        self._pack_opts = {}
        self._pack_before = {}
        self._ready = False
        self._resolving = False    # 后台解析中，防止重复点「解析」

        ico = self._app_path("app.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_style()
        self.bind("<Configure>", self._on_resize)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.configure(bg=BG_MAIN)
        # 关键：不要让子控件的「自然请求尺寸」反过来把顶层窗口撑回去。
        self.pack_propagate(False)
        # 使用 Windows 原生标题栏：拖动、缩放、最小化/最大化/关闭全部交给
        # 系统 DWM，不进入 Tk 的逐帧 geometry 循环 -> 零残影、不卡顿。
        self._body = tk.Frame(self, bg=BG_MAIN)
        self._body.pack(side="top", fill="both", expand=True)
        self._build_sidebar()
        self._build_content()
        self._build_new()
        self._build_tasks()
        self._build_done()
        self._build_settings()
        self._show(self.current)
        for c in Card._registry:
            c.fit()
        self._ready = True
        self.update_idletasks()
        self._relayout(self.winfo_width(), self.winfo_height())
        self._center_on_screen()
        self._tick()

    # ---------- 响应式布局：完整 / 紧凑 / 极简（身份证大小）----------
    def _on_wheel(self, e):
        """滚轮按指针位置路由到所在的卡片或任务列表。"""
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        step = -1 if getattr(e, "delta", 0) > 0 else 1
        while w is not None:
            if isinstance(w, Card):
                if w._sb_on:
                    w._cv.yview_scroll(step, "units")
                return
            if isinstance(w, TaskList):
                w._canvas.yview_scroll(step, "units")
                return
            w = getattr(w, "master", None)

    def _on_resize(self, e):
        """只有尺寸变化才重排；系统原生拖动不会触发任何重绘逻辑。"""
        if e.widget is not self or not getattr(self, "_ready", False):
            return
        if e.width < 2 or e.height < 2:
            return
        size = (e.width, e.height)
        if size == self._last_size:
            return
        self._last_size = size
        self._relayout(e.width, e.height)

    def _pack_state(self, w, visible):
        """记住控件最初的 pack 参数，折叠/展开时原样还原。"""
        if w is None:
            return
        key = id(w)
        if key not in self._pack_opts:
            info = w.pack_info() if w.winfo_manager() == "pack" else {}
            self._pack_opts[key] = {
                k: info[k] for k in ("side", "anchor", "fill", "expand",
                                     "padx", "pady", "ipadx", "ipady") if k in info
            } or {"side": "top"}
            # 记住原来的 pack 顺序，折叠后还原时不能跑到容器末尾
            try:
                slaves = list(w.master.pack_slaves())
                i = slaves.index(w)
                self._pack_before[key] = slaves[i + 1] if i + 1 < len(slaves) else None
            except Exception:
                self._pack_before[key] = None
        if visible:
            if w.winfo_manager() != "pack":
                try:
                    before = self._pack_before.get(key)
                    if before is not None and before.winfo_manager() == "pack":
                        w.pack(before=before, **self._pack_opts[key])
                    else:
                        w.pack(**self._pack_opts[key])
                except Exception:
                    pass
        elif w.winfo_manager():
            try:
                w.pack_forget()
            except Exception:
                pass

    @staticmethod
    def _grid_state(w, visible):
        if w is None:
            return
        try:
            if visible:
                if w.winfo_manager() != "grid":
                    w.grid()        # grid_remove 之后会恢复原先的行列参数
            elif w.winfo_manager() == "grid":
                w.grid_remove()
        except Exception:
            pass

    def _set_info(self, text, err=False):
        """解析结果：跟在按钮右侧显示，不额外占用一行高度。"""
        self._new_info.configure(text=text, fg=("#C0392B" if err else SUB))
        self._info_show(bool(text.strip()))

    def _info_show(self, visible):
        visible = bool(visible) and self._mode != 2
        try:
            cur = self._new_info.winfo_manager()
            if visible and cur != "pack":
                self._new_info.pack(side="left", padx=(_s(12), 0))
            elif not visible and cur == "pack":
                self._new_info.pack_forget()
        except Exception:
            pass

    def _relayout(self, w, h):
        logical = w / max(SCALE, 1.0)
        mode = 0 if logical >= 860 else (1 if logical >= 560 else 2)
        # 侧栏宽度连续跟随窗口；窄屏折叠成图标轨道
        if mode == 0:
            target = max(_s(180), min(_s(280), int(w * 0.18), int(w * 0.32)))
        else:
            target = max(_s(44), min(_s(70), int(w * 0.15)))
        if abs(target - self.side.winfo_width()) > 1:
            self.side.configure(width=target)
        if self._mode != mode:
            self._mode = mode
            self._apply_mode(mode)
        px, py = ((PADX, PADY) if mode == 0 else
                  (_s(14), _s(12)) if mode == 1 else (_s(8), _s(8)))
        if (px, py) != (self._cur_pad, self._cur_pady):
            self._cur_pad, self._cur_pady = px, py
            for panel in self._panels.values():
                if panel.winfo_manager():
                    panel.pack_configure(padx=px, pady=py)

    def _set_sidebar_compact(self, compact):
        self._pack_state(self._side_txt, not compact)
        self._pack_state(self._side_ver, not compact)
        self._pack_state(self._side_sep, not compact)
        try:
            self._side_head.pack_configure(
                padx=0 if compact else _s(16),
                pady=(_s(6), _s(6)) if compact else (_s(20), _s(16)))
            # 紧凑档侧栏只剩图标：图标块要水平居中，否则会贴在左上角
            self._side_ic.pack_configure(
                side="top" if compact else "left",
                anchor="center" if compact else "n",
                padx=0 if compact else (0, _s(10)))
            self._nav_wrap.pack_configure(padx=_s(6) if compact else _s(10))
        except Exception:
            pass

    def _apply_mode(self, mode):
        compact, mini = mode > 0, mode == 2
        pad = CARD_PAD if mode == 0 else (_s(8) if mode == 1 else _s(6))
        body_pad = PADX if mode == 0 else (_s(14) if mode == 1 else _s(8))
        py = PADY if mode == 0 else (_s(5) if mode == 1 else _s(4))
        if compact != self._compact:
            self._compact = compact
            self._set_sidebar_compact(compact)
            for item in self._nav.values():
                item.set_compact(compact)
        # 副标题在窄窗口真正收起（不是留空行），页面标题改小字
        for sub, text in ((self._new_sub, "粘贴直链或网盘分享链接，支持分块并发与断点续传"),
                          (self._tasks_sub, "正在下载与排队中的任务"),
                          (self._done_sub, "已结束的全部任务"),
                          (self._set_sub, "调整并发与默认下载参数")):
            sub.configure(text=text)
            self._pack_state(sub, not compact)
            if not compact:
                sub.pack_configure(padx=body_pad, pady=(0, py))
        for title in (self._new_title, self._tasks_title, self._done_title, self._set_title):
            title.configure(font=FONT_S if compact else FONT_T)
            title.pack_configure(padx=body_pad, pady=(py, 4 if not compact else 2))
        for frm in (self._new_form, self._set_form):
            frm.pack_configure(padx=body_pad, pady=(0, py))
        for lst in (self.tasks_list, self.done_list):
            lst.pack_configure(padx=body_pad, pady=(0, py))
        # 紧凑/极简：把表单行间距压紧，避免中等窗口还要滚动才能看到按钮
        for opts in (self._new_pady, self._set_pady):
            for w, orig in opts.items():
                try:
                    w.grid_configure(pady=(_s(1) if compact else orig))
                except Exception:
                    pass
        # 极简模式：只保留「链接 + 开始下载」，其余字段与次要按钮收起
        for w in self._new_optional:
            self._grid_state(w, not mini)
        self._grid_state(self._parse_btn, not mini)
        self._grid_state(self._threads_note, not mini)
        self._pack_state(self._open_btn, not mini)
        for w in self._set_optional:
            self._grid_state(w, not mini)
        # 解析结果跟着按钮走：极简档收起，其余档按是否有内容决定
        self._info_show(bool(self._new_info.cget("text").strip()))
        self._start_btn.resize(_s(160) if mini else _s(120))
        for c in Card._registry:
            c.set_density(pad, body_pad)

    # ---------- 路径 ----------    # ---------- 路径 ----------
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
        # 无记录（或旧格式记录）：按默认 1000×600 居中摆放
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            return
        w = min(DEFAULT_W, max(360, sw - _s(40)))
        h = min(DEFAULT_H, max(280, sh - _s(80)))
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
            # 只认当前格式；旧的裸 "1500x1020+530+290" 直接忽略，
            # 让升级后的第一次启动按新的默认 1000×600 居中，随后再记忆。
            if not data.startswith(GEOM_VERSION + " "):
                return None
            data = data[len(GEOM_VERSION) + 1:].strip()
            if re.match(r"^\d+x\d+[+-]\d+[+-]\d+$", data):
                return data
        except Exception:
            pass
        return None

    def _save_geom(self):
        try:
            self.update_idletasks()
            with open(self._config_path(), "w", encoding="utf-8") as f:
                f.write(f"{GEOM_VERSION} {self.geometry()}")
        except Exception:
            pass

    def _on_close(self):
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
                    bordercolor=FIELD_BORDER, lightcolor=FIELD_BORDER, darkcolor=FIELD_BORDER,
                    insertcolor=ACCENT, borderwidth=1, relief="solid", padding=6,
                    font=FONT)
        s.map("TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        s.configure("TCombobox", fieldbackground="#FFFFFF", foreground=TEXT,
                    background="#FFFFFF", bordercolor=FIELD_BORDER,
                    arrowcolor=SUB, borderwidth=1, padding=5, font=FONT)
        s.map("TCombobox", bordercolor=[("focus", ACCENT)],
              fieldbackground=[("readonly", "#FFFFFF")])
        s.configure("TSpinbox", fieldbackground="#FFFFFF", foreground=TEXT,
                    bordercolor=FIELD_BORDER, arrowcolor=SUB, borderwidth=1,
                    padding=5, font=FONT)
        s.configure("Plain.TCombobox", fieldbackground="#FFFFFF", foreground=TEXT,
                    background="#FFFFFF", bordercolor="#FFFFFF",
                    lightcolor="#FFFFFF", darkcolor="#FFFFFF",
                    arrowcolor=SUB, borderwidth=0, relief="flat",
                    padding=4, font=FONT)
        s.map("Plain.TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
              bordercolor=[("readonly", "#FFFFFF")])
        # 输入框未聚焦时的浅灰填充：ttk 只能靠样式切换，与 tk.Entry 的 bg 保持一致
        s.configure("Fill.TCombobox", fieldbackground=FIELD_BG, foreground=TEXT,
                    background=FIELD_BG, bordercolor=FIELD_BG,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                    arrowcolor=SUB, borderwidth=0, relief="flat",
                    padding=4, font=FONT)
        s.map("Fill.TCombobox", fieldbackground=[("readonly", FIELD_BG),
                                                 ("!readonly", FIELD_BG)],
              background=[("readonly", FIELD_BG), ("!readonly", FIELD_BG)],
              bordercolor=[("readonly", FIELD_BG)],
              lightcolor=[("readonly", FIELD_BG)],
              darkcolor=[("readonly", FIELD_BG)])
        s.configure("Focus.TCombobox", fieldbackground="#FFFFFF", foreground=TEXT,
                    background="#FFFFFF", bordercolor="#FFFFFF",
                    lightcolor="#FFFFFF", darkcolor="#FFFFFF",
                    arrowcolor=SUB, borderwidth=0, relief="flat",
                    padding=4, font=FONT)
        s.map("Focus.TCombobox", fieldbackground=[("readonly", "#FFFFFF"),
                                                  ("!readonly", "#FFFFFF")],
              background=[("readonly", "#FFFFFF"), ("!readonly", "#FFFFFF")])

        s.configure("TScrollbar", background=FIELD_BORDER, troughcolor=CARD,
                    bordercolor=CARD, arrowcolor=SUB, relief="flat", width=10)
        s.configure("Vertical.TScrollbar", background=FIELD_BORDER, troughcolor=CARD,
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
        head.pack(fill="x", padx=_s(16), pady=(_s(20), _s(18)))
        ic = tk.Canvas(head, width=_s(40), height=_s(40), bg=SIDEBAR,
                       highlightthickness=0)
        ic.pack(side="left", anchor="n", padx=(0, _s(11)))
        self._side_head, self._side_ic = head, ic
        # 圆角蓝色图标块 + 白色下载箭头：比线框方框更柔和、更像成品软件
        _box(ic, 0, 0, _s(40), _s(40), ACCENT, r=_s(11))
        ic.create_line(_s(20), _s(9), _s(20), _s(24), fill="#FFFFFF",
                       width=max(2, _s(2.6)), capstyle="round")
        ic.create_line(_s(13), _s(17), _s(20), _s(24), _s(27), _s(17),
                       fill="#FFFFFF", width=max(2, _s(2.6)),
                       capstyle="round", joinstyle="round")
        ic.create_line(_s(12), _s(30), _s(28), _s(30), fill="#FFFFFF",
                       width=max(2, _s(2.6)), capstyle="round")

        txt = tk.Frame(head, bg=SIDEBAR)
        txt.pack(side="left", fill="x")
        self._side_txt = txt
        tk.Label(txt, text="高速下载器", bg=SIDEBAR, fg=TEXT,
                 font=(UI_FAM, 14, "bold"), anchor="w").pack(anchor="w", pady=(1, 0))
        tk.Label(txt, text="Fast Downloader", bg=SIDEBAR, fg=SUB,
                 font=FONT_XS, anchor="w").pack(anchor="w", pady=(3, 0))

        sep = tk.Frame(side, bg=SEPARATOR, height=1)
        sep.pack(fill="x", padx=_s(18), pady=(0, _s(14)))
        self._side_sep = sep

        nav_wrap = tk.Frame(side, bg=SIDEBAR)
        nav_wrap.pack(fill="x", padx=_s(10))
        self._nav_wrap = nav_wrap
        for name, glyph in items:
            item = NavItem(nav_wrap, self, name, glyph, width - 20)
            item.pack(fill="x", pady=_s(3))
            self._nav[name] = item

        ver = tk.Label(side, text=f"v{APP_VERSION}", bg=SIDEBAR, fg=SUB,
                       font=FONT_XS)
        ver.pack(side="bottom", anchor="w", padx=_s(18), pady=(0, _s(16)))
        self._side_ver = ver

    # ---------- 内容区 ----------
    def _build_content(self):
        self.content = tk.Frame(self._body, bg=BG_MAIN)
        self.content.pack(side="right", fill="both", expand=True)

    def _show(self, name):
        self.current = name
        self.title(f"{name} · 高速下载器")
        for n, item in self._nav.items():
            item._set(selected=(n == name))
        for f in self._panels.values():
            f.pack_forget()
        self._panels[name].pack(
            fill="both", expand=True,
            padx=PADX if self._cur_pad is None else self._cur_pad,
            pady=PADY if self._cur_pady is None else self._cur_pady)

    # ---------- 新建下载 ----------
    def _build_new(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["新建下载"] = wrap
        card = Card(wrap, fit=True, maxw=_s(700))
        card.pack(fill="x")
        body = card._body
        self._new_title = tk.Label(body, text="新建下载任务", bg=CARD, fg=TEXT,
                                   font=FONT_T)
        self._new_title.pack(anchor="w", padx=PADX, pady=(PADY, _s(6)))
        self._new_sub = tk.Label(
            body, text="粘贴直链或网盘分享链接，支持分块并发与断点续传",
            bg=CARD, fg=SUB, font=FONT_SM)
        self._new_sub.pack(anchor="w", padx=PADX, pady=(0, _s(18)))
        self._new_body = body

        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=PADX, pady=(0, PADY))
        f.columnconfigure(0, weight=1)
        self._new_form = f

        url_label = tk.Label(f, text="下载链接", bg=CARD, fg=TEXT, font=FONT,
                             anchor="w")
        url_label.grid(row=0, column=0, sticky="w", pady=(_s(2), _s(6)))
        row0 = tk.Frame(f, bg=CARD)
        row0.grid(row=1, column=0, columnspan=3, sticky="ew", pady=2)
        row0.columnconfigure(0, weight=1)
        self.url_e = Field(row0, _make_entry)
        self.url_e.grid(row=0, column=0, sticky="ew")
        self._parse_btn = FlatButton(row0, "解析", self._resolve, kind="link",
                                    width=88, bg=CARD)
        self._parse_btn.grid(row=0, column=1, padx=(_s(8), 0))

        save_label = tk.Label(f, text="保存位置", bg=CARD, fg=TEXT, font=FONT,
                              anchor="w")
        save_label.grid(row=2, column=0, sticky="w", pady=(_s(16), _s(6)))
        row1 = tk.Frame(f, bg=CARD)
        row1.grid(row=3, column=0, columnspan=3, sticky="ew", pady=2)
        row1.columnconfigure(0, weight=1)
        self.save_e = Field(row1, _make_entry)
        self.save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.save_e.grid(row=0, column=0, sticky="ew")
        self._browse_btn = FlatButton(row1, "浏览…", self._choose_dir,
                                     width=88, bg=CARD)
        self._browse_btn.grid(row=0, column=1, padx=(_s(8), 0))

        name_label = tk.Label(f, text="文件名（留空自动）", bg=CARD, fg=TEXT,
                              font=FONT, anchor="w")
        name_label.grid(row=4, column=0, sticky="w", pady=(_s(16), _s(6)))
        rown = tk.Frame(f, bg=CARD)
        rown.grid(row=5, column=0, columnspan=3, sticky="ew", pady=2)
        rown.columnconfigure(0, weight=1)
        rown.columnconfigure(1, minsize=_s(96))  # 与带按钮的两行保持同一右边缘
        self.name_e = Field(rown, _make_entry)
        self.name_e.grid(row=0, column=0, sticky="ew")

        # 线程数提示并入标签：单独占一行会让 1000×600 默认尺寸下多出约 40px，
        # 卡片底部被挤出可视区，右侧常驻细滚动条。
        threads_label = tk.Label(
            f, text=f"线程数（默认 {DEFAULT_THREADS}，最高 {MAX_THREADS}）",
            bg=CARD, fg=LABEL, font=FONT, anchor="w")
        threads_label.grid(row=6, column=0, sticky="w", pady=(_s(16), _s(6)))
        self.threads_e = Field(f, lambda c: _make_combo(
            c, THREAD_CHOICES, str(DEFAULT_THREADS)),
            width=116)
        self.threads_e.grid(row=7, column=0, sticky="w", pady=2)
        self._threads_note = threads_label

        btns = tk.Frame(f, bg=CARD)
        btns.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(_s(14), 0))
        self._start_btn = FlatButton(btns, "开始下载", self._add_task,
                                    kind="primary", width=120, bg=CARD)
        self._start_btn.pack(side="left", padx=(0, _s(10)))
        self._open_btn = FlatButton(btns, "打开文件夹", self._open_folder,
                                   width=112, bg=CARD)
        self._open_btn.pack(side="left")
        # 解析结果显示在按钮右侧同一行：单独占一行会让 1000×600 下的卡片
        # 高出一截，右侧常驻细滚动条
        self.new_info = tk.Label(btns, text="", bg=CARD, fg=SUB, font=FONT_SM,
                                 anchor="w")
        self._new_info = self.new_info
        # 极简模式下收起的控件
        self._new_optional = [save_label, row1, name_label, rown,
                              threads_label, self.threads_e]
        self._new_pady = {w: w.grid_info().get("pady", "0") for w in f.grid_slaves()}

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
        if self._resolving:
            return
        self._resolving = True
        self._resolve_q = queue.Queue()
        self._set_info("正在解析链接…")
        # 解析要发网络请求（GitHub 页面还要打 API），放后台线程，
        # 避免慢域名把界面卡住十几秒。注意：控件只能在主线程读，
        # 保存目录与线程数先取好再传进去；结果用队列回传，子线程不碰 Tk。
        threading.Thread(
            target=self._resolve_bg,
            args=(url, self.save_e.get() or ".", _ui_threads()),
            daemon=True).start()
        self.after(120, self._poll_resolve)

    def _resolve_bg(self, url, save_dir, threads):
        info, name, err = "", None, None
        try:
            dl = Downloader(url, save_dir, threads=threads)
            dl.prepare()
            total, ranged = dl.probe()
            name = dl.filename
            # 结果显示在按钮右侧，横向空间有限，只留最关键的三项
            info = (f"{name} · {_fmt(total) if total else '未知'} · "
                    f"{'可分块' if ranged else '单线程'}")
            if dl.resolve_note:
                info = f"{info} · {dl.resolve_note}"
        except Exception as e:
            err = (github.describe_error(url, e)
                   if github.is_github(url) else str(e))
        self._resolve_q.put((info, name, err))

    def _poll_resolve(self):
        if not self._resolving:
            return
        try:
            info, name, err = self._resolve_q.get_nowait()
        except queue.Empty:
            self.after(120, self._poll_resolve)
            return
        self._resolving = False
        self._resolve_done(info, name, err)

    def _resolve_done(self, info, name, err):
        if err:
            # 就地一行提示，不弹模态框打断操作
            self._set_info(_elide(err, _s(380), FONT_SM), err=True)
            return
        self._set_info(_elide(info, _s(380), FONT_SM))
        if name and not self.name_e.get().strip():
            self.name_e.delete(0, tk.END)
            self.name_e.insert(0, name)

    def _add_task(self):
        url = self.url_e.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先填写下载链接")
            return
        threads = _ui_threads(self.threads_e.get())
        name = self.name_e.get().strip() or None
        # GitHub 页面链接先就地解析成真实文件地址，任务里只存直链：
        # 免得每刷新一次界面就去打一次 API，也便于之后「重试」直接复用
        if github.is_github(url):
            try:
                tmp = Downloader(url, self.save_e.get() or ".", threads=threads)
                tmp.prepare()
                url = tmp.effective_url
                if not name:
                    name = tmp.filename
            except Exception as e:
                messagebox.showerror("解析失败", github.describe_error(url, e))
                return
        t = Task(url, self.save_e.get() or ".", name, threads)
        self.mgr.add(t)
        self._show("任务列表")

    # ---------- 任务列表 ----------
    def _build_tasks(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["任务列表"] = wrap
        card = Card(wrap)
        card.pack(fill="both", expand=True)
        body = card._body
        self._tasks_title = tk.Label(body, text="任务列表", bg=CARD, fg=TEXT,
                                     font=FONT_T)
        self._tasks_title.pack(anchor="w", padx=PADX, pady=(PADY, _s(6)))
        self._tasks_sub = tk.Label(body, text="正在下载与排队中的任务", bg=CARD,
                                   fg=SUB, font=FONT_SM)
        self._tasks_sub.pack(anchor="w", padx=PADX, pady=(0, _s(12)))
        self.tasks_list = TaskList(body, self.mgr, self._on_task_action)
        self.tasks_list.pack(fill="both", expand=True, padx=_s(14), pady=(0, _s(14)))

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
        self._done_title = tk.Label(body, text="完成记录", bg=CARD, fg=TEXT,
                                    font=FONT_T)
        self._done_title.pack(anchor="w", padx=PADX, pady=(PADY, _s(6)))
        self._done_sub = tk.Label(body, text="已结束的全部任务", bg=CARD, fg=SUB,
                                  font=FONT_SM)
        self._done_sub.pack(anchor="w", padx=PADX, pady=(0, _s(12)))
        self.done_list = TaskList(body, self.mgr, lambda a, t: None)
        self.done_list.pack(fill="both", expand=True, padx=_s(14), pady=(0, _s(14)))

    # ---------- 设置 ----------
    def _build_settings(self):
        wrap = tk.Frame(self.content, bg=BG_MAIN)
        self._panels["设置"] = wrap
        card = Card(wrap, fit=True, maxw=_s(700))
        card.pack(fill="x")
        body = card._body
        self._set_title = tk.Label(body, text="设置", bg=CARD, fg=TEXT,
                                   font=FONT_T)
        self._set_title.pack(anchor="w", padx=PADX, pady=(PADY, _s(6)))
        self._set_sub = tk.Label(body, text="调整并发与默认下载参数", bg=CARD,
                                 fg=SUB, font=FONT_SM)
        self._set_sub.pack(anchor="w", padx=PADX, pady=(0, _s(16)))
        f = tk.Frame(body, bg=CARD)
        f.pack(fill="x", padx=PADX, pady=(0, PADY))
        # 两列式：左侧标签列定宽，右侧控件列吃掉余量，所有行自然对齐
        f.columnconfigure(0, minsize=_s(132))
        f.columnconfigure(1, weight=1)
        self._set_form = f

        def label(text, row):
            w = tk.Label(f, text=text, bg=CARD, fg=LABEL, font=FONT, anchor="w")
            w.grid(row=row, column=0, sticky="w", pady=_s(10))
            return w

        l_max = label("最大同时下载数", 0)
        self.max_e = Field(f, lambda c: _make_combo(
            c, [str(i) for i in range(1, 11)], str(self.mgr.max_concurrent)),
            width=116)
        self.max_e.grid(row=0, column=1, sticky="w", pady=_s(10))

        l_threads = label("默认线程数", 1)
        self.def_threads_e = Field(f, lambda c: _make_combo(
            c, THREAD_CHOICES, str(DEFAULT_THREADS)), width=116)
        self.def_threads_e.grid(row=1, column=1, sticky="w", pady=_s(10))

        l_save = label("默认保存位置", 2)
        row = tk.Frame(f, bg=CARD)
        row.grid(row=2, column=1, sticky="ew", pady=_s(10))
        row.columnconfigure(0, weight=1)
        self.def_save_e = Field(row, _make_entry)
        self.def_save_e.insert(0, os.path.join(os.path.expanduser("~"), "Desktop"))
        self.def_save_e.grid(row=0, column=0, sticky="ew")
        self._choose_def_btn = FlatButton(row, "浏览…", self._choose_def,
                                         width=88, bg=CARD)
        self._choose_def_btn.grid(row=0, column=1, padx=(_s(8), 0))

        FlatButton(f, "保存设置", self._save_settings, kind="primary",
                   width=112, bg=CARD).grid(row=3, column=0, columnspan=2,
                                            sticky="w", pady=(_s(22), 0))
        self._set_optional = [l_save, row, l_threads, self.def_threads_e]
        self._set_pady = {w: w.grid_info().get("pady", "0") for w in f.grid_slaves()}

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
