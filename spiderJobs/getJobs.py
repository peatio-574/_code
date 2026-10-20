# coding='utf-8'
"""招聘岗位数据采集系统
========================
统一入口与可视化界面，三个站点的采集逻辑已按平台拆分：

  - getJobs.py ：公共常量（XLSX_HEADERS）、xlsx 读写工具、GUI（BaseSpiderGUI 及各站点面板）、入口
  - guopin.py  ：国聘采集类 GuoPin（requests 调接口，同步采集）
  - ncss.py    ：国家大学生就业服务平台采集类 Ncss（requests 取列表 + 解析详情页）
  - zhipin.py  ：智联招聘采集类 ZhiPin（Playwright 浏览器登录态，异步采集）

统一输出字段：采集日期、来源、省份、城市、职位名称……职位描述（见 XLSX_HEADERS）。
"""
import os
import sys
import threading
import time
from datetime import datetime, timedelta

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

import tkinter as tk
from tkinter import simpledialog, ttk


# ==================== 路径（脚本 / exe 同目录为准） ====================
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR)
for _p in (_BASE_DIR, _ROOT_DIR):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

# 日志目录固定跟随程序目录（脚本 / exe 同目录），不依赖 os.getcwd()：
# 工作目录可能被删除、不存在或返回 None，用它会直接抛异常。
os.environ.setdefault('LOG_DIR', os.path.join(_BASE_DIR, 'logs'))

from Logger import logger


# ==================== 统一输出表格列 ====================
# 三个站点共用的表头，导出 xlsx / 界面展示都以此为准。
XLSX_HEADERS = [
    '采集日期', '来源', '省份', '城市',
    "职位名称", "公司名称", "公司性质", "公司规模", "公司行业",
    "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
    "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
    "报名截止", "职位描述"
]

def _read_xlsx_rows(file):
    """用openpyxl按行读取xlsx，返回 [[col1,col2,...], ...]；读取失败返回空列表。"""
    if not file or not os.path.exists(file):
        return []
    wb = None
    try:
        wb = load_workbook(file, read_only=True)
        ws = wb.active
        # 把单元格统一转成字符串，空值为空串，便于后续处理
        return [[str(c) if c is not None else '' for c in row]
                for row in ws.iter_rows(values_only=True)]
    except Exception as e:
        logger.error(f'读取 {os.path.basename(file)} 失败：{e}')
        return []
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass


# ==================== xlsx 公共操作（三个采集类复用） ====================
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
THIN_BORDER = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)


def prepare_workbook(data_file):
    """打开（或新建）工作簿并写好表头样式，返回 (wb, ws)。"""
    wb = load_workbook(filename=data_file) if os.path.exists(data_file) else Workbook()
    ws = wb.active
    ws.title = "职位数据"
    ws.freeze_panes = 'A2'
    for col, header in enumerate(XLSX_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER
    save_workbook(wb, data_file)
    return wb, ws


def save_workbook(wb, data_file, tag=''):
    """保存工作簿；文件被 Excel 占用时改写时间戳文件，避免中断采集。返回实际写入路径。"""
    try:
        wb.save(data_file)
        return data_file
    except PermissionError:
        fallback = f'{os.path.splitext(data_file)[0]}_{time.strftime("%Y%m%d_%H%M%S")}.xlsx'
        try:
            wb.save(fallback)
            logger.info(f'{tag}{os.path.basename(data_file)} 被占用（请关闭 Excel），'
                        f'本次改写入 {os.path.basename(fallback)}')
            return fallback
        except Exception as e:
            logger.error(f'{tag}保存失败（{os.path.basename(data_file)}）：{e}')
            return data_file
    except Exception as e:
        logger.error(f'{tag}保存失败（{os.path.basename(data_file)}）：{e}')
        return data_file


def read_recent_rows(data_file):
    """读取昨日/今日已入库数据（去掉采集日期列），用于增量去重。"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    recent = []
    for row in _read_xlsx_rows(data_file):
        if not row:
            continue
        if str(row[0]).split(' ')[0] in (yesterday, today):
            recent.append(row[1:])
    return recent


# ==================== 暂停 / 停止（可打断） ====================
# 轮询间隔：越小响应越快，但空转略多；0.2s 在界面上基本感觉不到延迟。
POLL_INTERVAL = 0.2


def running_now(probe, default=True):
    """读取「是否仍在运行」。

    probe 支持两种形式：
      * 可调用对象（GUI 传 lambda: panel.is_running，子线程据此实时取主线程状态）
      * 布尔值（命令行/脚本直接传 True/False）
    probe 为 None 时返回 default。
    """
    if probe is None:
        return default
    return bool(probe() if callable(probe) else probe)


def is_stopped(is_running=None):
    """is_running 为 None 时视为未停止；否则按 running_now 的规则判断。"""
    return is_running is not None and not running_now(is_running)


def wait_while_paused(pause_event=None, is_running=None):
    """暂停时阻塞，停止时立即返回 False（不再死等 pause_event）。"""
    while True:
        if is_stopped(is_running):
            return False
        if pause_event is None or pause_event.is_set():
            return True
        pause_event.wait(POLL_INTERVAL)


def interruptible_sleep(seconds, pause_event=None, is_running=None):
    """可被停止打断的 sleep；暂停期间不计时。返回 False 表示应终止采集。"""
    remain = max(0.0, float(seconds or 0))
    while True:
        if not wait_while_paused(pause_event, is_running):
            return False
        if remain <= 0:
            return True
        chunk = min(POLL_INTERVAL, remain)
        time.sleep(chunk)
        remain -= chunk




class BaseSpider(object):
    """三个采集类共用的运行状态、写盘节流与入库逻辑。

    子类只需定义 web_name、实现自己的 get_page_info / parser_page_info / run。
    """

    web_name = ''
    SAVE_INTERVAL = 10          # 两次写盘的最小间隔（秒），避免每页都重写整本 xlsx

    # 当前任务状态（由 run 设置）
    _pause_event = None
    # 运行状态探针：存布尔值或可调用对象（如 lambda: panel.is_running）
    _running_probe = None
    _save_ts = 0.0
    _saved_path = None          # 实际写入路径（被 Excel 占用时会变成时间戳文件）

    # ==================== 运行状态 ====================

    @classmethod
    def _begin_run(cls, pause_event, is_running):
        """开始一轮采集前重置状态。"""
        cls._pause_event = pause_event
        cls._running_probe = is_running
        cls._save_ts = 0.0
        cls._saved_path = None

    @classmethod
    def _should_stop(cls):
        """probe 可能是 lambda，也可能是布尔值，统一经 running_now 取值。"""
        return cls._running_probe is not None and not running_now(cls._running_probe)

    @classmethod
    def _wait(cls):
        """暂停时阻塞；返回 False 表示用户已点停止。"""
        return wait_while_paused(cls._pause_event, cls._running_probe)

    @classmethod
    def _sleep(cls, seconds):
        """可被打断的等待（暂停期间不计时）；返回 False 表示应终止。"""
        return interruptible_sleep(seconds, cls._pause_event, cls._running_probe)

    # ==================== xlsx ====================

    @classmethod
    def load_yesterday_data(cls, data_file):
        """读取昨日/今日已入库数据（去掉采集日期列），用于增量去重。"""
        return read_recent_rows(data_file)

    @classmethod
    def set_column_style(cls, data_file):
        """打开工作簿并写好表头样式，返回 (wb, ws)。"""
        return prepare_workbook(data_file)

    @classmethod
    def _save(cls, wb, data_file, force=False):
        """按时间节流保存；force=True 立即写盘（停止/结束时调用）。

        一旦因文件被占用而改写时间戳文件，后续都写同一个文件，避免数据分散。
        """
        now = time.time()
        if not force and now - cls._save_ts < cls.SAVE_INTERVAL:
            return cls._saved_path
        target = data_file
        if cls._saved_path and cls._saved_path != data_file:
            target = cls._saved_path
        cls._saved_path = save_workbook(wb, target, tag=f'【{cls.web_name}】')
        cls._save_ts = now
        return cls._saved_path

    # ==================== 入库 ====================

    @classmethod
    def _append_rows(cls, rows, all_rows, seen, ws=None, write=True, on_data=None):
        """按整行（不含采集日期）去重后写入工作表并回调；返回本次新增条数。"""
        count = 0
        for row in rows:
            key = tuple(row[1:])
            if key in seen:
                continue
            seen.add(key)
            count += 1
            all_rows.append(row)
            if write and ws is not None:
                ws.append(row)
            if on_data is not None:
                on_data(row)
        return count

    @classmethod
    def _finish_message(cls, added, stopped=False, failed=0):
        """统一的结束提示文案。"""
        suffix = f'，{failed} 个来源失败' if failed else ''
        if stopped:
            return f'{cls.web_name}采集已停止（新增 {added} 条{suffix}）'
        return f'{cls.web_name}采集完成（新增 {added} 条{suffix}）'


# ==================== 可视化界面 ====================
class BaseSpiderGUI:
    """爬虫可视化基类（通用界面，供子类复用以实现具体爬虫）。
    提供：开始/暂停/停止、进度条、数据表格、分页、每秒定时刷新表格。
    子类只需实现 spider_task()；采集中通过 on_data()/on_progress() 回调刷新界面。"""

    def __init__(self, title='数据采集系统', spider_name='', parent=None):
        # 主窗口；parent 为空则自身新建窗口，否则嵌入到 parent(容器Frame)中复用
        if parent is None:
            self.root = tk.Tk()
            self.root.title(title)
            self.root.geometry('960x640')
            self.root.minsize(800, 500)
            self._owns_root = True
            self.container = self.root
        else:
            self.root = parent.winfo_toplevel()
            self._owns_root = False
            self.container = parent

        self.spider_name = spider_name
        # 运行状态控制
        self.is_running = False
        self.is_paused = False
        self.pause_event = threading.Event()   # 置位=运行，清空=暂停（爬虫在循环里 wait 该事件）
        self.pause_event.set()
        self.spider_thread = None             # 后台采集线程

        # 统计信息
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self.current_city = ''
        self.current_page_no = 0
        self.start_time = None

        # 表格数据（内存中全量数据 + 分页）
        self.all_rows = []
        self.page_size = 100
        self.current_page = 0
        self._refresh_pending = False         # 是否有待刷新的数据
        self._refresh_timer_id = None         # 定时刷新任务 ID

        self._build_ui()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        self._build_header()
        self._build_control_panel()
        self._build_table()
        self._build_pagination()
        self._build_log_panel()
        self._build_status_bar()

    def _build_header(self):
        header = tk.Frame(self.container, bg='#2c3e50', height=50)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text=f'📊 {self.spider_name}数据采集',
                 bg='#2c3e50', fg='white', font=('微软雅黑', 14, 'bold')).pack(side='left', padx=15)
        self.lbl_time = tk.Label(header, text='', bg='#2c3e50', fg='#ecf0f1', font=('微软雅黑', 9))
        self.lbl_time.pack(side='right', padx=15)
        self._update_clock()

    def _build_control_panel(self):
        frame = tk.LabelFrame(self.container, text=' 控制面板 ', font=('微软雅黑', 10, 'bold'), padx=10, pady=8)
        frame.pack(fill='x', padx=10, pady=(10, 5))

        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill='x')

        self.btn_start = tk.Button(btn_frame, text='▶ 开始采集', width=12, bg='#27ae60', fg='white',
                                   font=('微软雅黑', 10, 'bold'), command=self._on_start)
        self.btn_start.pack(side='left', padx=(0, 8))

        self.btn_pause = tk.Button(btn_frame, text='⏸ 暂停', width=10, bg='#f39c12', fg='white',
                                   font=('微软雅黑', 10, 'bold'), command=self._on_pause, state='disabled')
        self.btn_pause.pack(side='left', padx=(0, 8))

        self.btn_stop = tk.Button(btn_frame, text='⏹ 停止', width=10, bg='#e74c3c', fg='white',
                                  font=('微软雅黑', 10, 'bold'), command=self._on_stop, state='disabled')
        self.btn_stop.pack(side='left')

        self.btn_refresh = tk.Button(btn_frame, text='🔄 刷新列表', width=12, bg='#8e44ad', fg='white',
                                     font=('微软雅黑', 10, 'bold'), command=self._on_refresh)
        self.btn_refresh.pack(side='left', padx=(8, 0))

        progress_frame = tk.Frame(frame)
        progress_frame.pack(fill='x', pady=(8, 0))

        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=(0, 10))

        self.lbl_progress = tk.Label(progress_frame, text='0%', font=('微软雅黑', 9), width=6)
        self.lbl_progress.pack(side='right')

        status_frame = tk.Frame(frame)
        status_frame.pack(fill='x', pady=(5, 0))

        self.lbl_status = tk.Label(status_frame, text='就绪', font=('微软雅黑', 9), fg='#7f8c8d', anchor='w')
        self.lbl_status.pack(side='left', fill='x', expand=True)

        self.lbl_stats = tk.Label(status_frame, text='', font=('微软雅黑', 9), fg='#2c3e50')
        self.lbl_stats.pack(side='right')

    def _build_table(self):
        table_frame = tk.Frame(self.container)
        table_frame.pack(fill='both', expand=True, padx=10, pady=(5, 5))

        columns = ('id', 'date', 'source', 'province', 'city', 'job_name', 'company_name', 'nature', 'scale',
                   'industry', 'recruit_type', 'job_type', 'category', 'salary',
                   'amount', 'education', 'experience', 'major', 'location',
                   'address', 'deadline', 'description')
        headings = ('ID', '采集日期', '来源', '省份', '城市', '职位名称', '公司名称', '公司性质', '公司规模',
                    '公司行业', '招聘类型', '职位性质', '职位类别', '薪资范围',
                    '招聘人数', '学历要求', '经验要求', '专业要求', '工作地点',
                    '详细地址', '报名截止', '职位描述')

        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=18)
        self.tree.heading('#0', text='')
        self.tree.column('#0', width=0, stretch=False)

        widths = [50, 80, 60, 60, 70, 160, 200, 60, 80, 140, 70, 50, 100, 110,
                  50, 80, 80, 180, 90, 180, 130, 250]
        for col, heading, w in zip(columns, headings, widths):
            self.tree.heading(col, text=heading, anchor='w')
            self.tree.column(col, width=w, minwidth=40, anchor='w')

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind('<MouseWheel>', lambda e: self.tree.yview_scroll(int(-1 * (e.delta / 120)), 'units'))

    def _build_pagination(self):
        frame = tk.Frame(self.container)
        frame.pack(fill='x', padx=10, pady=(0, 5))

        self.btn_prev = tk.Button(frame, text='< 上一页', width=10, state='disabled',
                                  command=self._on_prev_page)
        self.btn_prev.pack(side='left')

        self.lbl_page = tk.Label(frame, text='第 0/0 页  共 0 条', font=('微软雅黑', 9))
        self.lbl_page.pack(side='left', expand=True)

        self.btn_next = tk.Button(frame, text='下一页 >', width=10, state='disabled',
                                  command=self._on_next_page)
        self.btn_next.pack(side='right')

    def _on_prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()

    def _on_next_page(self):
        max_page = (len(self.all_rows) - 1) // self.page_size
        if self.current_page < max_page:
            self.current_page += 1
            self._refresh_table()

    def _do_refresh(self):
        """刷新数据表格并清除“待刷新”标记。"""
        self._refresh_pending = False
        self._refresh_table()

    def _schedule_refresh_timer(self):
        """启动每秒一次的表格刷新定时器（避免多次重复创建）。"""
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
        self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)

    def _on_periodic_tick(self):
        """每秒回调：有新数据就刷新表格；运行中则继续排程下一次刷新。"""
        if self._refresh_pending:
            self._do_refresh()
        if self.is_running:
            self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)
        else:
            self._refresh_timer_id = None

    def _refresh_table(self):
        """按当前分页刷新表格内容（清空重绘当前页）。"""
        self.tree.delete(*self.tree.get_children())
        start = self.current_page * self.page_size
        end = start + self.page_size
        page_data = self.all_rows[start:end]
        for i, row in enumerate(page_data, start=start + 1):
            values = (str(i),) + tuple(str(v) if v is not None else '' for v in row)
            self.tree.insert('', 'end', values=values)
        total_pages = max(1, (len(self.all_rows) - 1) // self.page_size + 1)
        self.lbl_page.config(text=f'第 {self.current_page + 1}/{total_pages} 页  共 {len(self.all_rows)} 条')
        self.btn_prev.config(state='normal' if self.current_page > 0 else 'disabled')
        self.btn_next.config(state='normal' if self.current_page < total_pages - 1 else 'disabled')

    def _build_status_bar(self):
        bar = tk.Frame(self.container, bg='#ecf0f1', height=24)
        bar.pack(fill='x', side='bottom')
        bar.pack_propagate(False)
        self.lbl_bottom = tk.Label(bar, text='就绪', bg='#ecf0f1', fg='#7f8c8d',
                                   font=('微软雅黑', 8), anchor='w')
        self.lbl_bottom.pack(side='left', padx=10)

    def _build_log_panel(self):
        """运行日志面板：与文件日志同步，方便直接看到暂停/停止/失败原因。"""
        frame = tk.LabelFrame(self.container, text=' 运行日志 ', font=('微软雅黑', 9, 'bold'))
        frame.pack(fill='x', padx=10, pady=(0, 5))

        wrap = tk.Frame(frame)
        wrap.pack(fill='both', expand=True)
        self.txt_log = tk.Text(wrap, height=6, wrap='none', font=('Consolas', 9),
                               bg='#1e1e1e', fg='#d4d4d4', insertbackground='#d4d4d4',
                               state='disabled')
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

    # ==================== 线程安全 UI 调度 ====================

    def _ui(self, func):
        """把回调投递到主线程执行；窗口已关闭/事件循环未启动时静默忽略。"""
        try:
            self.root.after(0, func)
        except Exception:
            pass
    # ==================== 日志 ====================

    def _log(self, message, level='info'):
        """写入文件日志，并追加到界面日志面板（线程安全）。"""
        getattr(logger, level, logger.info)(f'[{self.spider_name}] {message}')
        if not hasattr(self, 'txt_log'):
            return
        line = f'{time.strftime("%H:%M:%S")} {message}\n'

        def _append():
            try:
                self.txt_log.configure(state='normal')
                self.txt_log.insert('end', line)
                # 只保留最近约 400 行，避免长时间运行后占用内存
                if int(self.txt_log.index('end-1c').split('.')[0]) > 400:
                    self.txt_log.delete('1.0', '100.0')
                self.txt_log.see('end')
                self.txt_log.configure(state='disabled')
            except Exception:
                pass

        try:
            self.root.after(0, _append)
        except Exception:
            pass

    # ==================== 时钟 ====================

    def _update_clock(self):
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        self.lbl_time.config(text=now)
        self.root.after(1000, self._update_clock)

    # ==================== 按钮事件 ====================

    def _on_start(self):
        if self.is_running and not self.is_paused:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self.btn_pause.config(text='⏸ 暂停', bg='#f39c12')
            self._set_status('继续采集中...')
            self._log('继续采集')
            return

        self.is_running = True
        self.is_paused = False
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self.start_time = time.time()

        # 切换平台/重新抓取时清空上一批数据
        self.all_rows = []
        self.current_page = 0
        self._refresh_table()
        self.tree.delete(*self.tree.get_children())

        self.btn_start.config(state='disabled')
        self.btn_pause.config(state='normal')
        self.btn_stop.config(state='normal')

        self._set_status('正在准备 %s 采集...' % self.spider_name)
        log_file = getattr(logger, 'filename', '')
        self._log(f'开始采集，数据文件：{self.default_data_file() or "(默认)"}')
        if log_file:
            self._log(f'日志文件：{log_file}')
        self._schedule_refresh_timer()
        self.spider_thread = threading.Thread(target=self.spider_task, daemon=True)
        self.spider_thread.start()

    def _on_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self.btn_pause.config(text='⏸ 暂停', bg='#f39c12')
            self._set_status('继续采集中...')
            self._log('继续采集')
        else:
            self.is_paused = True
            self.pause_event.clear()
            self.btn_pause.config(text='▶ 继续', bg='#3498db')
            self._set_status('已暂停')
            self._log('已暂停（当前请求结束后生效）')

    def _on_stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.is_paused = False
        self.pause_event.set()      # 唤醒正在暂停的线程
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
            self._refresh_timer_id = None
        self.btn_pause.config(state='disabled', text='⏸ 暂停', bg='#f39c12')
        self.btn_stop.config(state='disabled')
        self._set_status('正在停止，请稍候…')
        self._log('用户点击停止，等待当前请求结束…')
        self._do_refresh()
        self._poll_thread_exit()

    def _poll_thread_exit(self):
        """等待采集线程真正退出后再恢复“开始”按钮，避免重复启动。"""
        thread = self.spider_thread
        if thread is not None and thread.is_alive():
            self.root.after(200, self._poll_thread_exit)
            return
        self.btn_start.config(state='normal')
        elapsed = time.time() - self.start_time if self.start_time else 0
        self._set_status(f'已停止（本次采集 {self.today_count} 条，耗时 {elapsed:.0f}s）')

    # ==================== 爬虫回调 ====================

    def on_progress(self, current, total, city=''):
        # 跨线程更新控件：必须通过 root.after 调度回主线程，避免 Tkinter 线程安全问题
        def _update():
            self.total_count = current
            pct = int(current / total * 100) if total > 0 else 0
            self.progress['value'] = pct
            self.lbl_progress.config(text=f'{pct}%')
            self.current_city = city
            elapsed = time.time() - self.start_time if self.start_time else 0
            self.lbl_stats.config(text=f'已采集: {self.today_count} | 错误: {self.error_count} | 耗时: {elapsed:.0f}s')
            self._set_status(f'正在采集: {city} ({current}/{total})')
            self.lbl_bottom.config(text=f'当前: {city} | 进度: {current}/{total}')
        self._ui(_update)
        self._log(f'进度 {current}/{total}：{city}')

    def on_complete(self, msg='采集完成'):
        self.is_running = False
        self.is_paused = False
        if self._refresh_timer_id is not None:
            self.root.after_cancel(self._refresh_timer_id)
            self._refresh_timer_id = None
        elapsed = time.time() - self.start_time if self.start_time else 0
        summary = f'{msg}（本次采集 {self.today_count} 条，耗时 {elapsed:.0f}s）'
        self._ui(lambda: self.btn_start.config(state='normal'))
        self._ui(lambda: self.btn_pause.config(state='disabled', text='⏸ 暂停', bg='#f39c12'))
        self._ui(lambda: self.btn_stop.config(state='disabled'))
        self._ui(lambda: self._set_status(summary))
        # 被用户停止时不要把进度条拉满，避免误以为已全部完成
        if '停止' not in msg:
            self._ui(lambda: self.progress.config(value=100))
            self._ui(lambda: self.lbl_progress.config(text='100%'))
        self._ui(self._do_refresh)
        self._log(summary)

    def on_page_progress(self, page_id, page_added, city_total, elapsed):
        """页级进度：分页接口用它显示“第几页 + 新增条数 + 累计条数 + 耗时”。"""
        # 国聘的 current_city 是「省-市」；Ncss 的进度标签本身就是「第 x/y 页」，避免重复拼接
        scope = self.current_city if self.current_city and '页' not in self.current_city else ''
        detail = f'第 {page_id} 页（新增 {page_added} 条，累计 {city_total} 条，{elapsed:.0f}s）'
        text = f'{scope} {detail}'.strip()

        def _update():
            self.current_page_no = page_id
            self.lbl_bottom.config(text=f'当前: {text}')
            self._set_status(f'正在采集: {text}')
            if self.start_time:
                self.lbl_stats.config(
                    text=f'已采集: {self.today_count} | 错误: {self.error_count} | '
                         f'耗时: {time.time() - self.start_time:.0f}s')
        self._ui(_update)
        self._log(text)

    def on_error(self, msg):
        self.error_count += 1
        self._ui(lambda: self._set_status(f'错误: {msg}'))
        self._log(f'错误: {msg}', level='error')

    def on_data(self, row):
        self.today_count += 1
        self.all_rows.append(row)
        if not self._refresh_pending:
            self._refresh_pending = True
            self.root.after(200, self._do_refresh)
        if self.today_count % 50 == 0:
            self._log(f'已采集 {self.today_count} 条')

    def check_pause(self):
        """暂停时阻塞、停止时立即返回 False，调用方需按返回值决定是否继续。"""
        return wait_while_paused(self.pause_event, lambda: self.is_running)

    def _insert_row(self, row):
        row_id = len(self.tree.get_children()) + 1
        values = (str(row_id),) + tuple(str(v) if v is not None else '' for v in row)
        self.tree.insert('', 'end', values=values)
        self.tree.yview_moveto(1.0)

    def _set_status(self, text):
        self.lbl_status.config(text=text)

    def default_data_file(self):
        """当前爬虫使用的数据文件（子类可覆盖）。"""
        return None

    def _on_refresh(self):
        """手动刷新：从数据文件重新读取并刷新表格。"""
        f = self.default_data_file() or \
            simpledialog.askstring('刷新列表', '输入数据文件路径（取消则退出）:', parent=self.root)
        if not f:
            return
        if not os.path.exists(f):
            self._set_status('文件不存在: %s' % f)
            return
        try:
            rows = _read_xlsx_rows(f)
            header = XLSX_HEADERS
            data = []
            for r in rows:
                # 跳过表头行与空行
                if not r or (len(r) > 0 and str(r[0]) == str(header[0])):
                    continue
                data.append(tuple(r))
            self.all_rows = data
            self.current_page = 0
            self._refresh_table()
            self.lbl_bottom.config(text='已刷新 %s，共 %d 条' % (os.path.basename(f), len(data)))
            self._set_status('刷新完成，共 %d 条' % len(data))
        except Exception as e:
            self._set_status('刷新失败: %s' % e)

    def spider_task(self):
        raise NotImplementedError('子类必须实现 spider_task 方法')

    def run(self):
        if self._owns_root:
            self.root.mainloop()


def _run_guopin_gui(panel, data_file):
    """国聘采集的 GUI 驱动逻辑（GuoPinGUI / GuopinPanel 共用）。"""
    from guopin import GuoPin

    def _on_page(page_id, page_added, city_total, elapsed):
        panel.on_page_progress(page_id, page_added, city_total, elapsed)

    GuoPin.run(
        data_file,
        pause_event=panel.pause_event,
        is_running=lambda: panel.is_running,
        on_progress=panel.on_progress,
        on_page=_on_page,
        on_data=panel.on_data,
        on_complete=panel.on_complete,
    )


class GuoPinGUI(BaseSpiderGUI):
    """国聘采集可视化界面（独立窗口）"""

    def __init__(self):
        super().__init__(title='国聘数据采集系统', spider_name='国聘')

    def default_data_file(self):
        return '国聘数据.xlsx'

    def spider_task(self, data_file=None):
        _run_guopin_gui(self, data_file or self.default_data_file())


class ZhilianPanel(BaseSpiderGUI):
    """智联招聘采集面板（独立页签）。"""

    def __init__(self, master):
        container = tk.Frame(master)
        super().__init__(title='', spider_name='智联招聘', parent=container)

    def default_data_file(self):
        return '智联数据.xlsx'

    # 线程安全弹窗输入（智联登录手机号/验证码）
    def _ask(self, prompt):
        res = {}
        evt = threading.Event()

        def _dialog():
            res['v'] = simpledialog.askstring('智联登录', prompt, parent=self.root)
            evt.set()

        self.root.after(0, _dialog)
        evt.wait()
        return (res.get('v') or '').strip()

    def spider_task(self, data_file=None):
        self._run_zhilian(data_file or self.default_data_file())

    def _run_zhilian(self, data_file='智联数据.xlsx'):
        from zhipin import ZhiPin

        def _on_progress(prov, city, added):
            # 线程安全：控件更新通过 root.after 回到主线程执行
            def _u():
                self._set_status('正在采集: %s-%s (新增 %d)' % (prov, city, added))
                self.lbl_bottom.config(text='当前: %s-%s | 新增: %d' % (prov, city, added))
            self.root.after(0, _u)

        try:
            ZhiPin.run(data_file,
                       ask=self._ask,
                       pause_event=self.pause_event,
                       is_running=lambda: self.is_running,
                       on_progress=_on_progress,
                       on_data=self.on_data,
                       on_complete=self.on_complete,
                       on_error=self.on_error)
        except Exception as e:
            logger.error('智联招聘采集异常：%s' % e)
            self.on_error('智联招聘: %s' % e)
            self.on_complete('智联招聘异常结束')


class GuopinPanel(BaseSpiderGUI):
    """国聘采集面板（独立页签）。"""

    def __init__(self, master):
        container = tk.Frame(master)
        super().__init__(title='', spider_name='国聘', parent=container)

    def default_data_file(self):
        return '国聘数据.xlsx'

    def spider_task(self, data_file=None):
        _run_guopin_gui(self, data_file or self.default_data_file())

class NcssPanel(BaseSpiderGUI):
    """国家大学生就业服务平台采集面板（独立标签页）。"""

    def __init__(self, master):
        container = tk.Frame(master)
        super().__init__(title='', spider_name='国家大学生就业服务平台', parent=container)

    # 需要采集的来源平台；None 表示按 ncss.Ncss.CRAWL_SOURCES（全部平台）
    sources = None

    def default_data_file(self):
        return '国家大学生就业服务平台.xlsx'

    def spider_task(self, data_file=None):
        from ncss import Ncss

        data_file = data_file or self.default_data_file()
        try:
            Ncss.run(
                data_file,
                sources=self.sources,
                pause_event=self.pause_event,
                is_running=lambda: self.is_running,
                on_progress=self.on_progress,
                on_page=self.on_page_progress,
                on_data=self.on_data,
                on_complete=self.on_complete,
                on_error=self.on_error,
            )
        except Exception as e:
            logger.error('国家大学生就业服务平台采集异常：%s' % e)
            self.on_error('国家大学生就业服务平台: %s' % e)
            self.on_complete('国家大学生就业服务平台异常结束')


class SpiderGUI:
    """主窗口：两个页签（智联招聘 / 国聘），各自独立开始采集、各自独立数据展示。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('数据采集系统')
        self.root.geometry('1080x700')
        self.root.minsize(900, 560)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=8, pady=8)

        self.tab_zhi = ZhilianPanel(self.root)
        self.tab_gp = GuopinPanel(self.root)
        self.tab_ncss = NcssPanel(self.root)
        self.notebook.add(self.tab_zhi.container, text=' 智联招聘 ')
        self.notebook.add(self.tab_gp.container, text=' 国聘 ')
        self.notebook.add(self.tab_ncss.container, text=' 国家大学生就业服务平台 ')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    SpiderGUI().run()

