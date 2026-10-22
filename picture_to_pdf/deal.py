# coding='utf-8'
"""艺术水平考级证书附件 —— 作品照片批量贴图（GUI 版）

功能：
  1. 内置空白模板 空白副证图片.pdf（A4 210×297mm，打包进 exe）。
  2. 选择图片根目录，程序会遍历其下所有“图片目录”（直接含图片的子目录）。
  3. 每个图片目录按其名称推断作品编号前缀（如 029-021-011图片 -> 029-021-011），
     在同级生成 “029-021-011附证” 目录，并逐张图片生成 PDF：
         - 照片固定按 5 寸输出（12.7cm × 8.9cm，比例 3:2）：
           竖图 8.9cm × 12.7cm，横图 12.7cm × 8.9cm；
         - 图片按 3:2 居中裁切后贴合，不拉伸变形；
         - 照片右下角标注图片标号（如 004）；
         - “作品编号（NO）：”处填写 前缀-序号（如 029-021-011-004）。

运行：
    D:\\_code\\python\\python.exe picture_to_pdf\\deal.py
"""
import os
import queue
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

try:
    import pymupdf as fitz
except ImportError:  # 兼容旧版本
    import fitz

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    """资源文件路径：源码运行取脚本目录，打包后取 exe 内置的解包目录。"""
    if getattr(sys, 'frozen', False):
        bundled = Path(getattr(sys, '_MEIPASS', BASE_DIR)) / name
        if bundled.exists():
            return bundled
    return BASE_DIR / name


def app_dir() -> Path:
    """程序所在目录：打包后为 exe 目录，源码运行为脚本目录。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR


# 日志目录：程序目录下的 logs，按日期分文件
LOG_DIR = app_dir() / 'logs'


def log_file_path() -> Path:
    """当天的日志文件路径：logs/YYYYMMDD.log。"""
    from datetime import datetime
    return LOG_DIR / f'{datetime.now():%Y%m%d}.log'


def write_log_file(text: str):
    """把一行日志追加写入当日日志文件；写入失败不影响界面日志。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = f'{datetime.now():%Y-%m-%d %H:%M:%S}'
        with open(log_file_path(), 'a', encoding='utf-8') as fp:
            fp.write(f'[{stamp}] {text}\n')
    except OSError:
        pass


# ==================== 默认配置 ====================
TEMPLATE = resource_path('空白副证图片.pdf')   # 空白模板（打包进 exe）
IMAGE_ROOT = app_dir()                          # 图片根目录（其下为各图片目录）
OUTPUT_ROOT = None                              # 输出根目录，None 表示与图片目录同级
NUMBER_PREFIX = '029-021-011'                   # 单目录运行时的默认前缀

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}

# 目录名后缀，用于从 “029-021-011图片” 中取出 “029-021-011”
DIR_SUFFIXES = ('图片集', '图片', '照片', '作品', '图')
OUTPUT_SUFFIX = '附证'

# 字体：仅需数字与连字符，打包时用宋体子集（约 10KB）避免把 17MB 字体塞进 exe
FONT_FILE = resource_path('simsun_num.ttf')
if not FONT_FILE.is_file():
    FONT_FILE = resource_path('simsun.ttc')
if not FONT_FILE.is_file():
    FONT_FILE = Path(r'C:\Windows\Fonts\simsun.ttc')
FONT_NAME = 'SimSun'

# ==================== 版面坐标（单位 pt，A4 页面 595.276 × 841.89） ====================
# 中间照片固定为 5 寸（12.7cm × 8.9cm，比例 3:2），竖向 8.9×12.7，横向 12.7×8.9
PT_PER_CM = 72.0 / 2.54
PHOTO_SHORT = 8.9 * PT_PER_CM    # 252.28 pt
PHOTO_LONG = 12.7 * PT_PER_CM    # 360.00 pt

# 照片纵向可用区间：顶边压住模板“考级作品照片”占位，底边留出下方说明文字
PHOTO_TOP = 246.6
PHOTO_BOTTOM = PHOTO_TOP + PHOTO_LONG

NO_ORIGIN = (224.43, 690.65)   # “作品编号（NO）：”后文字的基线起点
NO_FONT_SIZE = 12.0

MARK_FONT_SIZE = 12.0    # 照片右下角标号字号
MARK_RIGHT_PAD = 0.10    # 标号距照片右边 = 照片宽度 × 该比例
MARK_BOTTOM_PAD = 12.0   # 标号距照片底边（pt）

PHOTO_JPEG_QUALITY = 95  # 裁切后的照片质量

NUMBER_RE = re.compile(r'(\d{3})\D?(\d{3})\D?(\d{3})')

Image.MAX_IMAGE_PIXELS = None

# ==================== 基础工具 ====================
def natural_key(path: Path):
    """按文件名中的数字排序，避免 10.jpg 排在 9.jpg 前面。"""
    nums = re.findall(r'\d+', path.stem)
    return int(nums[0]) if nums else 0, path.stem


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


def collect_images(image_dir: Path):
    """收集目录内的图片，按文件名数字升序。"""
    files = [p for p in image_dir.iterdir() if is_image(p)]
    return sorted(files, key=natural_key)


def image_size(path: Path):
    """读取图片像素尺寸（已考虑 EXIF 方向）。"""
    with Image.open(path) as im:
        width, height = im.size
        try:
            orientation = im.getexif().get(274)
        except (OSError, ValueError, AttributeError):
            orientation = None
    if orientation in (5, 6, 7, 8):
        width, height = height, width
    return width, height


def prefix_from_dir(name: str) -> str:
    """从目录名推断作品编号前缀：029-021-011图片 -> 029-021-011。"""
    match = NUMBER_RE.search(name)
    if match:
        return '-'.join(match.groups())
    cleaned = name
    for suffix in DIR_SUFFIXES:
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    return cleaned.strip(' _-') or name


def find_image_dirs(root: Path):
    """遍历根目录下的所有子目录，返回直接含图片的目录列表（跳过输出目录）。"""
    if not root.is_dir():
        raise FileNotFoundError(f'图片根目录不存在：{root}')

    found = []
    for current, dirnames, _files in os.walk(root):
        current_path = Path(current)
        # 跳过输出目录，避免把自己的产物当成素材
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.endswith(OUTPUT_SUFFIX) and not d.startswith('.')
        )
        if current_path == root:
            continue
        if collect_images(current_path):
            found.append(current_path)
    return sorted(found, key=lambda p: str(p).lower())


def photo_area(page_width: float, portrait: bool):
    """5 寸照片在页面上的位置（pt），水平居中、纵向居中于照片带内。

    竖向 8.9cm × 12.7cm，横向 12.7cm × 8.9cm。
    """
    width = PHOTO_SHORT if portrait else PHOTO_LONG
    height = PHOTO_LONG if portrait else PHOTO_SHORT
    x0 = (page_width - width) / 2
    y0 = PHOTO_TOP + (PHOTO_LONG - height) / 2
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def crop_to_ratio(image: Path, ratio: float):
    """按目标长宽比居中裁切，返回 (JPEG 字节, 宽, 高)。

    裁切而不是拉伸，保证照片不变形且保持 3:2。
    """
    from io import BytesIO

    from PIL import ImageOps

    with Image.open(image) as src:
        photo = ImageOps.exif_transpose(src).convert('RGB')

    width, height = photo.size
    if width <= 0 or height <= 0:
        raise ValueError('图片尺寸无效')
    current = width / height
    if abs(current - ratio) > 1e-4:
        if current > ratio:                     # 太宽，裁左右
            new_w = max(1, int(round(height * ratio)))
            left = (width - new_w) // 2
            photo = photo.crop((left, 0, left + new_w, height))
        else:                                   # 太高，裁上下
            new_h = max(1, int(round(width / ratio)))
            top = (height - new_h) // 2
            photo = photo.crop((0, top, width, top + new_h))

    buffer = BytesIO()
    photo.save(buffer, 'JPEG', quality=PHOTO_JPEG_QUALITY, subsampling=0)
    return buffer.getvalue(), photo.width, photo.height


# ==================== 生成单页 ====================
def build_page(template: Path, image: Path, target: Path, number: int, prefix: str):
    """把一张 5 寸照片贴到模板上并保存为单页 PDF。"""
    label = f'{number:03d}'
    doc = fitz.open(template)
    try:
        page = doc[0]
        width, height = image_size(image)
        portrait = height >= width

        rect = photo_area(page.rect.width, portrait)
        data, _, _ = crop_to_ratio(image, rect.width / rect.height)

        # 照片覆盖在模板“考级作品照片”占位文字之上，尺寸即 5 寸
        page.insert_image(rect, stream=data, keep_proportion=False)

        # 照片右下角标注图片标号
        mark_x = rect.x1 - rect.width * MARK_RIGHT_PAD - len(label) * MARK_FONT_SIZE * 0.5
        mark_y = rect.y1 - MARK_BOTTOM_PAD
        page.insert_text((mark_x, mark_y), label, fontname=FONT_NAME,
                         fontfile=str(FONT_FILE), fontsize=MARK_FONT_SIZE,
                         color=(0, 0, 0))

        # 作品编号（NO）：
        page.insert_text(NO_ORIGIN, f'{prefix}-{label}', fontname=FONT_NAME,
                         fontfile=str(FONT_FILE), fontsize=NO_FONT_SIZE,
                         color=(0, 0, 0))

        # 只嵌入用到的字形，避免整份宋体被写入
        try:
            doc.subset_fonts()
        except (RuntimeError, ValueError):
            pass

        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(target, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    return target


def output_dir_for(image_dir: Path, prefix: str, output_root: Path | None) -> Path:
    name = f'{prefix}{OUTPUT_SUFFIX}'
    return (output_root / name) if output_root else (image_dir.parent / name)


# ==================== 批量处理 ====================
def run_batch(root: Path, output_root: Optional[Path], template: Optional[Path] = None,
              overwrite: bool = True, prefix: Optional[str] = None,
              log: Optional[Callable[[str], None]] = None,
              progress: Optional[Callable[[int, int, str], None]] = None,
              on_state: Optional[Callable[[str, dict], None]] = None,
              stop: Optional[Callable[[], bool]] = None):
    """遍历 root 下的图片目录并逐个生成附证 PDF。

    log(text)                       输出日志
    progress(done, total, text)     整体进度回调
    on_state(prefix, state)         单个目录的状态回调，state 字段见 _emit
    stop()                          返回 True 时中止
    返回 (成功数, 跳过数, 失败数, 输出目录列表)
    """
    if log is None:
        log = print

    template = Path(template) if template else TEMPLATE
    if not template.is_file():
        raise FileNotFoundError(f'模板不存在：{template}')
    if not FONT_FILE.is_file():
        raise FileNotFoundError(f'缺少字体文件：{FONT_FILE}')

    if prefix:
        batches = [(root, prefix)] if collect_images(root) else []
    else:
        batches = [(d, prefix_from_dir(d.name)) for d in find_image_dirs(root)]

    if not batches:
        log(f'未在 {root} 下找到含图片的子目录')
        return 0, 0, 0, []

    total = sum(len(collect_images(d)) for d, _ in batches)
    log(f'模板：{template.name}  共 {len(batches)} 个图片目录 / {total} 张图片')
    log('-' * 64)

    done = ok = skipped = failed = 0
    outputs = []

    def emit(batch_prefix, state, batch_total, batch_done, batch_ok,
             batch_skip, batch_fail, current=''):
        """把单个目录的处理状态回传给界面。"""
        if on_state is None:
            return
        on_state(batch_prefix, {
            'state': state,
            'total': batch_total,
            'done': batch_done,
            'ok': batch_ok,
            'skipped': batch_skip,
            'failed': batch_fail,
            'current': current,
        })

    for image_dir, batch_prefix in batches:
        images = collect_images(image_dir)
        target_dir = output_dir_for(image_dir, batch_prefix, output_root)
        outputs.append(target_dir)

        batch_total = len(images)
        batch_done = batch_ok = batch_skip = batch_fail = 0
        emit(batch_prefix, 'running', batch_total, 0, 0, 0, 0)
        log(f'[{batch_prefix}] {image_dir.name}  ->  {target_dir.name}（{batch_total} 张）')

        for image in images:
            if stop and stop():
                emit(batch_prefix, 'stopped', batch_total, batch_done, batch_ok,
                     batch_skip, batch_fail, '已停止')
                log('已停止')
                return ok, skipped, failed, outputs

            nums = re.findall(r'\d+', image.stem)
            if not nums:
                log(f'   跳过（文件名无编号）：{image.name}')
                skipped += 1
                done += 1
                batch_skip += 1
                batch_done += 1
                emit(batch_prefix, 'running', batch_total, batch_done, batch_ok,
                     batch_skip, batch_fail, image.name)
                if progress:
                    progress(done, total, image.name)
                continue

            number = int(nums[0])
            target = target_dir / f'{batch_prefix}-{number:03d}.pdf'
            if target.exists() and not overwrite:
                log(f'   已存在，跳过：{target.name}')
                skipped += 1
                done += 1
                batch_skip += 1
                batch_done += 1
                emit(batch_prefix, 'running', batch_total, batch_done, batch_ok,
                     batch_skip, batch_fail, image.name)
                if progress:
                    progress(done, total, image.name)
                continue

            try:
                build_page(template, image, target, number, batch_prefix)
                size_kb = target.stat().st_size / 1024
                log(f'   {image.name:<14} -> {target.name}  ({size_kb:.0f} KB)')
                ok += 1
                batch_ok += 1
            except Exception as exc:
                log(f'   {image.name} 生成失败：{exc}')
                failed += 1
                batch_fail += 1
            done += 1
            batch_done += 1
            emit(batch_prefix, 'running', batch_total, batch_done, batch_ok,
                 batch_skip, batch_fail, image.name)
            if progress:
                progress(done, total, image.name)

        emit(batch_prefix, 'done', batch_total, batch_done, batch_ok,
             batch_skip, batch_fail)

    log('-' * 64)
    log(f'完成：成功 {ok}，跳过 {skipped}，失败 {failed}')
    return ok, skipped, failed, outputs


# ==================== GUI ====================
# 配色
BG = '#f4f6f9'
CARD = '#ffffff'
BORDER = '#e4e9f0'
FG = '#1f2937'
MUTED = '#6b7280'
ACCENT = '#2563eb'
ACCENT_HOVER = '#1d4ed8'
SUCCESS = '#16a34a'
DANGER = '#dc2626'
LOG_BG = '#0f172a'
LOG_FG = '#cbd5e1'
FONT_UI = '微软雅黑'


def _enable_dpi():
    """开启高 DPI 感知，界面在高分屏上更清晰。返回缩放比例。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return max(1.0, dpi / 96.0)
    except (AttributeError, OSError):
        return 1.0


def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    scale = _enable_dpi()

    def px(value: float) -> int:
        return int(round(value * scale))

    def card(parent, title: str):
        """白色卡片容器，返回 (卡片, 内容区)。"""
        outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill='both', expand=True, padx=px(16), pady=px(12))
        if title:
            head = tk.Frame(inner, bg=CARD)
            head.pack(fill='x', pady=(0, px(10)))
            tk.Frame(head, bg=ACCENT, width=px(3), height=px(14)).pack(side='left', padx=(0, px(8)))
            tk.Label(head, text=title, bg=CARD, fg=FG,
                     font=(FONT_UI, 10, 'bold')).pack(side='left')
        return outer, inner

    class ToggleSwitch(tk.Canvas):
        """自绘开关，替代系统复选框，观感更统一。"""

        def __init__(self, parent, variable, width=44, height=22):
            super().__init__(parent, width=px(width), height=px(height), bg=BG,
                             highlightthickness=0, bd=0, cursor='hand2')
            self.var = variable
            self.w = px(width)
            self.h = px(height)
            self.bind('<Button-1>', lambda _e: self.toggle())
            self.var.trace_add('write', lambda *_: self._draw())
            self._draw()

        def toggle(self):
            self.var.set(not self.var.get())

        def _draw(self):
            self.delete('all')
            on = bool(self.var.get())
            color = ACCENT if on else '#cbd5e1'
            radius = self.h / 2
            self.create_oval(0, 0, self.h, self.h, fill=color, outline=color)
            self.create_oval(self.w - self.h, 0, self.w, self.h,
                             fill=color, outline=color)
            self.create_rectangle(radius, 0, self.w - radius, self.h,
                                  fill=color, outline=color)
            knob = self.h - px(6)
            center = (self.w - radius) if on else radius
            self.create_oval(center - knob / 2, (self.h - knob) / 2,
                             center + knob / 2, (self.h + knob) / 2,
                             fill='#ffffff', outline='#ffffff')

    class App:
        def __init__(self, root):
            self.root = root
            self.root.title('艺术水平考级证书附件 · 批量生成')
            self.root.configure(bg=BG)
            self.root.geometry(f'{px(1080)}x{px(820)}')
            self.root.minsize(px(960), px(720))

            self.messages = queue.Queue()
            self.worker = None
            self.stop_event = threading.Event()
            self._last_output = None
            self.row_ids = {}

            self.root_var = tk.StringVar(value=str(IMAGE_ROOT))
            self.out_var = tk.StringVar(value=str(IMAGE_ROOT))
            self.overwrite_var = tk.BooleanVar(value=True)
            self.status_var = tk.StringVar(value='就绪')
            self.pct_var = tk.StringVar(value='0%')
            self.summary_var = tk.StringVar(value='尚未扫描')

            self._init_style()
            self._build()
            self._poll()
            self._scan(silent=True)

        # ---------- 样式 ----------
        def _init_style(self):
            style = ttk.Style()
            try:
                style.theme_use('clam')
            except tk.TclError:
                pass

            style.configure('.', font=(FONT_UI, 9), background=BG, foreground=FG)

            # 输入框
            style.configure('Modern.TEntry', fieldbackground=CARD, foreground=FG,
                            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                            insertcolor=FG, padding=(8, 7), relief='flat')
            style.map('Modern.TEntry',
                      bordercolor=[('focus', ACCENT)],
                      lightcolor=[('focus', ACCENT)],
                      darkcolor=[('focus', ACCENT)])

            # 主按钮
            style.configure('Accent.TButton', background=ACCENT, foreground='#ffffff',
                            bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                            relief='flat', padding=(18, 9), font=(FONT_UI, 9, 'bold'))
            style.map('Accent.TButton',
                      background=[('active', ACCENT_HOVER), ('pressed', ACCENT_HOVER),
                                  ('disabled', '#a9bce0')],
                      foreground=[('disabled', '#eef2ff')],
                      bordercolor=[('disabled', '#a9bce0')])

            # 次要按钮：有边框、无填充色
            style.configure('Ghost.TButton', background=CARD, foreground=FG,
                            bordercolor='#cbd5e1', lightcolor=CARD, darkcolor=CARD,
                            borderwidth=1, relief='solid', padding=(14, 8),
                            font=(FONT_UI, 9))
            style.map('Ghost.TButton',
                      background=[('active', '#eef4fd'), ('pressed', '#e2ebf9'),
                                  ('disabled', CARD)],
                      foreground=[('disabled', '#a6adba')],
                      bordercolor=[('active', ACCENT), ('pressed', ACCENT),
                                   ('disabled', '#e2e8f0')],
                      lightcolor=[('active', '#eef4fd'), ('pressed', '#e2ebf9')],
                      darkcolor=[('active', '#eef4fd'), ('pressed', '#e2ebf9')])

            # 浏览按钮：更紧凑的描边按钮
            style.configure('Browse.TButton', background=CARD, foreground=ACCENT,
                            bordercolor='#cbd5e1', lightcolor=CARD, darkcolor=CARD,
                            borderwidth=1, relief='solid', padding=(12, 7),
                            font=(FONT_UI, 9))
            style.map('Browse.TButton',
                      background=[('active', '#eef4fd'), ('pressed', '#e2ebf9')],
                      foreground=[('active', ACCENT_HOVER), ('pressed', ACCENT_HOVER)],
                      bordercolor=[('active', ACCENT), ('pressed', ACCENT)],
                      lightcolor=[('active', '#eef4fd'), ('pressed', '#e2ebf9')],
                      darkcolor=[('active', '#eef4fd'), ('pressed', '#e2ebf9')])

            style.configure('Modern.TCheckbutton', background=CARD, foreground=FG,
                            font=(FONT_UI, 9))
            style.map('Modern.TCheckbutton', background=[('active', CARD)])

            # 表格
            style.configure('Modern.Treeview', background=CARD, fieldbackground=CARD,
                            foreground=FG, rowheight=px(26), borderwidth=0,
                            font=(FONT_UI, 9))
            style.configure('Modern.Treeview.Heading', background='#f8fafc',
                            foreground=MUTED, relief='flat',
                            font=(FONT_UI, 9, 'bold'), padding=(px(8), px(6)))
            style.map('Modern.Treeview.Heading', background=[('active', '#eef2f7')])
            style.map('Modern.Treeview',
                      background=[('selected', '#dbeafe')],
                      foreground=[('selected', ACCENT_HOVER)])

            # 进度条
            style.configure('Accent.Horizontal.TProgressbar', troughcolor='#e6ebf3',
                            background=ACCENT, bordercolor='#e6ebf3',
                            lightcolor=ACCENT, darkcolor=ACCENT,
                            thickness=px(8), borderwidth=0)

            style.configure('Vertical.TScrollbar', background='#d8dfe9',
                            troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                            relief='flat')
            style.map('Vertical.TScrollbar', background=[('active', '#c3ccd9')])
            style.configure('Horizontal.TScrollbar', background='#d8dfe9',
                            troughcolor=LOG_BG, bordercolor=LOG_BG,
                            arrowcolor='#94a3b8', relief='flat')

        # ---------- 界面 ----------
        def _build(self):
            # 标题只在系统标题栏显示，界面内不再重复

            # 底部状态栏（先 pack，保证不被内容挤出窗口）
            status = tk.Frame(self.root, bg='#eaeef5', height=px(28))
            status.pack(fill='x', side='bottom')
            status.pack_propagate(False)
            tk.Label(status, textvariable=self.status_var, bg='#eaeef5', fg=MUTED,
                     font=(FONT_UI, 9), anchor='w').pack(side='left', padx=px(16))
            tk.Label(status, text='A4 · 5 寸照片', bg='#eaeef5',
                     fg='#9aa3af', font=(FONT_UI, 8)).pack(side='right', padx=(0, px(14)))
            tk.Label(status, text=f'日志：{log_file_path()}', bg='#eaeef5',
                     fg='#9aa3af', font=(FONT_UI, 8)).pack(side='right', padx=(0, px(14)))

            body = tk.Frame(self.root, bg=BG)
            body.pack(fill='both', expand=True, padx=px(16), pady=px(16))
            body.columnconfigure(0, weight=1)
            body.rowconfigure(3, weight=3)
            body.rowconfigure(4, weight=2)

            # ① 目录设置
            paths_card, paths = card(body, '① 选择目录')
            paths_card.grid(row=0, column=0, sticky='ew')

            grid = tk.Frame(paths, bg=CARD)
            grid.pack(fill='x')
            grid.columnconfigure(1, weight=1)

            tk.Label(grid, text='图片根目录', bg=CARD, fg=MUTED,
                     font=(FONT_UI, 9)).grid(row=0, column=0, sticky='w',
                                             padx=(0, px(12)), pady=px(4))
            ttk.Entry(grid, textvariable=self.root_var, style='Modern.TEntry').grid(
                row=0, column=1, sticky='we', pady=px(4))
            ttk.Button(grid, text='浏览…', style='Browse.TButton',
                       command=self._pick_root).grid(
                row=0, column=2, padx=(px(8), 0), pady=px(4))

            tk.Label(grid, text='输出根目录', bg=CARD, fg=MUTED,
                     font=(FONT_UI, 9)).grid(row=1, column=0, sticky='w',
                                             padx=(0, px(12)), pady=px(4))
            self.out_entry = ttk.Entry(grid, textvariable=self.out_var,
                                       style='Modern.TEntry')
            self.out_entry.grid(row=1, column=1, sticky='we', pady=px(4))
            ttk.Button(grid, text='浏览…', style='Browse.TButton',
                       command=self._pick_out).grid(
                row=1, column=2, padx=(px(8), 0), pady=px(4))

            # ② 操作区
            actions = tk.Frame(body, bg=BG)
            actions.grid(row=1, column=0, sticky='ew', pady=(px(12), px(8)))

            self.btn_start = ttk.Button(actions, text='开始生成', style='Accent.TButton',
                                        command=self._start)
            self.btn_start.pack(side='left')
            self.btn_stop = ttk.Button(actions, text='停止', style='Ghost.TButton',
                                       command=self._stop, state='disabled')
            self.btn_stop.pack(side='left', padx=(px(8), 0))
            ttk.Button(actions, text='扫描目录', style='Ghost.TButton',
                       command=self._scan).pack(side='left', padx=(px(8), 0))
            ttk.Button(actions, text='打开输出目录', style='Ghost.TButton',
                       command=self._open_out).pack(side='left', padx=(px(8), 0))
            ttk.Button(actions, text='打开日志', style='Ghost.TButton',
                       command=self._open_log).pack(side='left', padx=(px(8), 0))

            overwrite_box = tk.Frame(actions, bg=BG, cursor='hand2')
            overwrite_box.pack(side='right')
            tk.Label(overwrite_box, text='覆盖已存在的 PDF', bg=BG, fg=FG,
                     font=(FONT_UI, 9), cursor='hand2').pack(side='left', padx=(0, px(8)))
            self.switch = ToggleSwitch(overwrite_box, self.overwrite_var)
            self.switch.pack(side='left')
            for widget in (overwrite_box, *overwrite_box.winfo_children()):
                widget.bind('<Button-1>', lambda _e: self.switch.toggle())

            # 进度
            prog_row = tk.Frame(body, bg=BG)
            prog_row.grid(row=2, column=0, sticky='ew', pady=(0, px(12)))
            self.progress = ttk.Progressbar(prog_row, mode='determinate', maximum=100,
                                            style='Accent.Horizontal.TProgressbar')
            self.progress.pack(side='left', fill='x', expand=True)
            tk.Label(prog_row, textvariable=self.pct_var, bg=BG, fg=ACCENT,
                     font=(FONT_UI, 9, 'bold'), width=6,
                     anchor='e').pack(side='left', padx=(px(10), 0))

            # ③ 待处理清单
            list_card, list_inner = card(body, '② 待处理清单')
            list_card.grid(row=3, column=0, sticky='nsew')

            tk.Label(list_inner, textvariable=self.summary_var, bg=CARD, fg='#9aa3af',
                     font=(FONT_UI, 8)).pack(anchor='e', pady=(0, px(6)))

            tree_wrap = tk.Frame(list_inner, bg=CARD)
            tree_wrap.pack(fill='both', expand=True)

            columns = ('dir', 'prefix', 'count', 'out', 'state')
            self.tree = ttk.Treeview(tree_wrap, columns=columns, show='headings',
                                     style='Modern.Treeview', height=5)
            headings = {'dir': ('图片目录', 280), 'prefix': ('编号前缀', 120),
                        'count': ('图片数', 70), 'out': ('输出目录', 260),
                        'state': ('状态', 130)}
            for key, (text, width) in headings.items():
                self.tree.heading(key, text=text, anchor='w')
                self.tree.column(key, width=px(width), anchor='w',
                                 stretch=(key in ('dir', 'out')))
            self.tree.column('count', anchor='center')
            self.tree.column('state', anchor='w')
            self.tree.pack(side='left', fill='both', expand=True)

            tree_scroll = ttk.Scrollbar(tree_wrap, orient='vertical',
                                        style='Vertical.TScrollbar',
                                        command=self.tree.yview)
            self.tree.configure(yscrollcommand=tree_scroll.set)
            tree_scroll.pack(side='right', fill='y')
            self.tree.tag_configure('odd', background='#fbfcfe')
            self.tree.tag_configure('running', foreground=ACCENT)
            self.tree.tag_configure('done', foreground=SUCCESS)
            self.tree.tag_configure('failed', foreground=DANGER)
            self.tree.tag_configure('stopped', foreground=MUTED)

            # ④ 运行日志
            log_card, log_inner = card(body, '③ 运行日志')
            log_card.grid(row=4, column=0, sticky='nsew', pady=(px(12), 0))

            log_wrap = tk.Frame(log_inner, bg=LOG_BG)
            log_wrap.pack(fill='both', expand=True)

            self.log_text = tk.Text(log_wrap, wrap='none', height=6, bd=0,
                                    font=('Consolas', 9), background=LOG_BG,
                                    foreground=LOG_FG, insertbackground=LOG_FG,
                                    padx=px(12), pady=px(10), relief='flat',
                                    selectbackground='#334155')
            yscroll = ttk.Scrollbar(log_wrap, orient='vertical',
                                    style='Vertical.TScrollbar',
                                    command=self.log_text.yview)
            xscroll = ttk.Scrollbar(log_wrap, orient='horizontal',
                                    style='Horizontal.TScrollbar',
                                    command=self.log_text.xview)
            self.log_text.configure(yscrollcommand=yscroll.set,
                                    xscrollcommand=xscroll.set)
            self.log_text.grid(row=0, column=0, sticky='nsew')
            yscroll.grid(row=0, column=1, sticky='ns')
            xscroll.grid(row=1, column=0, sticky='ew')
            log_wrap.rowconfigure(0, weight=1)
            log_wrap.columnconfigure(0, weight=1)

            self.log_text.tag_configure('ok', foreground='#4ade80')
            self.log_text.tag_configure('err', foreground='#f87171')
            self.log_text.tag_configure('dim', foreground='#64748b')
            self.log_text.tag_configure('info', foreground='#7dd3fc')

        # ---------- 选择路径 ----------
        def _pick_root(self):
            path = filedialog.askdirectory(title='选择图片根目录')
            if path:
                previous = self.root_var.get().strip()
                follow = (not self.out_var.get().strip()
                          or self.out_var.get().strip() == previous)
                self.root_var.set(path)
                if follow:
                    self.out_var.set(path)
                self._scan(silent=True)

        def _pick_out(self):
            path = filedialog.askdirectory(title='选择输出根目录')
            if path:
                self.out_var.set(path)
                self._scan(silent=True)

        # ---------- 日志 ----------
        def _log(self, text):
            self.messages.put(('log', text))

        def _open_log(self):
            path = log_file_path()
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()
            try:
                os.startfile(str(path))
            except OSError as exc:
                messagebox.showerror('打开日志失败', str(exc))

        def _clear_log(self):
            self.log_text.delete('1.0', 'end')

        def _write_log(self, text):
            """写入界面日志（按内容着色），同时追加到当日日志文件。"""
            tag = ''
            if '失败' in text or '错误' in text or '无效' in text:
                tag = 'err'
            elif '完成：' in text or '->' in text:
                tag = 'ok'
            elif text.startswith('-') or text.startswith('模板') or text.startswith('共'):
                tag = 'dim'
            elif text.startswith('未'):
                tag = 'info'
            self.log_text.insert('end', text + '\n', tag)
            self.log_text.see('end')
            write_log_file(text)

        def _poll(self):
            try:
                while True:
                    kind, payload = self.messages.get_nowait()
                    if kind == 'log':
                        self._write_log(payload)
                    elif kind == 'progress':
                        done, total, text = payload
                        pct = (done / total * 100) if total else 0
                        self.progress['value'] = pct
                        self.pct_var.set(f'{pct:.0f}%')
                        self.status_var.set(f'正在生成 {done}/{total} · {text}')
                    elif kind == 'state':
                        prefix, state = payload
                        self._update_state(prefix, state)
                    elif kind == 'status':
                        self.status_var.set(payload)
                    elif kind == 'done':
                        self._finish(payload)
            except queue.Empty:
                pass
            self.root.after(80, self._poll)

        # ---------- 清单状态 ----------
        def _reset_states(self):
            """开始生成前把每一行状态重置为“等待”。"""
            for prefix, iid in self.row_ids.items():
                if not self.tree.exists(iid):
                    continue
                values = list(self.tree.item(iid, 'values'))
                values[-1] = '等待'
                self.tree.item(iid, values=values,
                               tags=('odd',) if self._is_odd(iid) else ())

        def _is_odd(self, iid) -> bool:
            children = self.tree.get_children()
            try:
                return children.index(iid) % 2 == 1
            except ValueError:
                return False

        def _update_state(self, prefix, state):
            """把单个目录的处理进度同步到清单行。"""
            iid = self.row_ids.get(prefix)
            if not iid or not self.tree.exists(iid):
                return

            kind = state.get('state', 'running')
            total = state.get('total', 0)
            done = state.get('done', 0)
            ok = state.get('ok', 0)
            skipped = state.get('skipped', 0)
            failed = state.get('failed', 0)

            if kind == 'running':
                text = f'生成中 {done}/{total}'
            elif kind == 'done':
                text = f'完成 {ok}'
                if skipped:
                    text += f' · 跳过 {skipped}'
                if failed:
                    text += f' · 失败 {failed}'
            elif kind == 'stopped':
                text = f'已停止 {done}/{total}'
            else:
                text = kind

            values = list(self.tree.item(iid, 'values'))
            if len(values) < 5:
                values = values + [''] * (5 - len(values))
            values[-1] = text

            tag = 'odd' if self._is_odd(iid) else ''
            if failed:
                tag = 'failed'
            elif kind == 'done':
                tag = 'done'
            elif kind == 'stopped':
                tag = 'stopped'
            elif kind == 'running':
                tag = 'running'
            self.tree.item(iid, values=values, tags=(tag,) if tag else ())
            self.tree.see(iid)

        # ---------- 扫描 ----------
        def _scan(self, silent=False):
            for item in self.tree.get_children():
                self.tree.delete(item)
            if not silent:
                self._clear_log()

            root = Path(self.root_var.get().strip())
            try:
                dirs = find_image_dirs(root)
            except (OSError, ValueError) as exc:
                if not silent:
                    messagebox.showerror('扫描失败', str(exc))
                self.summary_var.set('扫描失败')
                return

            if not dirs:
                self.summary_var.set('未找到含图片的子目录')
                if not silent:
                    self._write_log(f'未在 {root} 下找到含图片的子目录')
                return

            out_text = self.out_var.get().strip()
            out_root = Path(out_text) if out_text else root
            self.row_ids = {}
            total = 0
            for index, d in enumerate(dirs):
                prefix = prefix_from_dir(d.name)
                count = len(collect_images(d))
                total += count
                target = output_dir_for(d, prefix, out_root)
                iid = self.tree.insert(
                    '', 'end',
                    values=(d.name, prefix, count, target.name, '等待'),
                    tags=('odd',) if index % 2 else ())
                self.row_ids[prefix] = iid
                if not silent:
                    self._write_log(f'{d.name}  ->  {target.name}   {count} 张   [前缀 {prefix}]')

            self.summary_var.set(f'{len(dirs)} 个目录 · {total} 张图片 · '
                                 f'输出到 {out_root}')
            if not silent:
                self._write_log('-' * 64)
                self._write_log(f'共 {len(dirs)} 个图片目录，{total} 张图片')

        # ---------- 运行 ----------
        def _start(self):
            if self.worker and self.worker.is_alive():
                return
            root = Path(self.root_var.get().strip())
            template = TEMPLATE
            out_text = self.out_var.get().strip()
            out_root = Path(out_text) if out_text else root

            if not template.is_file():
                messagebox.showerror('模板缺失', f'内置模板不可用：\n{template}')
                return
            if not root.is_dir():
                messagebox.showerror('路径无效', f'找不到图片根目录：\n{root}')
                return
            if not out_root.is_dir():
                try:
                    out_root.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    messagebox.showerror('输出目录无效', str(exc))
                    return

            self.stop_event.clear()
            self.btn_start.configure(state='disabled')
            self.btn_stop.configure(state='normal')
            self.progress['value'] = 0
            self.pct_var.set('0%')
            self.status_var.set('正在生成…')
            self._clear_log()
            self._reset_states()

            overwrite = self.overwrite_var.get()

            def work():
                try:
                    ok, skipped, failed, outputs = run_batch(
                        root, out_root, template, overwrite=overwrite,
                        log=self._log,
                        progress=lambda d, t, x: self.messages.put(('progress', (d, t, x))),
                        on_state=lambda p, st: self.messages.put(('state', (p, st))),
                        stop=self.stop_event.is_set,
                    )
                    self.messages.put(('done', (ok, skipped, failed, outputs)))
                except Exception as exc:
                    self._log(f'处理失败：{exc}')
                    self.messages.put(('done', (0, 0, 0, [], str(exc))))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def _finish(self, payload):
            ok, skipped, failed = payload[0], payload[1], payload[2]
            outputs = payload[3] if len(payload) > 3 else []
            error = payload[4] if len(payload) > 4 else ''
            self.btn_start.configure(state='normal')
            self.btn_stop.configure(state='disabled')
            self.progress['value'] = 100 if ok else 0
            self.pct_var.set('100%' if ok else '0%')
            if error:
                self.status_var.set('失败')
                messagebox.showerror('处理失败', error)
            elif self.stop_event.is_set():
                self.status_var.set(f'已停止 · 成功 {ok} · 跳过 {skipped} · 失败 {failed}')
            else:
                self.status_var.set(f'完成 · 成功 {ok} · 跳过 {skipped} · 失败 {failed}')
            if outputs:
                self._last_output = outputs[-1]

        def _stop(self):
            self.stop_event.set()
            self.status_var.set('正在停止…')

        def _open_out(self):
            target = None
            if self._last_output and Path(self._last_output).is_dir():
                target = Path(self._last_output)
            else:
                out_text = self.out_var.get().strip()
                root_text = self.root_var.get().strip()
                for candidate in (out_text, root_text):
                    if candidate and Path(candidate).is_dir():
                        target = Path(candidate)
                        break
            if not target:
                messagebox.showinfo('提示', '暂无可打开的输出目录')
                return
            try:
                os.startfile(str(target))
            except OSError as exc:
                messagebox.showerror('打开失败', str(exc))

    root = tk.Tk()
    App(root)
    root.mainloop()


def main():
    launch_gui()
    return 0


if __name__ == '__main__':
    sys.exit(main())
