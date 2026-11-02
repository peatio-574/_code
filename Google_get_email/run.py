# -*- coding: utf-8 -*-
"""关键词采集 —— 图形界面（统一入口，可切 Google / Facebook）

功能：
  · 采集源：Google 搜索 / Facebook 群组主页，两套逻辑共用同一张结果表
  · 代理：主机默认 127.0.0.1，端口可填（本地代理软件的 HTTP/混合端口）
  · 关键词：从 txt 导入，按行读取（自动识别 UTF-8 / GBK 编码）
  · 参数：搜索页数（默认 10）、每页条数（默认 10）、最多访问数
  · 结果表回显：启动时自动读取 xlsx 里已有的数据，界面本身就是完整的表
  · 采集结果实时上表（关键词 / 国家 / 网站名称 / 链接 / 邮箱 / 电话 / 来源）
  · 日志可折叠

三个文件的分工：
    run.py       本文件：界面 + 调度（双击运行 / 打包成 exe 的入口）
    google.py    Google 采集 + 通用层（结果表读写、运行时钩子、国家识别）
    facebook.py  Facebook 采集

界面通过 google.set_runtime_hooks() 接收两个采集源上报的进度与实时记录
（facebook.py 复用同一套钩子），通过 stop_requested() 响应停止。
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

import google as G                      # noqa: E402
import facebook as F                    # noqa: E402

# 可写目录（exe 同级）与资源目录（打包后在 _MEIPASS）由核心模块统一给出
BASE_DIR = G.BASE_DIR
RES_DIR = G.RES_DIR

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

# 关键词表列定义：(列 id, 标题, 宽度, 对齐)
KW_COLUMNS = (
    ('word', '关键词', 150, 'w'),
    ('pages', '页数', 52, 'center'),
    ('per_page', '条数', 52, 'center'),
    ('max_sites', '数量', 56, 'center'),
)

# 结果表列定义：(列 id, 标题, 宽度, 对齐)
COLUMNS = (
    ('idx', '#', 44, 'center'),
    ('keyword', '关键词', 104, 'w'),
    ('country', '国家', 82, 'center'),
    ('name', '网站名称', 130, 'w'),
    ('url', '网站链接', 210, 'w'),
    ('email', '邮箱', 175, 'w'),
    ('phone', '电话', 120, 'w'),
    ('origin', '来源', 76, 'center'),
    ('stage', '状态', 88, 'center'),
)

# ==================== 采集源 ====================
# 直接复用 google.py 的常量，避免两处各写一份、改一处忘另一处
SOURCE_GOOGLE = G.SOURCE_GOOGLE
SOURCE_FACEBOOK = G.SOURCE_FACEBOOK

SOURCE_TITLES = {
    SOURCE_GOOGLE: '关键词采集 · Google',
    SOURCE_FACEBOOK: '关键词采集 · Facebook',
}

SOURCE_HINTS = {
    SOURCE_GOOGLE: '在 Google 搜索网页，逐个提取联系方式（需代理）',
    SOURCE_FACEBOOK: '在 Facebook 搜群组/主页，提取地址(国家)/电话/邮箱（首次会自动打开浏览器让你登录）',
}


def new_keyword(word, defaults=None):
    """构造一条关键词配置（含它自己的采集参数）。"""
    d = defaults or {}
    return {
        'word': (word or '').strip(),
        'pages': int(d.get('pages', G.MAX_SERP_PAGES)),
        'per_page': int(d.get('per_page', G.NUM_PER_PAGE)),
        'max_sites': int(d.get('max_sites', G.MAX_SITES)),
    }


def parse_keyword_line(line, defaults=None):
    """把一行文本解析成关键词配置；无效行返回 None。

    每行格式（用 | 或 Tab 分隔，后三项可省略，省略就用默认值）：

        RC hobby shop
        RC hobby shop | 5 | 10 | 50
        RC hobby shop\t10\t20\t200

    为什么用 | 而不是逗号：关键词本身可能带逗号
    （如「rc hobby shop, online store」），用逗号切分会把关键词切坏。
    """
    s = (line or '').strip().lstrip('\ufeff')
    if not s or s.startswith('#'):
        return None

    # Tab 优先，其次竖线
    if '\t' in s:
        parts = s.split('\t')
    elif '|' in s:
        parts = s.split('|')
    else:
        parts = [s]

    word = parts[0].strip()
    if not word:
        return None

    rec = new_keyword(word, defaults)

    def take(idx, key, lo, hi):
        if idx >= len(parts):
            return
        raw = parts[idx].strip()
        if not raw:
            return
        try:
            v = int(raw)
        except ValueError:
            return          # 写错了就用默认值，不因为一行格式不对整份文件失败
        if lo <= v <= hi:
            rec[key] = v

    take(1, 'pages', 1, 50)
    take(2, 'per_page', 1, 50)
    take(3, 'max_sites', 1, 2000)
    return rec


def read_keywords(path, defaults=None):
    """按行读取关键词文件，返回 (关键词配置列表, 实际使用的编码)。

    国内 txt 常见 GBK，utf-8 读会抛 UnicodeDecodeError，
    所以按顺序试几种编码；空行和 # 开头的注释行跳过，并保持原顺序去重。
    每行可以带自己的采集参数，见 parse_keyword_line。
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

    out, seen = [], set()
    for line in raw.splitlines():
        rec = parse_keyword_line(line, defaults)
        if rec is None:
            continue
        key = rec['word'].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out, enc


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
    """鼠标悬浮在表格单元格上时，显示被列宽截断的完整内容。

    只在该列文字实际放不下时才弹（用字体真实像素宽度算），放得下就不打扰。
    结果表的「网站链接 / 网站名称」、关键词表的关键词列都挂了这个。

    参数：
        columns  要启用悬浮提示的列 id 列表；None 表示所有列都启用
                 （短内容的列本来就不会触发，不影响观感）
        delay    悬停多久才弹（毫秒），太短会一闪一闪
        wraplength 提示框的换行宽度，长 URL 会折成多行而不是拉成一条
    """

    def __init__(self, tree, columns=None, delay=320, wraplength=620):
        self.tree = tree
        self.columns = set(columns) if columns else None
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
        cid = self._col_id(col)
        if self.columns is not None and cid not in self.columns:
            self._hide()
            return

        key = (row, col)
        if key == self._key:
            return                     # 还在同一格里，别反复弹
        self._hide()
        self._key = key

        text = self._cell_text(row, cid)
        if not text or not self._is_clipped(cid, text):
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

    def _cell_text(self, row, cid):
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
        except (tk.TclError, RuntimeError):
            pass
        return tkfont.nametofont('TkDefaultFont')

    def _is_clipped(self, cid, text):
        """文字是否放不下这一列。

        ttk.Treeview 默认不显示省略号，只是把超出的部分裁掉，
        所以只能自己量：字体真实像素宽度 + 单元格左右内边距 > 列宽。
        """
        if not cid or not text:
            return False
        try:
            width = int(self.tree.column(cid, 'width'))
        except (tk.TclError, ValueError):
            return False
        if width <= 0:
            return False
        # ttk 的单元格左右各有一点内边距，再留 2px 余量避免误判
        avail = max(16, width - 12)
        try:
            need = self._font().measure(text)
        except (tk.TclError, RuntimeError):
            return False
        return need > avail

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


def _ask_text(parent, title, prompt, initial=''):
    """弹一个小输入框，返回输入内容；取消返回空串。

    tkinter 没有内置的单行输入对话框，simpleDialog 样式又太旧，
    这里自己拼一个和界面风格一致的小窗。
    """
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=CARD)
    win.resizable(False, False)
    win.transient(parent)
    try:
        win.attributes('-topmost', True)
    except tk.TclError:
        pass

    body = tk.Frame(win, bg=CARD)
    body.pack(fill='both', expand=True, padx=16, pady=14)
    ttk.Label(body, text=prompt, style='Card.TLabel').pack(anchor='w')
    var = tk.StringVar(value=initial)
    ent = ttk.Entry(body, textvariable=var, width=38)
    ent.pack(fill='x', pady=(8, 12))
    ent.focus_set()
    ent.select_range(0, 'end')

    result = {'value': ''}

    def ok(_e=None):
        result['value'] = var.get().strip()
        win.destroy()

    def cancel(_e=None):
        result['value'] = ''
        win.destroy()

    btns = tk.Frame(body, bg=CARD)
    btns.pack(fill='x')
    ttk.Button(btns, text='取消', command=cancel).pack(side='right')
    ttk.Button(btns, text='确定', style='Accent.TButton',
               command=ok).pack(side='right', padx=(0, 8))
    ent.bind('<Return>', ok)
    win.bind('<Escape>', cancel)

    win.update_idletasks()
    px = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    py = parent.winfo_rooty() + 160
    win.geometry('+%d+%d' % (max(0, px), max(0, py)))
    win.grab_set()
    parent.wait_window(win)
    return result['value']


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
        self.title(SOURCE_TITLES[SOURCE_GOOGLE])
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
        self.out_path = os.path.join(BASE_DIR, G.OUT_NAME)
        self.stat = {'kw_index': 0, 'kw_total': 0, 'links': 0,
                     'saved': 0, 'rows': 0}

        self._init_style()
        self._build()
        self._center()          # 必须在 _build 之后：要按内容实际高度定窗口
        self._attach_logger()
        self._on_source_change()   # 按初始采集源刷新标题与参数可用性

        # 启动就把结果表里的历史数据读进来，界面不只是「本次进度」，
        # 而是「表里全部数据 + 正在采集的状态」。读不到就静默略过。
        try:
            loaded = self._load_existing()
        except Exception as e:                  # noqa: BLE001
            loaded = 0
            G.logger.warning('启动时读取结果表失败：%s' % e)
        if loaded:
            G.logger.info('已载入结果表 %d 条记录：%s'
                          % (loaded, self.out_path))

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        # tkinter 回调里的异常默认只打印到控制台（打包成 exe 后看不到），
        # 重写成写日志，避免问题被吞掉。
        self.report_callback_exception = self._tk_exception
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
        #   左侧：采集源(0) / 代理(1) / 参数(2) / 关键词(3，吃掉剩余高度) / 按钮(4)
        #   右侧：结果表（日志始终留在视口内）
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_source(left)
        self._build_proxy(left)
        self._build_params(left)
        self._build_keywords(left)
        self._build_actions(left)

        self._build_progress(right)
        self._build_results(right)
        self._build_log(right)

        self._build_footer()

    # ---------------- 左侧：采集源 ----------------
    def _build_source(self, parent):
        box = self._card(parent, '采集源',
                         grid={'row': 0, 'column': 0, 'sticky': 'ew'})

        row = tk.Frame(box, bg=CARD)
        row.pack(fill='x')

        self.var_source = tk.StringVar(value=SOURCE_GOOGLE)
        self._source_widgets = []
        for value, text in ((SOURCE_GOOGLE, 'Google 搜索'),
                            (SOURCE_FACEBOOK, 'Facebook')):
            rb = tk.Radiobutton(
                row, text=text, value=value, variable=self.var_source,
                command=self._on_source_change,
                bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                selectcolor=FIELD, font=FONT_BOLD, bd=0,
                highlightthickness=0, cursor='hand2',
                padx=6, pady=3)
            rb.pack(side='left', padx=(0, 12))
            self._source_widgets.append(rb)

        self.lbl_source_hint = ttk.Label(
            box, text=SOURCE_HINTS[SOURCE_GOOGLE], style='Hint.TLabel',
            wraplength=300, justify='left')
        self.lbl_source_hint.pack(anchor='w', pady=(7, 0))

        # Facebook 专用的账号区：登录状态 + 「删除账号」
        # 账号 cookie 存在 config.ini 里，删除后下次采集需要重新登录。
        self.fb_account = tk.Frame(box, bg=CARD)
        self.lbl_fb_status = ttk.Label(
            self.fb_account, text='', style='Hint.TLabel')
        self.lbl_fb_status.pack(side='left')

        self.btn_del_account = ttk.Button(
            self.fb_account, text='删除账号', command=self._delete_account)
        self.btn_del_account.pack(side='left', padx=(10, 0))
        self._account_widgets = (self.fb_account, self.lbl_fb_status,
                                self.btn_del_account)

    def _refresh_fb_status(self):
        """刷新「登录状态：已登录 / 未登录」这一行。"""
        try:
            saved = F.login_status()
        except Exception as e:                  # noqa: BLE001
            saved = False
            G.logger.warning('读取 Facebook 登录状态失败：%s' % e)
        if saved:
            self.lbl_fb_status.configure(text='账号：已保存（可直接采集）',
                                         foreground=OK)
        else:
            self.lbl_fb_status.configure(text='账号：未登录（首次采集会打开浏览器）',
                                         foreground=MUTED)
        # 没有保存的账号时，删除按钮没有意义
        try:
            self.btn_del_account.configure(
                state='normal' if saved else 'disabled')
        except tk.TclError:
            pass

    def _delete_account(self):
        """删除 config.ini 里保存的 Facebook 账号（cookie）。"""
        if self._running():
            messagebox.showinfo('正在采集', '请先停止采集，再删除账号')
            return
        if not messagebox.askyesno(
                '删除账号',
                '将从 config.ini 中删除已保存的 Facebook 登录信息。\n\n'
                '删除后下一次 Facebook 采集会重新打开浏览器让你登录。\n'
                '确定删除吗？'):
            return

        ok, msg = F.clear_login()
        self._refresh_fb_status()
        if ok:
            self._emit('SUCCESS', msg)
        else:
            self._emit('ERROR', msg)
            messagebox.showerror('删除失败', msg)

    def _on_source_change(self):
        """切换采集源：改标题、提示，并把只有 Google 用到的参数置灰。"""
        src = self.var_source.get()
        self.title(SOURCE_TITLES.get(src, '关键词采集'))
        self.lbl_source_hint.configure(
            text=SOURCE_HINTS.get(src, ''))
        google_mode = (src == SOURCE_GOOGLE)
        for w in getattr(self, '_google_only_widgets', []):
            try:
                w.configure(state='normal' if google_mode else 'disabled')
            except tk.TclError:
                pass

        # 账号区只在 Facebook 模式下出现
        account = getattr(self, 'fb_account', None)
        if account is not None:
            if google_mode:
                account.pack_forget()
            else:
                account.pack(anchor='w', pady=(6, 0))
                self._refresh_fb_status()

    # ---------------- 左侧：代理 ----------------
    def _build_proxy(self, parent):
        box = self._card(parent, '代理设置',
                         grid={'row': 1, 'column': 0, 'sticky': 'ew'})

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
        box = self._card(parent, '默认参数（新增关键词时使用）',
                         grid={'row': 2, 'column': 0, 'sticky': 'ew'})

        # Facebook 模式用不到「搜索页数 / 每页条数」，切换时置灰
        self._google_only_widgets = []

        def line(label, factory, google_only=False):
            r = tk.Frame(box, bg=CARD)
            r.pack(fill='x', pady=3)
            ttk.Label(r, text=label, style='Card.TLabel',
                      width=10, anchor='w').pack(side='left')
            widget = factory(r)
            widget.pack(side='left', fill='x', expand=True)
            if google_only:
                self._google_only_widgets.append(widget)
            return widget

        self.var_pages = tk.StringVar(value=str(G.MAX_SERP_PAGES))
        line('搜索页数',
             lambda p: ttk.Spinbox(p, from_=1, to=50,
                                   textvariable=self.var_pages),
             google_only=True)

        self.var_per_page = tk.StringVar(value=str(G.NUM_PER_PAGE))
        line('每页条数',
             lambda p: ttk.Spinbox(p, from_=1, to=50,
                                   textvariable=self.var_per_page),
             google_only=True)

        # Google 下是「最多访问多少个网页」，Facebook 下是「每个词最多看多少个主页」
        self.var_max_sites = tk.StringVar(value=str(G.MAX_SITES))
        line('最多访问',
             lambda p: ttk.Spinbox(p, from_=1, to=2000,
                                   textvariable=self.var_max_sites))

        # 批量套用：选中关键词后一键把上面三个值写进去
        r = tk.Frame(box, bg=CARD)
        r.pack(fill='x', pady=(8, 0))
        ttk.Button(r, text='应用到选中', command=self._apply_defaults
                   ).pack(side='left')
        tk.Label(r, text='把上面三项写到选中的关键词', bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side='left', padx=(8, 0))

        # 采集方式：接口优先，接口失败时是否用浏览器兜底。
        # 关掉后全程只用 requests，不打开浏览器（更快，但 JS 站点可能采不到）。
        # 只对 Google 生效；Facebook 必须用浏览器。
        r = tk.Frame(box, bg=CARD)
        r.pack(fill='x', pady=(10, 0))
        ttk.Label(r, text='浏览器兜底', style='Card.TLabel',
                  width=10, anchor='w').pack(side='left')
        self._browser_fallback = True
        self._build_switch(r, '接口失败时用浏览器重试（仅 Google）',
                           '_browser_fallback').pack(side='left')

    def _apply_defaults(self):
        """把参数区三项值写到选中的关键词。"""
        if self._running():
            return
        sel = self.kw_tree.selection()
        if not sel:
            messagebox.showinfo('未选择', '请先在关键词列表里选中要修改的行')
            return
        d = self._default_params()
        for iid in sel:
            self.kw_tree.set(iid, 'pages', d['pages'])
            self.kw_tree.set(iid, 'per_page', d['per_page'])
            self.kw_tree.set(iid, 'max_sites', d['max_sites'])
        self._sync_from_tree()
        self._emit('SUCCESS', '已把默认参数应用到 %d 个关键词' % len(sel))

    # ---------------- 左侧：关键词 ----------------
    def _build_keywords(self, parent):
        # 这一块吃掉左侧剩余高度：关键词多了可以一直往下铺
        box = self._card(parent, '关键词（每个词可单独设参数）',
                         grid={'row': 3, 'column': 0, 'sticky': 'nsew'})

        bar = tk.Frame(box, bg=CARD)
        bar.pack(fill='x', pady=(0, 8))
        self.btn_import = ttk.Button(bar, text='导入 txt',
                                     command=self._pick_txt)
        self.btn_import.pack(side='left')
        self.btn_add = ttk.Button(bar, text='添加',
                                  command=self._add_keyword)
        self.btn_add.pack(side='left', padx=6)
        self.btn_remove = ttk.Button(bar, text='移除选中',
                                     command=self._remove_selected)
        self.btn_remove.pack(side='left')
        self.btn_clear_kw = ttk.Button(bar, text='清空',
                                       command=self._clear_keywords)
        self.btn_clear_kw.pack(side='left', padx=6)
        self.lbl_kw_count = ttk.Label(bar, text='共 0 个', style='Hint.TLabel')
        self.lbl_kw_count.pack(side='right')

        wrap = tk.Frame(box, bg=FIELD, highlightbackground=BORDER,
                        highlightthickness=1)
        wrap.pack(fill='both', expand=True)

        # 关键词表：每个关键词带自己的页数 / 条数 / 最多访问
        self.kw_tree = ttk.Treeview(
            wrap, columns=('word', 'pages', 'per_page', 'max_sites'),
            show='headings', selectmode='extended', height=8)
        for cid, title, width, anchor in KW_COLUMNS:
            self.kw_tree.heading(cid, text=title, anchor=anchor)
            self.kw_tree.column(
                cid, width=width, minwidth=40, anchor=anchor,
                stretch=(cid == 'word'))
        self.kw_tree.tag_configure('odd', background=FIELD)
        self.kw_tree.tag_configure('even', background=CARD)

        vsb = SlimScrollbar(wrap, orient='vertical', bg=FIELD,
                            command=self.kw_tree.yview, target=self.kw_tree)
        self.kw_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y', padx=(0, 3), pady=4)
        self.kw_tree.pack(side='left', fill='both', expand=True,
                          padx=(2, 2), pady=4)

        # 双击数字列 → 就地修改
        self.kw_tree.bind('<Double-1>', self._kw_begin_edit)
        self._kw_editor = None

        # 兼容旧代码/测试：关键字列表以 Listbox 形式暴露过，
        # 现在改用 Treeview，旧属性名指向同一个控件。
        self.lb_keys = self.kw_tree

    # ---------------- 左侧：操作按钮 ----------------
    def _build_actions(self, parent):
        box = tk.Frame(parent, bg=BG)
        box.grid(row=4, column=0, sticky='ew')

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
        # 手工重读结果表：在 Excel 里改过表、或想重新对齐界面时用
        ttk.Button(head, text='从结果表刷新',
                   command=self._reload_from_file).pack(side='right')

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
        # 内容被列宽截断时，鼠标悬浮显示完整内容。
        # 明确列出「网站名称 / 网站链接」这两列 —— 它们最容易超长；
        # 邮箱也可能很长，一并挂上，其余列本来也不会触发。
        self.tooltip = TreeTooltip(self.tree,
                                   columns=('name', 'url', 'email'))

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

    # ---------------- 读取结果表 -> 回显到界面 ----------------
    # 结果表的列位置有可能变（用户提过把国家前移），所以一律按「表头名字」定位，
    # 不写死列下标。
    SAVED_COLUMNS = ('关键词', '国家', '网站名称', '网站链接', '邮箱', '电话',
                     '来源')

    def _load_existing(self, path=None):
        """把结果表里已有的数据读进界面表格，返回读入的行数。

        这样界面不只是「本次采集的实时进度」，也能直接看到文件里历史攒下的
        全部数据，不用打开 Excel 才知道表里有什么。已有的链接在后续采集时
        会原地更新（_row_key 相同），不会变成重复行。
        """
        path = path or self.out_path
        if not path or not os.path.isfile(path):
            return 0
        try:
            import zipfile
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
        except (OSError, ValueError, KeyError, TypeError,
                zipfile.BadZipFile) as e:
            # 文件被独占 / 不是有效的 xlsx（空文件、损坏、正在写）：
            # 提示一句就好，不能因为回显失败把界面搞崩。
            self._emit('WARNING', '读取结果表失败：%s' % e)
            return 0

        loaded = 0
        try:
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = [str(c or '').strip() for c in next(rows, [])]
            pos = {}
            for i, name in enumerate(header):
                if name and name not in pos:
                    pos[name] = i
            if '网站链接' not in pos:
                # 表头不是我们的格式（或空表），不硬塞
                return 0

            def pick(row, name):
                i = pos.get(name)
                if i is None or i >= len(row):
                    return ''
                value = row[i]
                return '' if value is None else str(value).strip()

            def split_list(text):
                if not text or text == G.NO_DATA_TEXT:
                    return []
                return [p.strip() for p in text.split(';') if p.strip()]

            for row in rows:
                if not row:
                    continue
                url = pick(row, '网站链接')
                if not url:
                    continue
                rec = {
                    'keyword': pick(row, '关键词'),
                    'country': pick(row, '国家'),
                    'site_name': pick(row, '网站名称'),
                    'url': url,
                    'emails': split_list(pick(row, '邮箱')),
                    'phones': split_list(pick(row, '电话')),
                    'origin': pick(row, '来源'),
                    'source': 'saved',
                    'written': True,
                }
                if self._row_key(rec) in self.row_by_url:
                    continue                 # 文件里重复的行只显示一次
                self._add_row(rec)
                loaded += 1
        except (OSError, ValueError, KeyError, TypeError) as e:
            self._emit('WARNING', '解析结果表失败：%s' % e)
        finally:
            try:
                wb.close()
            except (OSError, ValueError):
                pass
        return loaded

    def _reload_from_file(self):
        """清空表格后重新从结果表读取（界面上的「从结果表刷新」）。"""
        if self._running():
            messagebox.showinfo('正在采集', '采集过程中不能重读结果表')
            return
        self._clear_rows()
        n = self._load_existing()
        self._emit('INFO' if n else 'MUTED',
                   '已从结果表读取 %d 条记录：%s'
                   % (n, os.path.basename(self.out_path)))

    def _update_rows_label(self):
        n = len(self.tree.get_children())
        self.lbl_rows.configure(text='实时显示，共 %d 条' % n)

    # 状态列只有两种取值：已完成 / 未完成
    #
    #   已完成 —— 这个链接已经处理完并且写进了结果表
    #             （本次采到并写入，或表里本来就有、本次跳过）
    #   未完成 —— 还没处理（待采集 / 访问了但没打开）
    #
    # 具体走的是接口、浏览器还是 Facebook，看「来源」列即可，
    # 不必再挤进状态列。
    STAGE_DONE = '已完成'
    STAGE_TODO = '未完成'
    # 内部 source -> 是否算「已完成」
    DONE_SOURCES = frozenset(('http', 'browser', 'facebook', 'skip', 'saved'))

    def _stage_text(self, rec):
        source = rec.get('source') or 'pending'
        if source in self.DONE_SOURCES:
            return self.STAGE_DONE
        return self.STAGE_TODO

    def _cells(self, rec):
        """按列 id 组装一行，不依赖 COLUMNS 的书写顺序。"""
        emails = rec.get('emails') or []
        phones = rec.get('phones') or []
        name = rec.get('site_name') or rec.get('title') or ''
        source = rec.get('source') or 'pending'
        stage = self._stage_text(rec)
        country = (rec.get('country') or '').strip()
        if not country:
            # 还没处理的行没查过国家，写「—」比写「未知」更准确
            country = ('—' if source in ('pending', 'skip')
                       else G.UNKNOWN_COUNTRY)
        return {
            'idx': rec.get('_seq', ''),
            'keyword': rec.get('keyword', ''),
            'name': name[:40],
            'url': rec.get('url', ''),
            'country': country,
            'email': '; '.join(emails)[:120] or '—',
            'phone': '; '.join(phones)[:80] or '—',
            'origin': self._origin_text(rec),
            'stage': stage,
        }

    @staticmethod
    def _origin_text(rec):
        """「来源」列：和写进 xlsx 的值保持一致。

        · 采集模块上报时带了 origin，直接用；
        · 还没访问的占位行（pending）不知道来源，显示「—」；
        · 其余（含老记录）按链接域名推断。
        """
        if str(rec.get('origin') or '').strip():
            return G.source_cell(rec)
        if (rec.get('source') or 'pending') == 'pending':
            return '—'
        try:
            return G.source_cell(rec)
        except Exception:                  # noqa: BLE001
            return '—'

    def _tags_for(self, rec, seq):
        emails = rec.get('emails') or []
        phones = rec.get('phones') or []
        source = rec.get('source') or 'pending'
        base = 'odd' if seq % 2 else 'even'
        if source == 'pending':
            return (base, 'pending')
        if source == 'saved':
            # 从结果表读进来的历史数据：加个 saved 标记，
            # 后续「跳过采集」的回报靠它来判断「这行不能清空」
            return (base, 'saved')
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
            'country': '',
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
            # 从结果表读进来的行已经带着完整数据，而「跳过（表里已有）」的回报
            # 是空记录 —— 不能让它把这行已有的邮箱/电话/国家清掉。
            tags = self.tree.item(iid, 'tags') or ()
            if rec.get('source') == 'skip' and 'saved' in tags:
                return
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
        """把 google / facebook 共用的 logger 挂到界面上（只挂一次）。"""
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
            title='选择关键词文件（每行一个，可用 | 追加参数）',
            initialdir=BASE_DIR,
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            words, enc = read_keywords(path, self._default_params())
        except (OSError, ValueError) as e:
            messagebox.showerror('读取失败', str(e))
            return
        if not words:
            messagebox.showwarning('没有关键词',
                                  '文件里没有有效内容（空行和 # 注释会被忽略）')
            return
        self._set_keywords(words)
        G.logger.info('已导入 %d 个关键词（编码 %s）：%s'
                      % (len(words), enc, path))

    def _set_keywords(self, words):
        """载入关键词列表。words 可以是字符串列表，也可以是配置 dict 列表。"""
        self.keywords = []
        for w in words or []:
            if isinstance(w, dict):
                self.keywords.append(new_keyword(w.get('word'), w))
            else:
                self.keywords.append(new_keyword(w, self._default_params()))
        self._refresh_kw_tree()
        self._emit('SUCCESS', '关键词已载入：%d 个' % len(self.keywords))

    def _default_params(self):
        """参数区当前的三项值（作为新增 / 导入关键词时的默认值）。"""
        def as_int(var, fallback):
            try:
                return int(str(var.get()).strip())
            except (ValueError, AttributeError):
                return fallback

        return {
            'pages': as_int(self.var_pages, G.MAX_SERP_PAGES),
            'per_page': as_int(self.var_per_page, G.NUM_PER_PAGE),
            'max_sites': as_int(self.var_max_sites, G.MAX_SITES),
        }

    def _refresh_kw_tree(self):
        """把 self.keywords 重画到关键词表里。"""
        for iid in self.kw_tree.get_children():
            self.kw_tree.delete(iid)
        for i, rec in enumerate(self.keywords):
            self.kw_tree.insert(
                '', 'end', iid=str(i),
                values=(rec['word'], rec['pages'], rec['per_page'],
                        rec['max_sites']),
                tags=('odd' if i % 2 else 'even',))
        self.lbl_kw_count.configure(text='共 %d 个' % len(self.keywords))

    def _sync_from_tree(self):
        """把表格里的值写回 self.keywords（编辑后调用）。

        行的 iid 就是关键词在 self.keywords 里的下标（见 _refresh_kw_tree），
        这里按 iid 定位而不是靠遍历顺序 —— 顺序一旦对不上，
        参数就会写到别的关键词头上，这种错很难发现。
        """
        for iid in self.kw_tree.get_children():
            try:
                i = int(iid)
            except ValueError:
                continue
            if not (0 <= i < len(self.keywords)):
                continue
            vals = self.kw_tree.item(iid, 'values')
            if len(vals) < 4:
                continue
            rec = self.keywords[i]
            word = str(vals[0]).strip()
            if word:
                rec['word'] = word
            for idx, key in ((1, 'pages'), (2, 'per_page'), (3, 'max_sites')):
                try:
                    rec[key] = int(vals[idx])
                except (ValueError, IndexError, TypeError):
                    pass

    def _add_keyword(self):
        """手动添加一个关键词（用参数区的默认值）。"""
        if self._running():
            return
        word = _ask_text(self, '添加关键词', '请输入关键词：', '')
        if not word:
            return
        word = word.strip()
        if not word:
            return
        if any(r['word'].lower() == word.lower() for r in self.keywords):
            messagebox.showinfo('已存在', '关键词「%s」已在列表里' % word)
            return
        self.keywords.append(new_keyword(word, self._default_params()))
        self._refresh_kw_tree()
        self.lbl_kw_count.configure(text='共 %d 个' % len(self.keywords))
        self._emit('SUCCESS', '已添加关键词：%s' % word)

    def _kw_begin_edit(self, event):
        """双击数字列 → 在单元格上放一个 Entry 就地修改。"""
        if self._running():
            return
        tree = self.kw_tree
        col = tree.identify_column(event.x)      # '#1' ~ '#4'，外部区域是 ''
        row = tree.identify_row(event.y)
        if not row or not col:
            return
        try:
            idx = int(col.replace('#', '')) - 1
        except ValueError:
            return
        if idx <= 0 or idx >= len(KW_COLUMNS):
            return                      # 关键词本身不在这里改（避免误触）

        bbox = tree.bbox(row, col)
        if not bbox:
            return
        x, y, w, h = bbox
        key = KW_COLUMNS[idx][0]
        cur = tree.set(row, key)

        self._kw_end_edit()
        ent = ttk.Entry(tree, justify='center')
        ent.insert(0, str(cur))
        ent.select_range(0, 'end')
        ent.place(x=x, y=y, width=w, height=h)

        # 回车提交后销毁 Entry 会再触发一次 <FocusOut>，
        # 此时 ent.get() 在已销毁的控件上会抛 TclError —— 用标记挡住重复提交。
        state = {'done': False}

        def commit(_e=None):
            if state['done']:
                return
            state['done'] = True
            try:
                raw = ent.get().strip()
            except tk.TclError:
                self._kw_end_edit()
                return
            try:
                v = int(raw)
            except ValueError:
                self._emit('WARNING', '「%s」必须是数字' % KW_COLUMNS[idx][1])
                self._kw_end_edit()
                return
            lo, hi = (1, 50) if key != 'max_sites' else (1, 2000)
            if not lo <= v <= hi:
                self._emit('WARNING', '%s 需在 %d ~ %d 之间'
                           % (KW_COLUMNS[idx][1], lo, hi))
                self._kw_end_edit()
                return
            tree.set(row, key, v)
            self._sync_from_tree()
            self._kw_end_edit()

        def cancel(_e=None):
            state['done'] = True
            self._kw_end_edit()

        ent.bind('<Return>', commit)
        ent.bind('<FocusOut>', commit)
        ent.bind('<Escape>', cancel)
        ent.focus_set()
        self._kw_editor = ent

    def _kw_end_edit(self):
        ent = getattr(self, '_kw_editor', None)
        if ent is not None:
            try:
                ent.destroy()
            except tk.TclError:
                pass
            self._kw_editor = None

    def _remove_selected(self):
        if self._running():
            return
        sel = self.kw_tree.selection()
        if not sel:
            return
        drop = set(sel)
        keep = []
        for i, rec in enumerate(self.keywords):
            if str(i) in drop:
                continue
            keep.append(rec)
        self.keywords = keep
        self._refresh_kw_tree()
        self.lbl_kw_count.configure(text='共 %d 个' % len(self.keywords))

    def _clear_keywords(self):
        if self._running():
            return
        self._kw_end_edit()
        self._set_keywords([])

    # ---------------- 运行状态 ----------------
    def _running(self):
        return self.worker is not None and self.worker.is_alive()

    def _set_running(self, running):
        normal = 'disabled' if running else 'normal'
        for w in (self.btn_import, self.btn_add, self.btn_remove,
                  self.btn_clear_kw, self.spn_port, self.ent_ip):
            try:
                w.configure(state=normal)
            except tk.TclError:
                pass
        self.btn_start.configure(state='disabled' if running else 'normal')
        self.btn_stop.configure(state='normal' if running else 'disabled')
        # 采集期间不允许切采集源，也不允许删除账号
        for w in self._source_widgets:
            try:
                w.configure(state='disabled' if running else 'normal')
            except tk.TclError:
                pass
        try:
            self.btn_del_account.configure(
                state='disabled' if running else 'normal')
        except tk.TclError:
            pass
        if not running:
            self._on_source_change()      # 恢复后按当前源重新置灰参数

    # ---------------- 开始 / 停止 ----------------
    def _read_config(self):
        """读取全局配置（采集源、代理、输出文件、采集方式）。

        页数 / 条数 / 最多访问不再在这里，它们属于每个关键词自己，
        见 self.keywords 里每一项的 pages / per_page / max_sites。
        """
        if not self.keywords:
            messagebox.showwarning('缺少关键词', '请先导入关键词 txt 文件')
            return None

        self._sync_from_tree()          # 表格里改过的值写回 self.keywords

        for rec in self.keywords:
            if not rec['word']:
                messagebox.showerror('关键词为空', '存在空的关键词，请先修改')
                return None

        source = self.var_source.get() or SOURCE_GOOGLE

        proxy = None
        port = self.var_port.get().strip()
        if port:
            ip = self.ent_ip.get().strip() or '127.0.0.1'
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                messagebox.showerror('代理端口错误',
                                     '端口需为 1 ~ 65535 的数字，留空表示直连')
                return None
            proxy = {'server': 'http://%s:%s' % (ip, port)}

        return {'source': source, 'proxy': proxy, 'out': self.out_path,
                'browser_fallback': bool(self._browser_fallback)}

    def _start(self):
        if self._running():
            return
        # 先收掉正在编辑的单元格，否则刚输入的值会被丢掉
        self._kw_end_edit()
        cfg = self._read_config()
        if cfg is None:
            return

        self.stop_event = threading.Event()
        self.stat = {'kw_index': 0, 'kw_total': len(self.keywords),
                     'links': 0, 'saved': 0, 'rows': 0}
        # 不清空表格：先按结果表重新读一遍（文件可能刚在 Excel 里被改过），
        # 这样已有的数据一直留在界面上，本次采集只往上叠加 / 原地更新。
        self._clear_rows()
        loaded = self._load_existing(cfg['out'])
        if loaded:
            G.logger.info('界面已载入结果表 %d 条历史记录' % loaded)
        self._update_stats()
        self.pb['value'] = 0
        self.lbl_percent.configure(text='0%')
        self.lbl_stage.configure(text='启动浏览器……')
        self.lbl_kw.configure(text='')
        self._set_running(True)
        self.start_time = time.time()

        facebook_mode = (cfg['source'] == SOURCE_FACEBOOK)

        self._emit('DIVIDER', '─' * 46)
        G.logger.info('采集源：%s' % ('Facebook 群组/主页' if facebook_mode
                                       else 'Google 搜索'))
        if cfg['proxy']:
            G.logger.info('代理：%s' % cfg['proxy']['server'])
        elif facebook_mode:
            G.logger.info('代理：不使用（直连）')
        else:
            G.logger.info('代理：不使用（直连，Google 大概率会要求验证）')
        G.logger.info('关键词 %d 个' % len(self.keywords))
        for rec in self.keywords:
            if facebook_mode:
                G.logger.info('  · %s ｜ 最多 %d 个主页'
                              % (rec['word'], rec['max_sites']))
            else:
                G.logger.info('  · %s ｜ 页数 %d ｜ 每页 %d 条 ｜ 最多 %d 个'
                              % (rec['word'], rec['pages'],
                                 rec['per_page'], rec['max_sites']))
        if facebook_mode:
            G.logger.info('采集方式：浏览器（首次会在窗口里等你登录 Facebook）')
        else:
            G.logger.info('采集方式：接口逐个抓取（串行）%s'
                          % ('，接口失败时用浏览器兜底'
                             if cfg['browser_fallback']
                             else '，仅接口（不打开浏览器）'))

        jobs = [dict(r) for r in self.keywords]
        self.worker = threading.Thread(target=self._run,
                                       args=(jobs, cfg),
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
        """采集线程：不碰界面，只往队列里发消息。

        两个采集源共用 google.set_runtime_hooks() 这一套钩子
        （facebook.py 也是调用 google 里的 report_progress / report_record），
        所以这里只需要设置一次。
        """
        q = self.queue
        facebook_mode = (cfg['source'] == SOURCE_FACEBOOK)
        # 关键词之间的间隔：Google 要防止被判定异常流量，Facebook 也需要喘口气
        gap = G.SERP_DELAY if not facebook_mode else (2.0, 4.0)

        def progress(stage, cur, total, text):
            q.put(('progress', stage, cur, total, text))

        G.set_runtime_hooks(
            progress=progress, stop_event=self.stop_event,
            record=lambda rec: q.put(('record', rec)),
            link=lambda rec: q.put(('link', rec)))
        total_saved = 0
        try:
            for i, job in enumerate(keywords, 1):
                if self.stop_event.is_set():
                    left = len(keywords) - i + 1
                    q.put(('log', 'WARNING',
                           '已停止，剩余 %d 个关键词未执行' % left))
                    break
                kw = job['word']
                q.put(('kw', i, len(keywords), kw))
                q.put(('log', 'DIVIDER', '─' * 46))
                if facebook_mode:
                    G.logger.info('开始采集关键词：%s（%d/%d）｜ 最多 %d 个主页'
                                  % (kw, i, len(keywords), job['max_sites']))
                else:
                    G.logger.info('开始采集关键词：%s（%d/%d）｜ 页数 %d ｜ '
                                  '每页 %d 条 ｜ 最多 %d 个'
                                  % (kw, i, len(keywords), job['pages'],
                                     job['per_page'], job['max_sites']))
                try:
                    if facebook_mode:
                        saved = F.crawl(kw, proxy=cfg['proxy'],
                                        max_sites=job['max_sites'],
                                        out_file=cfg['out'])
                    else:
                        saved = G.crawl(kw, proxy=cfg['proxy'],
                                        max_pages=job['pages'],
                                        max_sites=job['max_sites'],
                                        out_file=cfg['out'],
                                        per_page=job['per_page'],
                                        browser_fallback=cfg['browser_fallback'])
                    total_saved += saved
                except Exception as e:      # noqa: BLE001
                    # 单个关键词失败不能让整批停掉；日志里带上完整堆栈，
                    # 否则打包成 exe 后完全看不到问题出在哪一行。
                    import traceback
                    q.put(('log', 'ERROR', '关键词「%s」采集失败：%s'
                           % (kw, str(e)[:200])))
                    q.put(('log', 'ERROR',
                           traceback.format_exc()[:2500]))
                    saved = 0
                q.put(('kw_done', i, len(keywords), kw, total_saved))
                if (not self.stop_event.is_set()) and i < len(keywords):
                    time.sleep(random.uniform(*gap))
        except Exception as e:              # noqa: BLE001
            q.put(('log', 'ERROR', '采集线程异常：%s' % str(e)[:300]))
            import traceback
            q.put(('log', 'ERROR', traceback.format_exc()[:2500]))
        finally:
            G.set_runtime_hooks(None, None, None, None)
            q.put(('log', 'MUTED', '正在关闭浏览器……'))
            try:
                G.reset_browser()
            except Exception as e:              # noqa: BLE001
                q.put(('log', 'WARNING', '关闭浏览器出错（可忽略）：%s' % e))
            q.put(('done', total_saved, self.stop_event.is_set(),
                    cfg['out']))

    # ---------------- 消息循环 ----------------
    def _poll(self):
        """定时把队列里的消息搬进界面。

        这里必须做到「单条消息出错不影响整个界面」：
        一旦本函数抛异常，after() 就不会再注册，界面会永久卡死
        （表现为日志停在某一行、按钮全部无响应，而后台采集还在继续）。
        """
        try:
            while True:
                msg = self.queue.get_nowait()
                try:
                    self._handle(msg)
                except Exception as e:          # noqa: BLE001
                    self._log_exc('处理界面消息失败（%s）：%s'
                                  % (msg[:1], e))
        except queue.Empty:
            pass
        except Exception as e:                  # noqa: BLE001
            self._log_exc('界面轮询异常：%s' % e)
        finally:
            try:
                self._tick_elapsed()
            except Exception:                   # noqa: BLE001
                pass
            self._poll_id = self.after(120, self._poll)

    def _log_exc(self, prefix=''):
        """把异常连堆栈写进日志（界面和文件都有），方便定位。"""
        import traceback
        tb = traceback.format_exc()
        text = (prefix + '\n' + tb).strip()
        try:
            G.logger.error('【界面异常】%s' % text[:2000])
        except Exception:                       # noqa: BLE001
            pass

    def _tk_exception(self, exc, val, tb):
        """tkinter 回调里未捕获的异常：默认只在控制台打印（windowed 模式看不到）。

        重写它，把堆栈写进日志，这样打包成 exe 后也能查到问题。
        """
        import traceback
        text = ''.join(traceback.format_exception(exc, val, tb))
        try:
            G.logger.error('【界面异常】tkinter 回调出错\n%s' % text[:2000])
        except Exception:                       # noqa: BLE001
            pass

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
            G.set_runtime_hooks(None, None, None, None)
            G.reset_browser()
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


def _install_crash_guard():
    """装上崩溃取证：即使进程被原生错误干掉，也留下现场文件。

    打包成 windowed exe 后没有控制台，异常默认无处可看，
    表现为「程序直接关闭、什么也没留下」。这里做三件事：

      1. faulthandler —— 段错误 / 栈溢出这类原生崩溃也能打印 Python 栈
      2. sys.excepthook —— 主线程未捕获异常
      3. threading.excepthook —— 子线程未捕获异常

    全部写到 <可写目录>/logs/crash_<时间>.txt。
    """
    import datetime
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
        crash_path = os.path.join(BASE_DIR, 'logs', 'crash_%s.txt' % stamp)
        crash_file = open(crash_path, 'a', encoding='utf-8', buffering=1)
    except OSError:
        crash_file = None

    def write(tag, text):
        if crash_file is None:
            return
        try:
            crash_file.write('===== %s %s =====\n%s\n'
                             % (tag, datetime.datetime.now(), text))
            crash_file.flush()
        except Exception:                   # noqa: BLE001
            pass

    # 1. 原生崩溃
    try:
        import faulthandler
        if crash_file is not None:
            faulthandler.enable(file=crash_file, all_threads=True)
    except Exception:                       # noqa: BLE001
        pass

    # 2. 主线程异常
    def _excepthook(exc_type, exc_val, exc_tb):
        import traceback
        text = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        write('主线程未捕获异常', text)
        try:
            G.logger.error('【崩溃】主线程未捕获异常\n%s' % text[:3000])
        except Exception:                   # noqa: BLE001
            pass

    sys.excepthook = _excepthook

    # 3. 子线程异常（采集线程崩了也要记录）
    try:
        def _thread_hook(args):
            import traceback
            text = ''.join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback))
            write('子线程未捕获异常：%s' % args.thread.name, text)
            try:
                G.logger.error('【崩溃】子线程 %s 异常\n%s'
                               % (args.thread.name, text[:3000]))
            except Exception:               # noqa: BLE001
                pass

        threading.excepthook = _thread_hook
    except (AttributeError, TypeError):
        pass                        # Python < 3.8 没有这个钩子

    return crash_file


def main():
    _set_app_user_model_id()
    _install_crash_guard()
    app = App()
    try:
        app.mainloop()
    except BaseException:                   # noqa: BLE001
        # mainloop 本身抛异常（Tcl 错误等）也要留证据再退出
        import traceback
        text = traceback.format_exc()
        try:
            G.logger.error('【崩溃】主循环异常退出\n%s' % text[:3000])
        except Exception:                   # noqa: BLE001
            pass
        try:
            with open(os.path.join(BASE_DIR, 'logs',
                                   'crash_mainloop.txt'),
                      'a', encoding='utf-8') as f:
                f.write(text)
        except OSError:
            pass
        raise
    return 0


if __name__ == '__main__':
    sys.exit(main())
