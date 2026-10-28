# -*- coding: utf-8 -*-
"""Google 关键词采集 —— 图形界面

功能：
  · 代理：主机默认 127.0.0.1，端口可填（本地代理软件的 HTTP/混合端口）
  · 关键词：从 txt 导入，按行读取（自动识别 UTF-8 / GBK 编码）
  · 参数：搜索页数（默认 10）、每页条数（默认 10）、最多访问网页数
  · 采集结果实时上表（关键词 / 网站名称 / 邮箱 / 电话 / 链接）
  · 日志可折叠

与 keyword_get_email.py 的关系：
  本文件只做界面与调度，所有采集逻辑仍在 keyword_get_email.py 里，
  通过 set_runtime_hooks() 接收进度与实时记录、通过 stop_requested() 响应停止。
"""
import logging
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

# 打包成 exe 后（windowed，没有控制台）sys.stdout / sys.stderr 是 None，
# logging 的 StreamHandler 一旦写日志就会往 None 上写而报错。这里补一个
# 丢弃式的占位流，避免采集过程中因为打日志把程序搞崩。
if sys.stdout is None or sys.stderr is None:
    class _NullStream(object):
        def write(self, *_a, **_k):
            return 0

        def flush(self):
            pass

        def isatty(self):
            return False

        encoding = 'utf-8'

    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()

import keyword_get_email as K          # noqa: E402

# 可写目录（exe 同级）与资源目录（打包后在 _MEIPASS）由核心模块统一给出
BASE_DIR = K.BASE_DIR
RES_DIR = K.RES_DIR

# ==================== 配色（浅色） ====================
BG = '#f2f5fa'          # 窗口底色
CARD = '#ffffff'        # 卡片
FIELD = '#f7f9fc'       # 输入框
BORDER = '#e1e7f0'
FG = '#1e2532'          # 主文字
MUTED = '#6b7686'       # 次要文字
ACCENT = '#2563eb'      # 强调色
ACCENT_HOVER = '#1d4ed8'
ACCENT_SOFT = '#e8effd'
OK = '#15803d'
WARN = '#b45309'
ERR = '#dc2626'
HEAD_BG = '#eef3fb'     # 表头

FONT_UI = ('Microsoft YaHei UI', 9)
FONT_BOLD = ('Microsoft YaHei UI', 9, 'bold')
FONT_TITLE = ('Microsoft YaHei UI', 15, 'bold')
FONT_BIG = ('Microsoft YaHei UI', 21, 'bold')
FONT_SMALL = ('Microsoft YaHei UI', 8)
FONT_MONO = ('Consolas', 9)

TXT_ENCODINGS = ('utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'utf-16')

# 结果表列定义：(列 id, 标题, 宽度, 对齐)
COLUMNS = (
    ('idx', '#', 46, 'center'),
    ('keyword', '关键词', 110, 'w'),
    ('name', '网站名称', 140, 'w'),
    ('url', '网站链接', 230, 'w'),
    ('email', '邮箱', 190, 'w'),
    ('phone', '电话', 130, 'w'),
    ('stage', '状态', 92, 'center'),
)


def read_keywords(path):
    """按行读取关键词文件，返回 (关键词列表, 实际使用的编码)。

    国内 txt 常见 GBK，utf-8 读会抛 UnicodeDecodeError，
    所以按顺序试几种编码；空行和 # 开头的注释行跳过，并保持原顺序去重。
    """
    last_err = None
    for enc in TXT_ENCODINGS:
        try:
            with open(path, 'r', encoding=enc) as f:
                raw = f.read()
            break
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
            continue
    else:
        raise ValueError('无法识别文件编码，请另存为 UTF-8 或 GBK：%s'
                         % last_err)

    words, seen = [], set()
    for line in raw.splitlines():
        w = line.strip().lstrip('\ufeff')
        if not w or w.startswith('#'):
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(w)
    return words, enc


class SlimScrollbar(tk.Canvas):
    """细长、圆角、无箭头的滚动条（替代 ttk.Scrollbar）。

    ttk 的滚动条在 clam 主题下带两个箭头按钮 + 3D 边框，跟这套浅色界面不搭，
    而且没法做圆角。这里用 Canvas 自绘：
      · 9px 细条，胶囊形滑块
      · 内容不需要滚动时整条不画（保留 9px 空槽，避免布局跳动）
      · 悬停 / 拖动时颜色加深
      · 支持拖滑块、点空白翻页、在滚动条上滚滚轮

    用法与 ttk.Scrollbar 基本一致：
        sb = SlimScrollbar(frame, orient='vertical',
                           command=tree.yview, target=tree)
        tree.configure(yscrollcommand=sb.set)
    """

    THICK = 9          # 轨道粗细（px）
    PAD = 2            # 滑块与轨道的间隙
    MIN_LEN = 26       # 滑块最短长度，太短不好拖
    IDLE = '#ccd5e3'   # 静止颜色
    ACTIVE = '#93a1b6'  # 悬停 / 拖动颜色

    def __init__(self, master, orient='vertical', thickness=None,
                 command=None, target=None, bg=None, **kw):
        self.vertical = (orient == 'vertical')
        self._thick = thickness or self.THICK
        self._command = command
        self._target = target
        self._first, self._last = 0.0, 1.0
        self._thumb = None
        self._drag_delta = None
        self._hover = False

        box = bg or CARD
        if self.vertical:
            super().__init__(master, width=self._thick, bg=box,
                             highlightthickness=0, borderwidth=0, **kw)
        else:
            super().__init__(master, height=self._thick, bg=box,
                             highlightthickness=0, borderwidth=0, **kw)

        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_press)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_release)
        self.bind('<MouseWheel>', self._on_wheel)

    # ---------- 目标控件回调 ----------
    def set(self, first, last):
        """被 yscrollcommand / xscrollcommand 调用，参数是 0~1 的可见范围。"""
        try:
            self._first = max(0.0, min(1.0, float(first)))
            self._last = max(0.0, min(1.0, float(last)))
        except (TypeError, ValueError):
            return
        self._draw()

    # ---------- 绘制 ----------
    def _draw(self):
        self.delete('all')
        self._thumb = None
        # 全部内容都在可视区内 -> 不需要滚动条，直接不画
        if self._first <= 0.0 and self._last >= 1.0:
            return

        total = (self.winfo_height() if self.vertical
                 else self.winfo_width())
        if total <= 2:
            return                    # 还没完成布局，等下一次 Configure

        span = max(0.0, self._last - self._first)
        length = max(self.MIN_LEN, span * total)
        length = min(length, total - 2 * self.PAD)
        start = self._first * total
        start = max(0.0, min(start, total - length - self.PAD))
        end = start + length
        self._thumb = (start, end)

        color = (self.ACTIVE if (self._hover or self._drag_delta is not None)
                 else self.IDLE)
        if self.vertical:
            self._capsule(self.PAD, start, self._thick - self.PAD, end, color)
        else:
            self._capsule(start, self.PAD, end, self._thick - self.PAD, color)

    def _capsule(self, x0, y0, x1, y1, color):
        """画胶囊形：两端半圆 + 中间矩形。

        Canvas 没有圆角矩形，直接 create_polygon(smooth=True) 边缘会发虚，
        用两个正圆加一个矩形拼出来更干净。
        """
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        d = min(w, h)
        self.create_oval(x0, y0, x0 + d, y0 + d, fill=color, outline='')
        self.create_oval(x1 - d, y1 - d, x1, y1, fill=color, outline='')
        if h > w:
            self.create_rectangle(x0, y0 + d / 2.0, x1, y1 - d / 2.0,
                                  fill=color, outline='')
        else:
            self.create_rectangle(x0 + d / 2.0, y0, x1 - d / 2.0, y1,
                                  fill=color, outline='')

    # ---------- 交互 ----------
    def _on_enter(self, _e=None):
        self._hover = True
        self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._draw()

    def _pos(self, event):
        return event.y if self.vertical else event.x

    def _on_press(self, event):
        if self._thumb is None:
            return
        pos = self._pos(event)
        start, end = self._thumb
        if start <= pos <= end:
            self._drag_delta = pos - start      # 按在滑块上：准备拖动
        else:
            # 按在空白处：向前/向后翻一屏
            page = max(0.05, self._last - self._first)
            self._moveto(self._first + (-page if pos < start else page))
        self._draw()

    def _on_drag(self, event):
        if self._drag_delta is None:
            return
        total = (self.winfo_height() if self.vertical
                 else self.winfo_width())
        if total <= 2:
            return
        self._moveto((self._pos(event) - self._drag_delta) / float(total))

    def _on_release(self, _e=None):
        self._drag_delta = None
        self._draw()

    def _moveto(self, frac):
        if self._command is None:
            return
        top = max(0.0, min(1.0 - max(0.0, self._last - self._first), frac))
        self._command('moveto', top)

    def _on_wheel(self, event):
        if self._target is None:
            return
        step = -3 if event.delta > 0 else 3
        if self.vertical:
            self._target.yview_scroll(step, 'units')
        else:
            self._target.xview_scroll(step, 'units')


class TreeTooltip:
    """鼠标悬浮在结果表单元格上时，显示被列宽截断的完整内容。

    触发条件：该列文字实际像素宽度超过列宽（留出内边距），
    也就是「显示不全」才弹，放得下就不打扰。
    """

    def __init__(self, tree, delay=350, wraplength=560):
        self.tree = tree
        self.delay = delay
        self.wraplength = wraplength
        self._win = None
        self._after = None
        self._key = None

        tree.bind('<Motion>', self._on_motion, add='+')
        tree.bind('<Leave>', self._hide, add='+')
        tree.bind('<ButtonPress-1>', self._hide, add='+')
        tree.bind('<Button-4>', self._hide, add='+')      # Linux 滚轮
        tree.bind('<Button-5>', self._hide, add='+')
        tree.bind('<MouseWheel>', self._hide, add='+')
        tree.bind('<B1-Motion>', self._hide, add='+')

    # ---------- 事件 ----------
    def _on_motion(self, event):
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row or not col:
            self._hide()
            return
        key = (row, col)
        if key == self._key:
            return                     # 还在同一格里，别反复弹
        self._hide()
        self._key = key

        text = self._cell_text(row, col)
        if not text or not self._is_clipped(col, text):
            return
        self._after = self.tree.after(
            self.delay,
            lambda: self._show(event.x_root, event.y_root, text))

    def _hide(self, _event=None):
        if self._after is not None:
            try:
                self.tree.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None
        self._key = None

    # ---------- 取内容 / 判断是否截断 ----------
    def _col_id(self, col):
        try:
            idx = int(str(col).replace('#', '')) - 1
            cols = list(self.tree['columns'])
            if 0 <= idx < len(cols):
                return cols[idx]
        except (tk.TclError, ValueError):
            pass
        return ''

    def _cell_text(self, row, col):
        cid = self._col_id(col)
        if not cid:
            return ''
        try:
            return str(self.tree.set(row, cid) or '').strip()
        except tk.TclError:
            return ''

    def _font(self):
        try:
            spec = self.tree.cget('font')
            if spec:
                return tkfont.Font(font=spec)
        except tk.TclError:
            pass
        return tkfont.nametofont('TkDefaultFont')

    def _is_clipped(self, col, text):
        cid = self._col_id(col)
        if not cid:
            return False
        try:
            width = int(self.tree.column(cid, 'width'))
        except (tk.TclError, ValueError):
            return False
        need = self._font().measure(text)
        return need > max(24, width - 14)

    # ---------- 显示 ----------
    def _show(self, x, y, text):
        self._after = None
        if self._win is not None:
            return
        win = tk.Toplevel(self.tree)
        win.wm_overrideredirect(True)      # 无标题栏
        # 必须自己也置顶：否则主窗口一旦是 topmost（或刚被激活），
        # 这个普通 Toplevel 会被压在下面，提示根本看不见。
        try:
            win.attributes('-topmost', True)
        except tk.TclError:
            pass
        win.configure(bg=BORDER)
        tk.Label(win, text=text, bg='#fffdf2', fg=FG, font=FONT_UI,
                 justify='left', anchor='w', wraplength=self.wraplength,
                 padx=9, pady=6).pack(padx=1, pady=1)
        win.update_idletasks()

        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        # 贴着鼠标右下角，贴边时自动翻到另一侧，避免跑出屏幕
        px = min(int(x) + 14, sw - w - 8)
        py = int(y) + 20
        if py + h > sh - 48:
            py = int(y) - h - 24
        win.wm_geometry('+%d+%d' % (max(0, px), max(0, py)))
        self._win = win


class LogQueueHandler(logging.Handler):
    """把 logging 记录塞进队列，由主线程取出来显示（tkinter 不能跨线程操作）。"""

    def __init__(self, q):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        try:
            self.q.put(('log', record.levelname, self.format(record)))
        except Exception:              # noqa: BLE001  日志失败不能影响采集
            pass


class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self._init_icon()
        self.title('Google 关键词采集 · 电话 / 邮箱')
        self.configure(bg=BG)

        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.start_time = 0.0
        self.keywords = []
        self.log_open = True
        self.row_seq = 0
        # url -> 表格行 id：链接先占位，采到结果后原地更新这一行
        self.row_by_url = {}
        # 结果文件固定在「exe 所在目录」（打包后也不会写进临时目录），
        # 界面上不再让用户选路径。文件不存在时会在采集开始时自动新建。
        self.out_path = os.path.join(BASE_DIR, K.OUT_NAME)
        self.stat = {'kw_index': 0, 'kw_total': 0, 'links': 0,
                     'saved': 0, 'rows': 0}

        self._init_style()
        self._build()
        self._center()          # 必须在 _build 之后：要按内容实际高度定窗口
        self._attach_logger()

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self._poll_id = self.after(120, self._poll)

        self._emit('MUTED', '就绪。请先导入关键词 txt，确认代理端口后点「开始采集」。')

    # ---------------- 外观 ----------------
    def _init_icon(self):
        """设置窗口 / 任务栏图标。

        用 pythonw.exe（或打包后的 exe）运行时，任务栏默认显示解释器的图标，
        因为图标取自宿主进程。这里给窗口显式指定图标，再配合 main() 里的
        AppUserModelID，任务栏就会显示本程序的图标。

        资源从 RES_DIR 取：打包后 app.ico 被解包在 _MEIPASS 里，
        而不是 exe 所在目录。
        """
        ico = os.path.join(RES_DIR, 'app.ico')
        if not os.path.isfile(ico):
            return
        # 必须分两步：带 default= 的调用只登记「后续 toplevel 的默认图标」，
        # 不会作用到当前这个窗口（wm_iconbitmap 查询会返回空串）。
        try:
            self.iconbitmap(ico)             # 当前窗口（标题栏 + 任务栏）
        except tk.TclError:
            pass
        try:
            self.iconbitmap(default=ico)     # 之后弹出的对话框也用它
        except tk.TclError:
            pass
        # 高 DPI 下 iconbitmap 有时显示模糊，再用 iconphoto 补一张大图。
        # 打包时裁剪掉了 Pillow，这里失败就跳过，不影响功能。
        try:
            from PIL import Image, ImageTk
            png = os.path.join(RES_DIR, 'app.png')
            src = png if os.path.isfile(png) else ico
            self._icon_img = ImageTk.PhotoImage(Image.open(src))
            self.iconphoto(True, self._icon_img)
        except Exception:                    # noqa: BLE001
            pass

    def _center(self):
        """按内容需要的尺寸定窗口大小，保证底部按钮不会被裁掉。"""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(max(1320, self.winfo_reqwidth() + 8), sw - 40)
        h = min(max(760, self.winfo_reqheight() + 8), sh - 80)
        self.geometry('%dx%d+%d+%d' % (w, h, max(0, (sw - w) // 2),
                                       max(0, (sh - h) // 3)))
        self.minsize(min(w, 1180), min(h, 700))

    def _init_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use('clam')
        except tk.TclError:
            pass

        st.configure('TFrame', background=BG)
        st.configure('TLabel', background=CARD, foreground=FG, font=FONT_UI)
        st.configure('Card.TLabel', background=CARD, foreground=FG,
                     font=FONT_UI)
        st.configure('Hint.TLabel', background=CARD, foreground=MUTED,
                     font=FONT_SMALL)
        st.configure('CardTitle.TLabel', background=CARD, foreground=FG,
                     font=FONT_BOLD)
        st.configure('Bg.TLabel', background=BG, foreground=FG, font=FONT_UI)
        st.configure('Title.TLabel', background=BG, foreground=FG,
                     font=FONT_TITLE)
        st.configure('Sub.TLabel', background=BG, foreground=MUTED,
                     font=FONT_UI)
        st.configure('Big.TLabel', background=CARD, foreground=ACCENT,
                     font=FONT_BIG)
        st.configure('Stat.TLabel', background=CARD, foreground=MUTED,
                     font=FONT_SMALL)

        st.configure('TCheckbutton', background=CARD, foreground=FG,
                     font=FONT_UI, focuscolor=CARD)
        st.map('TCheckbutton', background=[('active', CARD)],
               foreground=[('disabled', MUTED)])

        st.configure('TEntry', fieldbackground=FIELD, background=FIELD,
                     foreground=FG, insertcolor=FG, bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER, padding=6)
        st.map('TEntry', fieldbackground=[('disabled', '#f0f2f6')],
               foreground=[('disabled', MUTED)])

        st.configure('TSpinbox', fieldbackground=FIELD, background=FIELD,
                     foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER, padding=5)
        st.map('TSpinbox', fieldbackground=[('disabled', '#f0f2f6')],
               foreground=[('disabled', MUTED)])

        st.configure('TButton', background='#eef2f9', foreground=FG,
                     borderwidth=0, focusthickness=0, padding=(12, 7),
                     font=FONT_UI)
        st.map('TButton',
               background=[('active', '#e2e8f4'), ('disabled', '#f2f4f8')],
               foreground=[('disabled', '#b3bac6')])

        # 去掉「点击按钮后出现一圈虚线」
        # clam 主题的 TButton 布局里有个 Button.focus 元素，专门负责画
        # 虚线焦点环；focusthickness=0 在 clam 下并不生效，必须把这个
        # 元素从布局里摘掉。其它按钮样式（Accent/Stop/Outline）都继承
        # TButton 的布局，所以改这一处就全生效。
        try:
            st.layout('TButton', [
                ('Button.border', {
                    'sticky': 'nswe', 'border': '1', 'children': [
                        ('Button.padding', {
                            'sticky': 'nswe', 'children': [
                                ('Button.label', {'sticky': 'nswe'})]})]})
            ])
        except tk.TclError:
            pass

        st.configure('Ghost.TButton', background=CARD, foreground=ACCENT,
                     borderwidth=0, focusthickness=0, padding=(8, 5),
                     font=FONT_BOLD)
        st.map('Ghost.TButton',
               background=[('active', ACCENT_SOFT), ('disabled', CARD)],
               foreground=[('disabled', '#b3bac6')])

        st.configure('Accent.TButton', background=ACCENT, foreground='#ffffff',
                     borderwidth=0, focusthickness=0, padding=(16, 9),
                     font=FONT_BOLD)
        st.map('Accent.TButton',
               background=[('active', ACCENT_HOVER), ('disabled', '#c3d3f5')],
               foreground=[('disabled', '#ffffff')])

        st.configure('Stop.TButton', background='#fdeaea', foreground=ERR,
                     borderwidth=0, padding=(16, 9), font=FONT_BOLD)
        st.map('Stop.TButton',
               background=[('active', '#fbdcdc'), ('disabled', '#f4f5f7')],
               foreground=[('disabled', '#c9ced6')])

        st.configure('Horizontal.TProgressbar', troughcolor='#e8edf5',
                     background=ACCENT, bordercolor='#e8edf5',
                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=12)

        # 结果表
        st.configure('Treeview', background=CARD, fieldbackground=CARD,
                     foreground=FG, rowheight=25, borderwidth=0,
                     font=FONT_UI)
        st.map('Treeview',
               background=[('selected', ACCENT_SOFT)],
               foreground=[('selected', FG)])
        st.configure('Treeview.Heading', background=HEAD_BG, foreground=MUTED,
                     font=FONT_BOLD, relief='flat', borderwidth=0,
                     padding=(6, 6))
        st.map('Treeview.Heading', background=[('active', '#e3eaf7')])

    def _card(self, parent, title=None, grid=None, pady=(0, 11)):
        """带 1px 描边 + 白色底的卡片，返回内部容器。

        grid 不为空时用 grid 摆放（行高由调用方控制），否则 pack。
        """
        outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1)
        if grid is not None:
            outer.grid(pady=pady, **grid)
        else:
            outer.pack(fill='x', pady=pady)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill='both', expand=True, padx=14, pady=11)
        if title:
            head = tk.Frame(inner, bg=CARD)
            head.pack(fill='x', pady=(0, 9))
            tk.Frame(head, bg=ACCENT, width=3, height=13).pack(side='left')
            ttk.Label(head, text='  ' + title,
                      style='CardTitle.TLabel').pack(side='left')
        return inner

    def _build(self):
        root = tk.Frame(self, bg=BG)
        root.pack(fill='both', expand=True, padx=16, pady=(12, 8))

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, minsize=370, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky='nsew')
        # 左右两栏都用 grid 排版：让「可变高度」的那块吃掉多余空间
        #   左侧：关键词卡片（列表可以一直往下铺）
        #   右侧：结果表（日志始终留在视口内）
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_proxy(left)
        self._build_params(left)
        self._build_keywords(left)
        self._build_actions(left)

        self._build_progress(right)
        self._build_results(right)
        self._build_log(right)

        self._build_footer()

    # ---------------- 左侧：代理 ----------------
    def _build_proxy(self, parent):
        box = self._card(parent, '代理设置',
                         grid={'row': 0, 'column': 0, 'sticky': 'ew'})

        row = tk.Frame(box, bg=CARD)
        row.pack(fill='x')

        ttk.Label(row, text='主机', style='Card.TLabel').pack(side='left')
        # 必须自己持有 StringVar 的引用：匿名 StringVar 会被 GC 回收，
        # 输入框就会变成空的（很隐蔽的 tkinter 坑）。
        self.var_ip = tk.StringVar(value='127.0.0.1')
        self.ent_ip = ttk.Entry(row, textvariable=self.var_ip, width=15)
        self.ent_ip.pack(side='left', padx=(6, 0))

        tk.Frame(row, bg=CARD).pack(side='left', fill='x', expand=True)

        ttk.Label(row, text='端口', style='Card.TLabel').pack(side='left')
        self.var_port = tk.StringVar(value='7892')
        self.spn_port = ttk.Spinbox(row, from_=1, to=65535, width=8,
                                    textvariable=self.var_port)
        self.spn_port.pack(side='left', padx=(6, 0))

    # ---------------- 左侧：采集参数 ----------------
    def _build_params(self, parent):
        box = self._card(parent, '采集参数',
                         grid={'row': 1, 'column': 0, 'sticky': 'ew'})

        def line(label, factory):
            r = tk.Frame(box, bg=CARD)
            r.pack(fill='x', pady=3)
            ttk.Label(r, text=label, style='Card.TLabel',
                      width=10, anchor='w').pack(side='left')
            factory(r).pack(side='left', fill='x', expand=True)

        self.var_pages = tk.StringVar(value=str(K.MAX_SERP_PAGES))
        line('搜索页数',
             lambda p: ttk.Spinbox(p, from_=1, to=50,
                                   textvariable=self.var_pages))

        self.var_per_page = tk.StringVar(value=str(K.NUM_PER_PAGE))
        line('每页条数',
             lambda p: ttk.Spinbox(p, from_=1, to=50,
                                   textvariable=self.var_per_page))

        self.var_max_sites = tk.StringVar(value=str(K.MAX_SITES))
        line('最多访问',
             lambda p: ttk.Spinbox(p, from_=1, to=2000,
                                   textvariable=self.var_max_sites))

        # 采集方式：接口优先，接口失败时是否用浏览器兜底。
        # 关掉后全程只用 requests，不打开浏览器（更快，但 JS 站点可能采不到）。
        r = tk.Frame(box, bg=CARD)
        r.pack(fill='x', pady=(8, 0))
        ttk.Label(r, text='浏览器兜底', style='Card.TLabel',
                  width=10, anchor='w').pack(side='left')
        self._browser_fallback = True
        self._build_switch(r, '接口失败时用浏览器重试',
                           '_browser_fallback').pack(side='left')

    # ---------------- 左侧：关键词 ----------------
    def _build_keywords(self, parent):
        # 这一块吃掉左侧剩余高度：关键词多了可以一直往下铺
        box = self._card(parent, '关键词（txt 每行一个）',
                         grid={'row': 2, 'column': 0, 'sticky': 'nsew'})

        bar = tk.Frame(box, bg=CARD)
        bar.pack(fill='x', pady=(0, 8))
        self.btn_import = ttk.Button(bar, text='导入 txt',
                                     command=self._pick_txt)
        self.btn_import.pack(side='left')
        self.btn_remove = ttk.Button(bar, text='移除选中',
                                     command=self._remove_selected)
        self.btn_remove.pack(side='left', padx=6)
        self.btn_clear_kw = ttk.Button(bar, text='清空',
                                       command=self._clear_keywords)
        self.btn_clear_kw.pack(side='left')
        self.lbl_kw_count = ttk.Label(bar, text='共 0 个', style='Hint.TLabel')
        self.lbl_kw_count.pack(side='right')

        wrap = tk.Frame(box, bg=FIELD, highlightbackground=BORDER,
                        highlightthickness=1)
        wrap.pack(fill='both', expand=True)
        self.lb_keys = tk.Listbox(
            wrap, bg=FIELD, fg=FG, font=FONT_UI, height=6,
            selectbackground=ACCENT_SOFT, selectforeground=FG,
            highlightthickness=0, borderwidth=0, activestyle='none')
        sb = SlimScrollbar(wrap, orient='vertical', bg=FIELD,
                           command=self.lb_keys.yview,
                           target=self.lb_keys)
        self.lb_keys.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y', padx=(0, 3), pady=4)
        self.lb_keys.pack(side='left', fill='both', expand=True, padx=(8, 2),
                          pady=6)

    # ---------------- 左侧：操作按钮 ----------------
    def _build_actions(self, parent):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=3, column=0, sticky='ew')

        self.btn_start = ttk.Button(box, text='▶  开始采集',
                                    style='Accent.TButton',
                                    command=self._start)
        self.btn_start.pack(side='left', fill='x', expand=True)

        self.btn_stop = ttk.Button(box, text='■  停止', style='Stop.TButton',
                                   command=self._stop, state='disabled')
        self.btn_stop.pack(side='left', padx=(10, 0))

    # ---------------- 右侧：进度 ----------------
    def _build_progress(self, parent):
        box = self._card(parent, '采集进度',
                         grid={'row': 0, 'column': 0, 'sticky': 'ew'})

        top = tk.Frame(box, bg=CARD)
        top.pack(fill='x')

        self.lbl_percent = ttk.Label(top, text='0%', style='Big.TLabel')
        self.lbl_percent.pack(side='left')

        info = tk.Frame(top, bg=CARD)
        info.pack(side='left', padx=(12, 0), fill='x', expand=True)
        self.lbl_stage = ttk.Label(info, text='等待开始', style='Card.TLabel')
        self.lbl_stage.pack(anchor='w')
        self.lbl_stats = ttk.Label(
            info, text='关键词 0/0 · 链接 0 · 已保存 0', style='Stat.TLabel')
        self.lbl_stats.pack(anchor='w', pady=(2, 0))

        self.pb = ttk.Progressbar(box, mode='determinate', maximum=100)
        self.pb.pack(fill='x', pady=(9, 0))

        self.lbl_kw = ttk.Label(box, text='', style='Hint.TLabel')
        self.lbl_kw.pack(anchor='w', pady=(7, 0))

    # ---------------- 右侧：实时结果表 ----------------
    def _build_results(self, parent):
        outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1)
        outer.grid(row=1, column=0, sticky='nsew')
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill='both', expand=True, padx=14, pady=11)

        head = tk.Frame(inner, bg=CARD)
        head.pack(fill='x', pady=(0, 8))
        tk.Frame(head, bg=ACCENT, width=3, height=13).pack(side='left')
        ttk.Label(head, text='  采集结果', style='CardTitle.TLabel').pack(
            side='left')
        self.lbl_rows = ttk.Label(head, text='实时显示，共 0 条',
                                  style='Stat.TLabel')
        self.lbl_rows.pack(side='left', padx=(10, 0))

        ttk.Button(head, text='清空', command=self._clear_rows).pack(
            side='right')
        ttk.Button(head, text='复制本页', command=self._copy_rows).pack(
            side='right', padx=6)

        wrap = tk.Frame(inner, bg=CARD)
        wrap.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLUMNS],
                                 show='headings', selectmode='extended')
        for cid, ctitle, cwidth, anchor in COLUMNS:
            self.tree.heading(cid, text=ctitle, anchor=anchor)
            # 「网站链接」不参与拉伸：一拉伸就被压缩截断成
            # https://xxx.com/very/lor 这种，反而看不到完整地址。
            # 其余列最少保留 80% 的设计宽度，窗口窄时宁可出横向滚动条，
            # 也不要把列挤到文字放不下。
            stretch = cid in ('name', 'email')
            minw = max(40, int(cwidth * 0.8))
            self.tree.column(cid, width=cwidth, minwidth=minw, anchor=anchor,
                             stretch=stretch)
        self.tree.tag_configure('odd', background='#fbfcfe')
        self.tree.tag_configure('even', background=CARD)
        self.tree.tag_configure('empty', foreground=MUTED)
        self.tree.tag_configure('pending', foreground=MUTED)
        self.tree.tag_configure('failed', foreground=ERR)

        vsb = SlimScrollbar(wrap, orient='vertical', bg=CARD,
                            command=self.tree.yview, target=self.tree)
        hsb = SlimScrollbar(wrap, orient='horizontal', bg=CARD,
                            command=self.tree.xview, target=self.tree)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y', padx=(2, 0), pady=1)
        hsb.pack(side='bottom', fill='x', pady=(2, 0), padx=1)
        self.tree.pack(side='left', fill='both', expand=True)

        # 双击一行 → 用系统浏览器打开该网站
        self.tree.bind('<Double-1>', self._open_row_url)
        # 单元格被列宽截断时，鼠标悬浮显示完整内容
        self.tooltip = TreeTooltip(self.tree)

    def _clear_rows(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.row_seq = 0
        # (关键词, url) -> treeview item id
        # 用关键词一起做键：同一个网站出现在两个关键词下时不能互相覆盖
        self.row_by_url = {}
        self.stat['rows'] = 0
        self._update_rows_label()

    @staticmethod
    def _row_key(rec):
        return ((rec.get('keyword') or ''), (rec.get('url') or ''))

    def _update_rows_label(self):
        n = len(self.tree.get_children())
        self.lbl_rows.configure(text='实时显示，共 %d 条' % n)

    # 状态列的文字与颜色
    STAGE_TEXT = {
        'pending': '待采集',
        'http': '接口',
        'browser': '浏览器',
        'skip': '已存在',
        'fail': '未取到',
    }

    def _cells(self, rec):
        """按列 id 组装一行，不依赖 COLUMNS 的书写顺序。"""
        emails = rec.get('emails') or []
        phones = rec.get('phones') or []
        name = rec.get('site_name') or rec.get('title') or ''
        source = rec.get('source') or 'pending'
        stage = self.STAGE_TEXT.get(source, source)
        if source == 'http' and rec.get('written'):
            stage = '接口 ✓'
        elif source == 'browser' and rec.get('written'):
            stage = '浏览器 ✓'
        return {
            'idx': rec.get('_seq', ''),
            'keyword': rec.get('keyword', ''),
            'name': name[:40],
            'url': rec.get('url', ''),
            'email': '; '.join(emails)[:120] or '—',
            'phone': '; '.join(phones)[:80] or '—',
            'stage': stage,
        }

    def _tags_for(self, rec, seq):
        emails = rec.get('emails') or []
        phones = rec.get('phones') or []
        source = rec.get('source') or 'pending'
        base = 'odd' if seq % 2 else 'even'
        if source == 'pending':
            return (base, 'pending')
        if source in ('fail', 'skip'):
            return (base, 'empty', 'pending')
        if not emails and not phones:
            return (base, 'empty')
        return (base,)

    def _add_row(self, rec):
        """把一条采集结果插到表格里（主线程调用）。"""
        self.row_seq += 1
        seq = self.row_seq
        rec = dict(rec)
        rec['_seq'] = seq
        iid = self.tree.insert(
            '', 'end', tags=self._tags_for(rec, seq),
            values=tuple(self._cells(rec).get(c[0], '') for c in COLUMNS))
        url = rec.get('url') or ''
        if url:
            self.row_by_url[self._row_key(rec)] = iid
        self.stat['rows'] = seq
        self._update_rows_label()
        kids = self.tree.get_children()
        if kids:
            self.tree.see(kids[-1])
        return iid

    def _on_link(self, rec):
        """搜到一条结果链接：先占一行，状态「待采集」。

        这样用户能立刻看到搜到了什么，而不是等所有网站跑完才看到结果。
        """
        url = rec.get('url') or ''
        if not url:
            return
        if self._row_key(rec) in self.row_by_url:
            return                       # 已经占过位
        self._add_row({
            'keyword': rec.get('keyword', ''),
            'url': url,
            'title': rec.get('title', ''),
            'site_name': rec.get('site_name', ''),
            'emails': [],
            'phones': [],
            'source': 'pending',
        })

    def _on_record(self, rec):
        """采到一条结果：有占位行就原地更新，否则新增一行。

        原地更新很重要 —— 否则「待采集」和「接口」会变成两条，表格翻倍。
        """
        url = rec.get('url') or ''
        iid = self.row_by_url.get(self._row_key(rec)) if url else None
        if iid and self.tree.exists(iid):
            old = self.tree.item(iid, 'values')
            seq = 0
            try:
                seq = int(old[0]) if old else 0
            except (ValueError, IndexError, TypeError):
                seq = 0
            if not seq:
                self.row_seq += 1
                seq = self.row_seq
            rec = dict(rec)
            rec['_seq'] = seq
            self.tree.item(
                iid, tags=self._tags_for(dict(rec, source=rec.get('source')),
                                         seq),
                values=tuple(self._cells(rec).get(c[0], '')
                             for c in COLUMNS))
            self._update_rows_label()
            return

        self._add_row(rec)

    def _copy_rows(self):
        """把表格内容复制到剪贴板（Tab 分隔，粘到 Excel 就是一张表）"""
        lines = ['\t'.join(c[1] for c in COLUMNS)]
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, 'values')
            lines.append('\t'.join(str(v) for v in vals))
        self.clipboard_clear()
        self.clipboard_append('\n'.join(lines))
        self._emit('SUCCESS', '已复制 %d 行到剪贴板'
                   % (len(lines) - 1))

    def _open_row_url(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], 'values')
        # 用列 id 定位「网站链接」，不要写死下标：列顺序是可以调整的
        url = ''
        for i, col in enumerate(COLUMNS):
            if col[0] == 'url' and i < len(vals):
                url = vals[i]
                break
        if url.startswith('http'):
            try:
                os.startfile(url)          # noqa: S606  Windows 专用
            except OSError as e:
                self._emit('ERROR', '打开链接失败：%s' % e)

    # ---------------- 右侧：可折叠日志 ----------------
    def _build_log(self, parent):
        self.log_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                                 highlightthickness=1)
        self.log_card.grid(row=2, column=0, sticky='ew', pady=(11, 0))

        inner = tk.Frame(self.log_card, bg=CARD)
        inner.pack(fill='both', expand=True, padx=14, pady=(9, 10))

        head = tk.Frame(inner, bg=CARD)
        head.pack(fill='x')

        # 标题本身就是折叠开关
        self.btn_log_toggle = ttk.Button(
            head, text='▾  运行日志', style='Ghost.TButton',
            command=self._toggle_log)
        self.btn_log_toggle.pack(side='left')

        ttk.Button(head, text='清空', command=self._clear_log).pack(
            side='right')

        # 自动滚动开关：ttk 的 Checkbutton 在 clam 下就是一个带叉的小方块，
        # 很丑也不好点，这里用 Canvas 自绘一个滑动开关。
        self._autoscroll = True
        self._build_switch(head, '自动滚动', '_autoscroll',
                           self._toggle_autoscroll).pack(side='right',
                                                         padx=(0, 10))

        self.log_body = tk.Frame(inner, bg=CARD)
        self.log_body.pack(fill='both', expand=True, pady=(8, 0))

        wrap = tk.Frame(self.log_body, bg='#fbfcfe',
                        highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill='both', expand=True)
        self.log = tk.Text(
            wrap, bg='#fbfcfe', fg=FG, font=FONT_MONO,
            # 用 char 而不是 word：日志里全是长路径、URL 这类没有空格的串，
            # word 换行会把它们横向截断看不全。
            wrap='char', height=8,
            borderwidth=0, highlightthickness=0, padx=9, pady=7,
            spacing1=1, spacing3=2,
            insertbackground=FG, state='disabled')
        sb = SlimScrollbar(wrap, orient='vertical', bg='#fbfcfe',
                           command=self.log.yview, target=self.log)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y', padx=(0, 3), pady=5)
        self.log.pack(side='left', fill='both', expand=True)

        self.log.tag_config('INFO', foreground=FG)
        self.log.tag_config('MUTED', foreground=MUTED)
        self.log.tag_config('WARNING', foreground=WARN)
        self.log.tag_config('ERROR', foreground=ERR)
        self.log.tag_config('SUCCESS', foreground=OK)
        self.log.tag_config('ACCENT', foreground=ACCENT)
        self.log.tag_config('DIVIDER', foreground='#c3cbd8')

    def _build_switch(self, parent, text='', attr='_autoscroll',
                      on_change=None):
        """自绘滑动开关（Canvas），返回可 pack 的容器。

        ttk.Checkbutton 在 clam 主题下就是个带叉的小方块，和整体风格不搭；
        这里画一个 iOS 风格的滑块，点击任意位置都能切换。
        状态存在 self.<attr> 上，切换后调用 on_change()。
        """
        bar = tk.Frame(parent, bg=CARD)
        if text:
            tk.Label(bar, text=text, bg=CARD, fg=MUTED,
                     font=FONT_SMALL).pack(side='left', padx=(0, 6))

        W, H, PAD = 34, 18, 2
        cv = tk.Canvas(bar, width=W, height=H, bg=CARD,
                       highlightthickness=0, borderwidth=0, cursor='hand2')
        cv.pack(side='left')

        # 轨道：用两个半圆 + 中间矩形拼出胶囊形
        track_off, track_on = '#cfd6e2', ACCENT

        def draw():
            cv.delete('all')
            on = bool(getattr(self, attr))
            color = track_on if on else track_off
            r = H / 2.0
            cv.create_oval(0, 0, H, H, fill=color, outline=color)
            cv.create_oval(W - H, 0, W, H, fill=color, outline=color)
            cv.create_rectangle(r, 0, W - r, H, fill=color, outline=color)
            # 滑块
            d = H - PAD * 2
            x = (W - H + PAD) if on else PAD
            cv.create_oval(x, PAD, x + d, PAD + d,
                           fill='#ffffff', outline='')

        def toggle(_event=None):
            setattr(self, attr, not bool(getattr(self, attr)))
            draw()
            if on_change:
                on_change()

        cv.bind('<Button-1>', toggle)
        draw()                         # 先按初始状态画一次
        cv.draw = draw                 # 便于测试或主题切换时手动重绘
        if attr == '_autoscroll':
            self.switch = cv           # 兼容：日志自动滚动开关
        setattr(self, attr + '_switch', cv)
        return bar

    def _toggle_log(self):
        """折叠 / 展开日志：折叠后结果表自动占满剩余高度"""
        self.log_open = not self.log_open
        if self.log_open:
            self.log_body.pack(fill='both', expand=True, pady=(8, 0))
            self.btn_log_toggle.configure(text='▾  运行日志')
        else:
            self.log_body.pack_forget()
            self.btn_log_toggle.configure(text='▸  运行日志（已折叠）')

    def _build_footer(self):
        # 底部只保留耗时；状态信息已经在进度卡片里显示了
        foot = tk.Frame(self, bg=BG)
        foot.pack(fill='x', padx=16, pady=(0, 6))
        self.lbl_elapsed = ttk.Label(foot, text='', style='Sub.TLabel')
        self.lbl_elapsed.pack(side='right')

    # ---------------- 日志接入 ----------------
    def _attach_logger(self):
        """把 keyword_get_email 的 logger 挂到界面上（只挂一次）。"""
        base = logging.getLogger('main')
        base.setLevel(logging.DEBUG)
        for h in base.handlers:
            if isinstance(h, LogQueueHandler):
                return
        base.addHandler(LogQueueHandler(self.queue))

    def _emit(self, level, text):
        self.queue.put(('log', level, text))

    def _append_log(self, level, text):
        tag = level if level in ('INFO', 'WARNING', 'ERROR', 'SUCCESS',
                                 'ACCENT', 'MUTED', 'DIVIDER') else 'INFO'
        self.log.configure(state='normal')
        # 分割线不加时间戳，否则会被前缀撑到换行
        if tag == 'DIVIDER':
            self.log.insert('end', text + '\n', 'DIVIDER')
        else:
            self.log.insert('end', '[%s] ' % time.strftime('%H:%M:%S'), 'MUTED')
            self.log.insert('end', text + '\n', tag)
        self.log.configure(state='disabled')
        if self._autoscroll:
            self.log.see('end')

    def _toggle_autoscroll(self):
        """开关已由 Canvas 自己维护状态，这里只负责跟随滚动一次。"""
        if self._autoscroll:
            self.log.see('end')

    def _clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    # ---------------- 关键词操作 ----------------
    def _pick_txt(self):
        path = filedialog.askopenfilename(
            title='选择关键词文件（每行一个关键词）',
            initialdir=BASE_DIR,
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            words, enc = read_keywords(path)
        except (OSError, ValueError) as e:
            messagebox.showerror('读取失败', str(e))
            return
        if not words:
            messagebox.showwarning('没有关键词',
                                  '文件里没有有效内容（空行和 # 注释会被忽略）')
            return
        self._set_keywords(words)
        K.logger.info('已导入 %d 个关键词（编码 %s）：%s'
                      % (len(words), enc, path))

    def _set_keywords(self, words):
        self.keywords = list(words)
        self.lb_keys.delete(0, 'end')
        for w in self.keywords:
            self.lb_keys.insert('end', w)
        self.lbl_kw_count.configure(text='共 %d 个' % len(self.keywords))
        self._emit('SUCCESS', '关键词已载入：%d 个' % len(self.keywords))

    def _remove_selected(self):
        if self._running():
            return
        sel = list(self.lb_keys.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.lb_keys.delete(i)
        self.keywords = list(self.lb_keys.get(0, 'end'))
        self.lbl_kw_count.configure(text='共 %d 个' % len(self.keywords))

    def _clear_keywords(self):
        if self._running():
            return
        self._set_keywords([])

    # ---------------- 运行状态 ----------------
    def _running(self):
        return self.worker is not None and self.worker.is_alive()

    def _set_running(self, running):
        normal = 'disabled' if running else 'normal'
        for w in (self.btn_import, self.btn_remove, self.btn_clear_kw,
                  self.spn_port, self.ent_ip):
            try:
                w.configure(state=normal)
            except tk.TclError:
                pass
        self.btn_start.configure(state='disabled' if running else 'normal')
        self.btn_stop.configure(state='normal' if running else 'disabled')

    # ---------------- 开始 / 停止 ----------------
    def _read_config(self):
        if not self.keywords:
            messagebox.showwarning('缺少关键词', '请先导入关键词 txt 文件')
            return None

        def as_int(var, name, lo, hi):
            try:
                v = int(str(var.get()).strip())
            except ValueError:
                messagebox.showerror('参数错误', '%s 必须是整数' % name)
                return None
            if not lo <= v <= hi:
                messagebox.showerror('参数错误',
                                     '%s 需在 %d ~ %d 之间' % (name, lo, hi))
                return None
            return v

        pages = as_int(self.var_pages, '搜索页数', 1, 50)
        if pages is None:
            return None
        per_page = as_int(self.var_per_page, '每页条数', 1, 50)
        if per_page is None:
            return None
        max_sites = as_int(self.var_max_sites, '最多访问', 1, 2000)
        if max_sites is None:
            return None

        proxy = None
        port = self.var_port.get().strip()
        if port:
            ip = self.ent_ip.get().strip() or '127.0.0.1'
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                messagebox.showerror('代理端口错误',
                                     '端口需为 1 ~ 65535 的数字，留空表示直连')
                return None
            proxy = {'server': 'http://%s:%s' % (ip, port)}

        return {'proxy': proxy, 'pages': pages, 'per_page': per_page,
                'max_sites': max_sites, 'out': self.out_path,
                'browser_fallback': bool(self._browser_fallback)}

    def _start(self):
        if self._running():
            return
        cfg = self._read_config()
        if cfg is None:
            return

        self.stop_event = threading.Event()
        self.stat = {'kw_index': 0, 'kw_total': len(self.keywords),
                     'links': 0, 'saved': 0, 'rows': 0}
        self._clear_rows()
        self._update_stats()
        self.pb['value'] = 0
        self.lbl_percent.configure(text='0%')
        self.lbl_stage.configure(text='启动浏览器……')
        self.lbl_kw.configure(text='')
        self._set_running(True)
        self.start_time = time.time()

        self._emit('DIVIDER', '─' * 46)
        if cfg['proxy']:
            K.logger.info('代理：%s' % cfg['proxy']['server'])
        else:
            K.logger.info('代理：不使用（直连，Google 大概率会要求验证）')
        K.logger.info('关键词 %d 个 ｜ 页数 %d ｜ 每页 %d 条 ｜ 最多访问 %d 个网页'
                      % (len(self.keywords), cfg['pages'], cfg['per_page'],
                         cfg['max_sites']))
        K.logger.info('采集方式：接口优先（%d 线程）%s'
                      % (K.HTTP_MAX_WORKERS,
                         '，接口失败时用浏览器兜底'
                         if cfg['browser_fallback'] else '，仅接口（不打开浏览器）'))

        self.worker = threading.Thread(target=self._run,
                                       args=(list(self.keywords), cfg),
                                       daemon=True)
        self.worker.start()

    def _stop(self):
        if not self._running():
            return
        self.stop_event.set()
        self.btn_stop.configure(state='disabled')
        self.lbl_stage.configure(text='正在停止……')
        self._emit('WARNING',
                   '已请求停止：当前网页处理完就退出（验证等待也会立即中断）')

    def _run(self, keywords, cfg):
        """采集线程：不碰界面，只往队列里发消息。"""
        q = self.queue

        def progress(stage, cur, total, text):
            q.put(('progress', stage, cur, total, text))

        K.set_runtime_hooks(
            progress=progress, stop_event=self.stop_event,
            record=lambda rec: q.put(('record', rec)),
            link=lambda rec: q.put(('link', rec)))
        total_saved = 0
        try:
            for i, kw in enumerate(keywords, 1):
                if self.stop_event.is_set():
                    left = len(keywords) - i + 1
                    q.put(('log', 'WARNING',
                           '已停止，剩余 %d 个关键词未执行' % left))
                    break
                q.put(('kw', i, len(keywords), kw))
                q.put(('log', 'DIVIDER', '─' * 46))
                K.logger.info('开始采集关键词：%s（%d/%d）'
                              % (kw, i, len(keywords)))
                try:
                    saved = K.crawl(kw, proxy=cfg['proxy'],
                                    max_pages=cfg['pages'],
                                    max_sites=cfg['max_sites'],
                                    out_file=cfg['out'],
                                    per_page=cfg['per_page'],
                                    browser_fallback=cfg['browser_fallback'])
                    total_saved += saved
                except Exception as e:      # noqa: BLE001
                    # 单个关键词失败不能让整批停掉
                    q.put(('log', 'ERROR', '关键词「%s」采集失败：%s'
                           % (kw, str(e)[:200])))
                    saved = 0
                q.put(('kw_done', i, len(keywords), kw, total_saved))
                if (not self.stop_event.is_set()) and i < len(keywords):
                    time.sleep(random.uniform(*K.SERP_DELAY))
        except Exception as e:              # noqa: BLE001
            q.put(('log', 'ERROR', '采集线程异常：%s' % str(e)[:300]))
        finally:
            K.set_runtime_hooks(None, None, None, None)
            q.put(('log', 'MUTED', '正在关闭浏览器……'))
            K.reset_browser()
            q.put(('done', total_saved, self.stop_event.is_set(),
                    cfg['out']))

    # ---------------- 消息循环 ----------------
    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self._tick_elapsed()
        self._poll_id = self.after(120, self._poll)

    def _handle(self, msg):
        kind = msg[0]

        if kind == 'log':
            self._append_log(msg[1], msg[2])

        elif kind == 'link':
            self._on_link(msg[1])

        elif kind == 'record':
            self._on_record(msg[1])

        elif kind == 'kw':
            _, idx, total, kw = msg
            self.stat['kw_index'] = idx
            self.stat['kw_total'] = total
            self.lbl_kw.configure(text='当前关键词：%s' % kw)
            self._update_stats()
            self._paint(self._fraction(0))

        elif kind == 'progress':
            _, stage, cur, total, text = msg
            self.lbl_stage.configure(text=text or stage)
            if stage == 'links':
                self.stat['links'] = cur
                self._update_stats()
            self._paint(self._fraction(0, stage, cur, total))

        elif kind == 'kw_done':
            _, idx, total, kw, saved = msg
            self.stat['kw_index'] = idx
            self.stat['saved'] = saved
            self._update_stats()
            self._paint(self._fraction(0, 'keyword_done', 1, 1))

        elif kind == 'done':
            _, saved, stopped, out = msg
            self._set_running(False)
            self.lbl_stage.configure(text='已停止' if stopped else '全部完成')
            self._paint(1.0 if not stopped else self.pb['value'] / 100.0)
            self.lbl_kw.configure(text='')
            self._emit('DIVIDER', '─' * 46)
            if stopped:
                self._emit('WARNING', '已停止，本次新增 %d 条记录' % saved)
            else:
                self._emit('SUCCESS', '全部完成，本次新增 %d 条记录' % saved)
            self._emit('ACCENT', '结果文件：%s' % out)
            self.start_time = 0.0
            self.lbl_elapsed.configure(text='')

    def _fraction(self, base, stage=None, cur=0, total=0):
        """把「第几个关键词 + 关键词内部阶段」换算成 0~1 的总进度"""
        kw_total = max(1, self.stat['kw_total'])
        done = max(0, self.stat['kw_index'] - 1)
        part = 0.0
        if stage is not None:
            ratio = (cur / total) if total else 0.0
            ratio = max(0.0, min(1.0, ratio))
            if stage == 'search':
                part = 0.05 * ratio        # 搜索只占一小段
            elif stage == 'links':
                part = 0.08
            elif stage == 'sites':
                part = 0.10 + 0.88 * ratio
            elif stage == 'keyword_done':
                part = 1.0
        return max(0.0, min(1.0, (done + part) / kw_total))

    def _paint(self, frac):
        pct = int(round(frac * 100))
        self.pb['value'] = pct
        self.lbl_percent.configure(text='%d%%' % pct)

    def _update_stats(self):
        s = self.stat
        self.lbl_stats.configure(
            text='关键词 %d/%d · 链接 %d · 已保存 %d'
                 % (s['kw_index'], s['kw_total'], s['links'], s['saved']))

    def _tick_elapsed(self):
        if self.start_time and self._running():
            sec = int(time.time() - self.start_time)
            self.lbl_elapsed.configure(
                text='已用时 %02d:%02d:%02d'
                     % (sec // 3600, sec % 3600 // 60, sec % 60))

    # ---------------- 关闭 ----------------
    def _on_close(self):
        if self._running():
            if not messagebox.askyesno(
                    '正在采集', '采集尚未结束，确定要退出吗？\n'
                                '（正在处理的网页可能会丢失）'):
                return
            self.stop_event.set()
            self.worker.join(timeout=3)
        # 先停掉定时器：否则 destroy 之后回调还会触发，
        # 控制台会冒出 invalid command name "_poll" 的报错
        try:
            self.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError):
            pass
        try:
            K.set_runtime_hooks(None, None, None, None)
            K.reset_browser()
        except Exception:                   # noqa: BLE001
            pass
        self.destroy()

    def destroy(self):
        try:
            self.after_cancel(self._poll_id)
        except (tk.TclError, AttributeError):
            pass
        super().destroy()


def _set_app_user_model_id(app_id='Google.KeywordGetEmail.GUI'):
    """告诉 Windows 这是个独立程序，任务栏不要挂在 python.exe 名下。

    不设置的话，任务栏按钮会用宿主进程（pythonw.exe）的图标和分组，
    也就是你看到「图标是 Python 的」的原因。

    必须在**创建任何窗口之前**调用：窗口一旦建出来，Windows 就已经按
    原来那份 AppUserModelID 把任务栏条目分好组了。
    """
    if os.name != 'nt':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(app_id))
    except Exception:                   # noqa: BLE001  设置失败不影响运行
        pass


def main():
    _set_app_user_model_id()
    app = App()
    app.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
