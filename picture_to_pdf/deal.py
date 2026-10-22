# coding='utf-8'
"""艺术水平考级证书附件 —— 作品照片批量贴图（GUI 版）

功能：
  1. 选择空白模板 PDF（默认使用本目录下的 空白副证图片.pdf）。
  2. 选择图片根目录，程序会遍历其下所有“图片目录”（直接含图片的子目录）。
  3. 每个图片目录按其名称推断作品编号前缀（如 029-021-011图片 -> 029-021-011），
     在同级生成 “029-021-011附证” 目录，并逐张图片生成 PDF：
         - 照片等比缩放后居中放入照片区，不拉伸；
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

# ==================== 版面坐标（单位 pt，页面 595.276 × 841.89） ====================
PHOTO_MAX_W = 316.0      # 照片区最大宽度
PHOTO_MAX_H = 300.0      # 照片区最大高度
PHOTO_TOP = 246.6        # 照片区顶边距页顶（与范本一致）

NO_ORIGIN = (224.43, 690.65)   # “作品编号（NO）：”后文字的基线起点
NO_FONT_SIZE = 12.0

MARK_FONT_SIZE = 12.0    # 照片右下角标号字号
MARK_RIGHT_PAD = 0.10    # 标号距照片右边 = 照片宽度 × 该比例
MARK_BOTTOM_PAD = 12.0   # 标号距照片底边（pt）

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


def photo_area(page_width: float):
    """照片区：水平居中，顶边固定。"""
    x0 = (page_width - PHOTO_MAX_W) / 2
    return fitz.Rect(x0, PHOTO_TOP, x0 + PHOTO_MAX_W, PHOTO_TOP + PHOTO_MAX_H)


def fit_rect(area, width: int, height: int):
    """等比缩放并居中，保证不拉伸变形。"""
    if width <= 0 or height <= 0:
        return area
    scale = min(area.width / width, area.height / height)
    draw_w, draw_h = width * scale, height * scale
    x0 = area.x0 + (area.width - draw_w) / 2
    y0 = area.y0 + (area.height - draw_h) / 2
    return fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h)


# ==================== 生成单页 ====================
def build_page(template: Path, image: Path, target: Path, number: int, prefix: str):
    """把一张图片贴到模板上并保存为单页 PDF。"""
    label = f'{number:03d}'
    doc = fitz.open(template)
    try:
        page = doc[0]
        width, height = image_size(image)
        rect = fit_rect(photo_area(page.rect.width), width, height)

        # 照片覆盖在模板“考级作品照片”占位文字之上
        page.insert_image(rect, filename=str(image), keep_proportion=True)

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
              stop: Optional[Callable[[], bool]] = None):
    """遍历 root 下的图片目录并逐个生成附证 PDF。

    log(text)                       输出日志
    progress(done, total, text)     进度回调
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

    for image_dir, batch_prefix in batches:
        images = collect_images(image_dir)
        target_dir = output_dir_for(image_dir, batch_prefix, output_root)
        outputs.append(target_dir)
        log(f'[{batch_prefix}] {image_dir.name}  ->  {target_dir.name}（{len(images)} 张）')

        for image in images:
            if stop and stop():
                log('已停止')
                return ok, skipped, failed, outputs
            nums = re.findall(r'\d+', image.stem)
            if not nums:
                log(f'   跳过（文件名无编号）：{image.name}')
                skipped += 1
                done += 1
                continue

            number = int(nums[0])
            target = target_dir / f'{batch_prefix}-{number:03d}.pdf'
            if target.exists() and not overwrite:
                log(f'   已存在，跳过：{target.name}')
                skipped += 1
                done += 1
                if progress:
                    progress(done, total, image.name)
                continue

            try:
                build_page(template, image, target, number, batch_prefix)
                size_kb = target.stat().st_size / 1024
                log(f'   {image.name:<14} -> {target.name}  ({size_kb:.0f} KB)')
                ok += 1
            except Exception as exc:
                log(f'   {image.name} 生成失败：{exc}')
                failed += 1
            done += 1
            if progress:
                progress(done, total, image.name)

    log('-' * 64)
    log(f'完成：成功 {ok}，跳过 {skipped}，失败 {failed}')
    return ok, skipped, failed, outputs


# ==================== GUI ====================
def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App:
        def __init__(self, root):
            self.root = root
            self.root.title('艺术水平考级证书附件 - 批量生成')
            self.root.geometry('980x680')
            self.root.minsize(860, 600)

            self.messages = queue.Queue()
            self.worker = None
            self.stop_event = threading.Event()

            self.root_var = tk.StringVar(value=str(IMAGE_ROOT))
            self.out_var = tk.StringVar(value='')
            self.overwrite_var = tk.BooleanVar(value=True)
            self.status_var = tk.StringVar(value='就绪')

            self._build()
            self._poll()

        # ---------- 界面 ----------
        def _build(self):
            paths = ttk.LabelFrame(self.root, text='路径设置')
            paths.pack(fill='x', padx=10, pady=(10, 6))

            ttk.Label(paths, text='图片根目录').grid(
                row=0, column=0, sticky='w', padx=8, pady=4)
            ttk.Entry(paths, textvariable=self.root_var).grid(
                row=0, column=1, sticky='we', padx=8, pady=4)
            ttk.Button(paths, text='浏览…', command=self._pick_root).grid(
                row=0, column=2, padx=8, pady=4)

            ttk.Label(paths, text='输出根目录').grid(
                row=1, column=0, sticky='w', padx=8, pady=4)
            ttk.Entry(paths, textvariable=self.out_var).grid(
                row=1, column=1, sticky='we', padx=8, pady=4)
            ttk.Button(paths, text='浏览…', command=self._pick_out).grid(
                row=1, column=2, padx=8, pady=4)
            ttk.Label(paths, text='留空则输出到各图片目录同级',
                      foreground='#777').grid(row=2, column=1, sticky='w', padx=8)

            paths.columnconfigure(1, weight=1)

            bar = ttk.Frame(self.root)
            bar.pack(fill='x', padx=10)
            ttk.Checkbutton(bar, text='覆盖已存在的 PDF',
                            variable=self.overwrite_var).pack(side='left')
            ttk.Button(bar, text='扫描目录', command=self._scan).pack(side='right', padx=4)
            ttk.Button(bar, text='打开输出目录', command=self._open_out).pack(side='right', padx=4)
            ttk.Button(bar, text='打开日志', command=self._open_log).pack(side='right', padx=4)

            actions = ttk.Frame(self.root)
            actions.pack(fill='x', padx=10, pady=6)
            self.btn_start = ttk.Button(actions, text='开始生成', command=self._start)
            self.btn_start.pack(side='left')
            self.btn_stop = ttk.Button(actions, text='停止', command=self._stop, state='disabled')
            self.btn_stop.pack(side='left', padx=6)
            ttk.Button(actions, text='清空日志', command=self._clear_log).pack(side='left')
            self.log_path_label = ttk.Label(actions, text=f'日志：{log_file_path()}',
                                            foreground='#777')
            self.log_path_label.pack(side='right', padx=6)

            self.progress = ttk.Progressbar(self.root, mode='determinate', maximum=100)
            self.progress.pack(fill='x', padx=10, pady=(0, 6))

            log_frame = ttk.LabelFrame(self.root, text='运行日志')
            log_frame.pack(fill='both', expand=True, padx=10, pady=(0, 6))
            self.log_text = tk.Text(log_frame, wrap='none', height=20,
                                    font=('Consolas', 9), background='#1e1e1e',
                                    foreground='#dcdcdc', insertbackground='#dcdcdc')
            yscroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
            xscroll = ttk.Scrollbar(log_frame, orient='horizontal', command=self.log_text.xview)
            self.log_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            self.log_text.grid(row=0, column=0, sticky='nsew')
            yscroll.grid(row=0, column=1, sticky='ns')
            xscroll.grid(row=1, column=0, sticky='ew')
            log_frame.rowconfigure(0, weight=1)
            log_frame.columnconfigure(0, weight=1)

            ttk.Label(self.root, textvariable=self.status_var,
                      anchor='w', relief='sunken').pack(fill='x', side='bottom')

        # ---------- 选择路径 ----------
        def _pick_root(self):
            path = filedialog.askdirectory(title='选择图片根目录')
            if path:
                self.root_var.set(path)

        def _pick_out(self):
            path = filedialog.askdirectory(title='选择输出根目录')
            if path:
                self.out_var.set(path)

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
            """写入界面日志，同时追加到当日日志文件。"""
            self.log_text.insert('end', text + '\n')
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
                        self.progress['value'] = (done / total * 100) if total else 0
                        self.status_var.set(f'{done}/{total}  {text}')
                    elif kind == 'status':
                        self.status_var.set(payload)
                    elif kind == 'done':
                        self._finish(payload)
            except queue.Empty:
                pass
            self.root.after(80, self._poll)

        # ---------- 扫描 ----------
        def _scan(self):
            self._clear_log()
            root = Path(self.root_var.get().strip())
            try:
                dirs = find_image_dirs(root)
            except Exception as exc:
                messagebox.showerror('扫描失败', str(exc))
                return
            if not dirs:
                self._write_log(f'未在 {root} 下找到含图片的子目录')
                return
            out_root = Path(self.out_var.get().strip()) if self.out_var.get().strip() else None
            total = 0
            for d in dirs:
                prefix = prefix_from_dir(d.name)
                count = len(collect_images(d))
                total += count
                target = output_dir_for(d, prefix, out_root)
                self._write_log(f'{d.name}  ->  {target.name}   {count} 张   [前缀 {prefix}]')
            self._write_log('-' * 64)
            self._write_log(f'共 {len(dirs)} 个图片目录，{total} 张图片')

        # ---------- 运行 ----------
        def _start(self):
            if self.worker and self.worker.is_alive():
                return
            root = Path(self.root_var.get().strip())
            template = TEMPLATE
            out_text = self.out_var.get().strip()
            out_root = Path(out_text) if out_text else None

            if not template.is_file():
                messagebox.showerror('模板缺失', f'内置模板不可用：\n{template}')
                return
            if not root.is_dir():
                messagebox.showerror('路径无效', f'找不到图片根目录：\n{root}')
                return
            if out_root and not out_root.is_dir():
                if not messagebox.askyesno('输出目录不存在', f'{out_root}\n不存在，是否创建？'):
                    return
                try:
                    out_root.mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    messagebox.showerror('创建失败', str(exc))
                    return

            self.stop_event.clear()
            self.btn_start.configure(state='disabled')
            self.btn_stop.configure(state='normal')
            self.progress['value'] = 0
            self.status_var.set('正在生成…')
            self._clear_log()

            overwrite = self.overwrite_var.get()

            def work():
                try:
                    ok, skipped, failed, outputs = run_batch(
                        root, out_root, template, overwrite=overwrite,
                        log=self._log, progress=lambda d, t, x: self.messages.put(('progress', (d, t, x))),
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
            if error:
                self.status_var.set('失败')
                messagebox.showerror('处理失败', error)
            elif self.stop_event.is_set():
                self.status_var.set(f'已停止：成功 {ok}，跳过 {skipped}，失败 {failed}')
            else:
                self.status_var.set(f'完成：成功 {ok}，跳过 {skipped}，失败 {failed}')
            if outputs:
                self._last_output = outputs[-1]

        def _stop(self):
            self.stop_event.set()
            self.status_var.set('正在停止…')

        def _open_out(self):
            target = None
            out_text = self.out_var.get().strip()
            if out_text and Path(out_text).is_dir():
                target = Path(out_text)
            elif getattr(self, '_last_output', None) and Path(self._last_output).is_dir():
                target = Path(self._last_output)
            else:
                root_text = self.root_var.get().strip()
                if root_text and Path(root_text).is_dir():
                    target = Path(root_text)
            if not target:
                messagebox.showinfo('提示', '暂无可打开的输出目录')
                return
            try:
                os.startfile(str(target))
            except Exception as exc:
                messagebox.showerror('打开失败', str(exc))

    root = tk.Tk()
    try:
        ttk.Style().theme_use('vista')
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


def main():
    launch_gui()
    return 0


if __name__ == '__main__':
    sys.exit(main())
