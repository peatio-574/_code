# coding='utf-8'
"""招聘岗位数据采集系统
========================
统一入口与可视化界面，各站点的采集逻辑已按平台拆分：

  - getJobs.py ：公共常量（XLSX_HEADERS）、xlsx 读写工具、GUI（BaseSpiderGUI 及各站点面板）、入口
  - guopin.py  ：国聘采集类 GuoPin（requests 调接口，同步采集）
  - ncss.py    ：国家大学生就业服务平台采集类 Ncss（requests 取列表 + 解析详情页）
  - zhipin.py  ：智联招聘采集类 ZhiPin（Playwright 浏览器登录态，异步采集）
  - Boss.py    ：BOSS直聘采集类 Boss（PatchRight 浏览器内请求，逐条取详情）

登录凭证统一存放于 config/config.ini，界面可编辑的配置统一存放于 config/ 下的 JSON。

统一输出字段：采集日期、来源、省份、城市、职位名称……职位描述（见 XLSX_HEADERS）。
"""
import os
import sys
import json
import re
import ssl
import base64
import io
import threading
import time
from datetime import datetime, timedelta

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


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


# ==================== 配置文件加载 ====================
CONFIG_DIR = os.path.join(_BASE_DIR, 'config')


def load_config(name, default=None):
    """读取 config/ 下的 JSON 配置；文件缺失或损坏时返回 default。"""
    path = os.path.join(CONFIG_DIR, name)
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f'配置文件不存在：{path}，使用内置默认值')
        return default
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f'配置文件读取失败：{path}：{e}')
        return default


# ==================== 统一输出表格列 ====================
# 表头与界面列宽统一由 config/columns.json 定义，不再硬编码。
_DEFAULT_HEADERS = [
    '采集日期', '来源', '省份', '城市',
    "职位名称", "岗位编号", "公司名称", "公司性质", "公司规模", "公司行业",
    "招聘类型", "职位性质", "职位类别", "薪资范围", "招聘人数",
    "学历要求", "经验要求", "专业要求", "工作地点", "详细地址",
    "报名截止", "职位描述"
]

_COLUMNS_CFG = load_config('columns.json', {}) or {}
XLSX_HEADERS = _COLUMNS_CFG.get('headers') or _DEFAULT_HEADERS

# 岗位编号所在列（1-based），去重与更新都依赖它
ID_FIELD = _COLUMNS_CFG.get('id_column') or '岗位编号'
try:
    ID_COLUMN = XLSX_HEADERS.index(ID_FIELD) + 1
except ValueError:
    ID_FIELD = '岗位编号'
    ID_COLUMN = XLSX_HEADERS.index(ID_FIELD) + 1 if ID_FIELD in XLSX_HEADERS else 0

# GUI 表格列定义：[{key, header, width, visible}, ...]
# 首个虚拟列 id 由界面自行添加，不在此配置中。
TABLE_COLUMNS = _COLUMNS_CFG.get('columns') or [
    {'key': key, 'header': h, 'width': 110, 'visible': True}
    for key, h in zip(
        ['date', 'source', 'province', 'city', 'job_name', 'job_id',
         'company_name', 'nature', 'scale', 'industry', 'recruit_type',
         'job_type', 'category', 'salary', 'amount', 'education',
         'experience', 'major', 'location', 'address', 'deadline',
         'description'],
        XLSX_HEADERS)
]

# ==================== 来源字段：平台名 -> 写入表格的值 ====================
# 各采集类的 web_name 是明文平台名（BOSS直聘 / 智联招聘 / 国聘 /
# 国家大学生就业服务平台），写入表格时按 config.ini 的 [source] 段替换：
#
#   [source]
#   BOSS直聘 = MT86N4Lp/ofj6w
#   智联招聘 = lenTjOTmrOT5m6yq
#
# 规则：
#   * 平台名大小写、首尾空白都忽略（写 boss直聘 也能匹配 BOSS直聘）
#   * 右侧非空  -> 「来源」列写入该值
#   * 右侧为空或缺少该行 -> **启动时自动生成加密值并回写 ini**（见下）
#
# 自动填写：程序启动时调用 ensure_source_codes()，把缺失的加密值补进 ini，
# 这样无需手工计算/粘贴，第一次运行就自动配好。

# 已知平台清单（顺序即写入 ini 的顺序）
KNOWN_SOURCES = [
    'BOSS直聘',
    '智联招聘',
    '国聘',
    '国家大学生就业服务平台',
]

SOURCE_KEY = 'spiderJobs-2026'


def _resolve_ini():
    """定位 config.ini：优先 config/ 子目录，回退程序同目录。"""
    for base in (os.path.join(_BASE_DIR, 'config'), _BASE_DIR):
        path = os.path.join(base, 'config.ini')
        if os.path.exists(path):
            return path
    return os.path.join(_BASE_DIR, 'config', 'config.ini')


CONFIG_FILE = _resolve_ini()


def _xor_bytes(data, key):
    """按字节与密钥循环异或（对称）。"""
    k = key.encode('utf-8')
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))


def encode_source(name):
    """把平台名编码成纯 ASCII 字符串（异或 + Base64，去掉 = 填充）。"""
    name = str(name or '')
    if not name:
        return name
    raw = _xor_bytes(name.encode('utf-8'), SOURCE_KEY)
    return base64.b64encode(raw).decode('ascii').rstrip('=')


def ensure_source_codes(ini_path=None):
    """确保 [source] 段存在且每个已知平台都有值；缺失的自动生成并回写。

    只做「补全」，不覆盖已有值（手工改过的值会保留）。
    返回本次写入的 {平台名: 编码值}；无需改动时返回空字典。

    实现上按**行**修改 ini，而不是 configparser.write()：
    后者会丢掉全部注释、重排段落，把用户手工维护的 config.ini 改得面目全非。
    """
    import configparser

    path = ini_path or CONFIG_FILE
    if not os.path.exists(path):
        return {}

    try:
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = lambda s: s     # 保留键名大小写
        cfg.read(path, encoding='utf-8')
    except Exception as e:
        logger.warning('读取 %s 失败，来源自动填写跳过：%s' % (path, e))
        return {}

    has_section = cfg.has_section('source')
    existing = {}
    if has_section:
        for k, v in cfg.items('source'):
            existing[k.strip().casefold()] = (k.strip(), (v or '').strip())

    # 算出需要写入的项
    filled = {}
    for name in KNOWN_SOURCES:
        key = name.casefold()
        if key in existing:
            real_key, val = existing[key]
            if val:
                continue                  # 已有值，保留
            filled[real_key] = encode_source(name)
        else:
            filled[name] = encode_source(name)

    if not filled:
        return {}

    # 按行改原文：保留注释、顺序、其它段落与换行风格
    try:
        raw = io.open(path, 'r', encoding='utf-8', newline='').read()
    except OSError as e:
        logger.warning('读取 %s 失败，来源自动填写跳过：%s' % (path, e))
        return {}

    nl = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.split(nl)

    # 定位 [source] 段范围
    start = end = None
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith('[') and st.endswith(']'):
            if start is not None and end is None:
                end = i
            if st == '[source]':
                start = i
    if start is not None and end is None:
        end = len(lines)

    if start is None:
        # 文件里还没有 [source] 段：追加到末尾
        if lines and lines[-1] == '':
            lines.pop()
        lines.append('')
        lines.append('[source]')
        for name, code in filled.items():
            lines.append('%s = %s' % (name, code))
        lines.append('')
        new_text = nl.join(lines)
    else:
        # 段内已有的行改值，其余项追加到段末
        done = set()
        for i in range(start + 1, end):
            line = lines[i]
            st = line.strip()
            if not st or st.startswith('#') or st.startswith(';') or '=' not in line:
                continue
            k, _, _old = line.partition('=')
            k_stripped = k.strip()
            fk = k_stripped.casefold()
            for name, code in filled.items():
                if name.casefold() == fk:
                    lines[i] = '%s = %s' % (k_stripped, code)
                    done.add(name)
                    break
        extra = [n for n in filled if n not in done]
        if extra:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1            # 插在段内最后一条非空行之后
            for offset, name in enumerate(extra):
                lines.insert(insert_at + offset, '%s = %s' % (name, filled[name]))
        new_text = nl.join(lines)

    try:
        io.open(path, 'w', encoding='utf-8', newline='').write(new_text)
        logger.info('已在 %s 的 [source] 段自动填写 %d 个平台的加密值：%s'
                    % (os.path.basename(path), len(filled),
                       '、'.join(filled)))
    except OSError as e:
        logger.warning('写回 %s 失败（本次仍使用内存中的值）：%s' % (path, e))
    return filled


def _load_source_map(ini_path=None):
    """读取 [source] 段，返回 (正查表, 反查表)。

    正查表：平台名(小写) -> 写入值
    反查表：写入值       -> 原始平台名（用于还原展示）

    读取前会先 ensure_source_codes()，保证空值/缺项被自动补全。
    """
    import configparser

    path = ini_path or CONFIG_FILE
    fwd, rev = {}, {}
    if not os.path.exists(path):
        return fwd, rev

    ensure_source_codes(path)          # 缺失项自动填写并回写
    try:
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = lambda s: s        # 保留键名大小写
        cfg.read(path, encoding='utf-8')
        if not cfg.has_section('source'):
            return fwd, rev
        for name, val in cfg.items('source'):
            name = str(name or '').strip()
            val = str(val or '').strip()
            if not name or not val:
                continue                     # 留空 = 不替换，写明文
            fwd[name.casefold()] = val
            rev.setdefault(val, name)
    except Exception as e:
        logger.warning(f'读取 {path} 的 [source] 段失败：{e}')
    return fwd, rev


SOURCE_MAP, SOURCE_REVERSE = _load_source_map()

# 来源所在列（0-based），取自表头，避免列顺序调整后错位
try:
    SOURCE_INDEX = XLSX_HEADERS.index('来源')
except ValueError:
    SOURCE_INDEX = 1


def encrypt_source(text):
    """把来源换成 [source] 段里配置的值；未配置则原样返回明文。

    函数名沿用旧名（各采集类与 BaseSpider 都在调用），实际做的是查表替换：
        [source]
        boss直聘 = xxxx   ->  「来源」列写入 xxxx
    """
    text = str(text or '')
    if not text:
        return text
    return SOURCE_MAP.get(text.strip().casefold(), text)


def decrypt_source(code):
    """把写入表格的值还原成原始平台名；查不到时原样返回。"""
    code = str(code or '')
    if not code:
        return code
    return SOURCE_REVERSE.get(code.strip(), code)



# ==================== 单元格文本清洗 ====================
# openpyxl 只接受 \t(0x09) / \n(0x0A) / \r(0x0D) 三个控制字符，
# 其余 0x00-0x1F 会抛 IllegalCharacterError（形如
# "xxx cannot be used in worksheets."），整批写入失败。
# 岗位描述来自网页/接口，常混入 0x0B 垂直制表符等不可见字符，必须清掉。
ILLEGAL_CHARS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')


def clean_cell_value(value):
    """去掉 Excel 不接受的控制字符；非字符串原样返回。"""
    if not isinstance(value, str):
        return value
    if ILLEGAL_CHARS_RE.search(value):
        return ILLEGAL_CHARS_RE.sub('', value)
    return value


def clean_row_values(row):
    """清洗整行；没有任何非法字符时直接返回原对象（零拷贝）。

    ws.append 与 ws.cell 都要求内容合法，所有写盘路径都应经过这里。
    """
    fixed = None
    for i, value in enumerate(row):
        if not isinstance(value, str):
            continue
        if not ILLEGAL_CHARS_RE.search(value):
            continue
        if fixed is None:
            fixed = list(row)
        fixed[i] = ILLEGAL_CHARS_RE.sub('', value)
    return fixed if fixed is not None else row


# ==================== HTTPS 证书配置 ====================
# 个别站点（如国聘 gp-api.iguopin.com）用的是国内 CA（沃通 WoTrus）签发的证书，
# 某些环境的 CA 库不含其根证书 → SSLCertVerificationError。
# 这里显式指定 certifi 的 CA 包，并在创建会话时把系统证书库也合并进去，
# 兼容性比 requests 默认行为更好。
#
# 想用自定义 CA（比如公司内网代理）：把 CA_BUNDLE 设为 .pem 路径即可。
# 万不得已要跳过校验：把 VERIFY_SSL 改成 False（不安全，仅临时排查用）。
CA_BUNDLE = None          # None = 自动（certifi + 系统证书库）
VERIFY_SSL = True


def ca_bundle_path():
    """返回可用的 CA 包路径；拿不到时返回 None（交给 requests 默认处理）。"""
    if CA_BUNDLE:
        return CA_BUNDLE
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def create_session():
    """创建带统一证书配置的 requests.Session。

    在 certifi 的 CA 基础上追加系统证书库，避免因缺少某个根证书导致握手失败。
    """
    s = requests.Session()
    s.verify = ca_bundle_path() if VERIFY_SSL else False

    path = ca_bundle_path()
    if VERIFY_SSL and path and os.path.exists(path):
        try:
            ctx = ssl.create_default_context(cafile=path)
            # 追加系统证书库（Windows 证书存储 / Linux ca-certificates）
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
            adapter = requests.adapters.HTTPAdapter()
            original_init = adapter.init_poolmanager

            def init_poolmanager(connections, maxsize=10, block=False, **kwargs):
                kwargs.setdefault('ssl_context', ctx)
                return original_init(connections, maxsize, block, **kwargs)

            adapter.init_poolmanager = init_poolmanager
            s.mount('https://', adapter)
        except Exception as e:
            logger.warning('配置 HTTPS 证书库失败，使用 requests 默认设置：%s' % e)
    return s


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


def read_all_job_ids(data_file):
    """读取表格里**历史上全部**岗位编号（不限日期），返回 set。

    只读「岗位编号」一列，几万行也很快；用于「只要没采过的岗位」这类筛选。
    文件不存在或编号列为空时返回空集合。
    """
    if not data_file or not os.path.exists(data_file) or ID_COLUMN <= 0:
        return set()
    wb = None
    ids = set()
    try:
        wb = load_workbook(data_file, read_only=True)
        ws = wb.active
        for (value,) in ws.iter_rows(min_col=ID_COLUMN, max_col=ID_COLUMN,
                                     min_row=2, values_only=True):
            if value is None:
                continue
            key = str(value).strip()
            if key:
                ids.add(key)
    except Exception as e:
        logger.error('读取历史岗位编号失败（%s）：%s'
                     % (os.path.basename(data_file), e))
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass
    return ids


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

    web_name = ''               # 原始来源名（如 智联招聘），日志与明文都用它
    source_name = ''            # 同 web_name，加密前的明文（便于代码里直接引用）
    source_code = ''            # 加密后的来源，写入表格「来源」列
    SAVE_INTERVAL = 10          # 两次写盘的最小间隔（秒），避免每页都重写整本 xlsx

    # 去重方式：True=按岗位编号去重（默认），False=按整行内容去重（旧逻辑，兜底）
    DEDUP_BY_ID = True
    # 遇到已存在的岗位编号时是否更新已有行（由界面「更新重复岗位」开关控制）
    UPDATE_DUPLICATE = False

    # 当前任务状态（由 run 设置）
    _pause_event = None
    # 运行状态探针：存布尔值或可调用对象（如 lambda: panel.is_running）
    _running_probe = None
    _save_ts = 0.0
    _saved_path = None          # 实际写入路径（被 Excel 占用时会变成时间戳文件）
    _id_index = None            # 岗位编号 -> 工作表行号
    _update_count = 0           # 本轮更新了多少条重复岗位

    def __init_subclass__(cls, **kwargs):
        """子类定义时把 web_name 加密一次，之后每行直接用。

        source_name : 原始来源明文（智联招聘），仅用于日志/排查
        source_code : 加密后的字符串，写入表格「来源」列
        """
        super().__init_subclass__(**kwargs)
        if cls.web_name and not cls.__dict__.get('source_code'):
            cls.source_name = cls.web_name
            cls.source_code = encrypt_source(cls.web_name)

    @classmethod
    def source_plain(cls, value):
        """把表格里的来源密文还原成原始来源（供查看/导出核对）。"""
        return decrypt_source(value)

    # ==================== 运行状态 ====================

    @classmethod
    def _begin_run(cls, pause_event, is_running, update_duplicate=None):
        """开始一轮采集前重置状态。

        update_duplicate: None 表示沿用类属性；True/False 覆盖本次行为。
        """
        cls._pause_event = pause_event
        cls._running_probe = is_running
        cls._save_ts = 0.0
        cls._saved_path = None
        # 注意：不要重置 _id_index。它由 set_column_style 建立、
        # 由 _append_rows 增量维护，生命周期跟随工作簿而非一轮采集；
        # 在这里清空会导致「更新重复岗位」永远找不到目标行。
        cls._update_count = 0
        if update_duplicate is not None:
            cls.UPDATE_DUPLICATE = bool(update_duplicate)

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
    def load_existing_ids(cls, data_file):
        """读取历史上全部岗位编号，用于「只要没采过的岗位」筛选。"""
        return read_all_job_ids(data_file)

    @classmethod
    def set_column_style(cls, data_file):
        """打开工作簿并写好表头样式，返回 (wb, ws)。"""
        wb, ws = prepare_workbook(data_file)
        # 建立「岗位编号 -> 行号」索引，供更新重复岗位时定位
        cls._id_index = cls._scan_id_index(ws)
        return wb, ws

    @staticmethod
    def _scan_id_index(ws):
        """扫描工作表第二列起，建立 岗位编号 -> Excel 行号 的映射。"""
        index = {}
        if ws is None or ID_COLUMN <= 0:
            return index
        for r in range(2, ws.max_row + 1):
            val = ws.cell(row=r, column=ID_COLUMN).value
            if val is None:
                continue
            key = str(val).strip()
            if key:
                index[key] = r
        return index

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
    def _row_key(cls, row):
        """计算去重键。

        默认用「岗位编号」列；编号为空时退回整行内容（避免空编号全部被合并）。
        """
        if cls.DEDUP_BY_ID and ID_COLUMN > 0:
            idx = ID_COLUMN - 1
            if idx < len(row):
                job_id = str(row[idx] or '').strip()
                if job_id:
                    return ('id', job_id)
        return ('row', tuple(str(v) for v in row[1:]))

    @classmethod
    def init_seen(cls, yesterday_data):
        """把「昨日/今日已入库数据」转成与 _row_key 一致的键集合。

        read_recent_rows() 返回的是**去掉采集日期列**的行，而 _row_key
        是按完整行（含采集日期）取索引的。若直接把原始元组塞进 seen，
        键格式不一致（('智联招聘','四川',…) vs ('id','CC123')），
        会导致同一天重复运行把已采过的岗位再写一遍。
        这里补回一个日期占位，让两类键对齐。
        """
        seen = set()
        for r in (yesterday_data or []):
            if not r:
                continue
            seen.add(cls._row_key([''] + list(r)))
        return seen

    @classmethod
    def _in_history(cls, key):
        """该去重键是否已存在于工作表（不限日期）。

        只按岗位编号判断（DEDUP_BY_ID 模式）。_id_index 由
        set_column_style 扫描全表建立，因此跨天也能认出同一岗位，
        避免「隔天再采同一岗位 → 表格里出现重复行」。
        """
        return (key[0] == 'id' and bool(cls._id_index)
                and key[1] in cls._id_index)

    @classmethod
    def _append_rows(cls, rows, all_rows, seen, ws=None, write=True, on_data=None,
                     on_update=None):
        """按岗位编号去重后写入工作表并回调。

        - 写入前清掉 Excel 不接受的控制字符（否则 openpyxl 抛
          IllegalCharacterError，整批数据都写不进去）
        - 新岗位：追加到表尾
        - 重复岗位（本轮已见 或 历史表里已有）：UPDATE_DUPLICATE=True 时
          覆盖已有行（含采集日期），否则直接跳过
        返回本次新增条数（不含更新数，更新数见 cls._update_count）
        """
        count = 0
        for row in rows:
            # 先清洗再去重，避免带不可见字符的行绕过编号比对
            row = clean_row_values(row)
            key = cls._row_key(row)

            if key in seen or cls._in_history(key):
                # 重复岗位：按开关决定是否刷新
                if cls.UPDATE_DUPLICATE and write and ws is not None:
                    if cls._overwrite_row(ws, row):
                        cls._update_count += 1
                        if on_update is not None:
                            on_update(row)
                continue

            seen.add(key)
            count += 1
            all_rows.append(row)
            if write and ws is not None:
                ws.append(row)
                # 记录新行位置，便于后续重复时覆盖
                if cls._id_index is not None and ID_COLUMN > 0:
                    job_id = str(row[ID_COLUMN - 1] or '').strip()
                    if job_id:
                        cls._id_index[job_id] = ws.max_row
            if on_data is not None:
                on_data(row)
        return count

    @classmethod
    def _overwrite_row(cls, ws, row):
        """用新行覆盖「岗位编号」相同的工作表行；找不到则返回 False。"""
        if ID_COLUMN <= 0:
            return False
        job_id = str(row[ID_COLUMN - 1] or '').strip()
        if not job_id:
            return False
        target = (cls._id_index or {}).get(job_id)
        if not target:
            return False
        for col, value in enumerate(row, 1):
            ws.cell(row=target, column=col, value=clean_cell_value(value))
        return True

    @classmethod
    def _finish_message(cls, added, stopped=False, failed=0):
        """统一的结束提示文案。"""
        suffix = f'，{failed} 个来源失败' if failed else ''
        updated = getattr(cls, '_update_count', 0)
        extra = f'，更新 {updated} 条重复岗位' if updated else ''
        if stopped:
            return f'{cls.web_name}采集已停止（新增 {added} 条{extra}{suffix}）'
        return f'{cls.web_name}采集完成（新增 {added} 条{extra}{suffix}）'


# ==================== 可视化界面 ====================
# 主题与布局参数来自 config/ui.json，缺失时用内置默认值，避免任何硬编码颜色散落各处。
_UI_DEFAULT = {
    'themename': 'flatly',
    'window': {'width': 1400, 'height': 880,
               'min_width': 1120, 'min_height': 720},
    'font': {'family': '微软雅黑', 'size': 10, 'size_small': 9,
             'size_title': 16, 'size_card': 18, 'mono': 'Consolas'},
    'colors': {'header_bg': '#1e293b', 'header_bg2': '#334155',
               'header_fg': '#f8fafc', 'header_sub': '#94a3b8',
               'bg': '#f1f5f9', 'card_bg': '#ffffff', 'border': '#e2e8f0',
               'text': '#0f172a', 'muted': '#64748b', 'accent': '#2563eb',
               'success': '#059669', 'warning': '#d97706', 'danger': '#dc2626',
               'row_odd': '#ffffff', 'row_even': '#f8fafc',
               'log_bg': '#0f172a', 'log_fg': '#cbd5e1',
               'log_info': '#94a3b8', 'log_warn': '#fbbf24',
               'log_error': '#f87171'},
    'layout': {'pad': 12, 'gap': 8, 'row_height': 28,
               'log_height': 7, 'log_collapsed': True},
}


def _deep_merge(base, override):
    """递归合并配置字典，override 优先。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


UI = _deep_merge(_UI_DEFAULT, load_config('ui.json', {}) or {})
UI_FONT = UI['font']
UI_COLOR = UI['colors']
UI_LAYOUT = UI['layout']

# ttkbootstrap 提供现代主题；缺失时退回原生 ttk（功能不受影响，仅外观朴素）
try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y, W, E, N, S, END
    _HAS_TB = True
except ImportError:
    tb = None
    _HAS_TB = False
    BOTH, LEFT, RIGHT, X, Y, W, E, N, S, END = (
        'both', 'left', 'right', 'x', 'y', 'w', 'e', 'n', 's', 'end')


def _font(size_key='size', bold=False):
    size = UI_FONT.get(size_key, 10)
    return (UI_FONT['family'], size, 'bold') if bold else (UI_FONT['family'], size)


def _make_window(title):
    """创建主窗口：优先 ttkbootstrap 主题窗口。"""
    if _HAS_TB:
        win = tb.Window(themename=UI['themename'])
        win.title(title)
        w = UI['window']
        win.geometry('%dx%d' % (w['width'], w['height']))
        win.minsize(w['min_width'], w['min_height'])
        win.configure(bg=UI_COLOR['bg'])
        style = win.style
        _apply_theme_to_style(style)
        return win
    win = tk.Tk()
    win.title(title)
    w = UI['window']
    win.geometry('%dx%d' % (w['width'], w['height']))
    win.minsize(w['min_width'], w['min_height'])
    win.configure(bg=UI_COLOR['bg'])
    return win


def _apply_theme_to_style(style):
    """统一 Treeview / 标签页等基础控件的外观。"""
    row_h = UI_LAYOUT['row_height']
    style.configure('Treeview',
                    rowheight=row_h,
                    font=_font('size'),
                    background=UI_COLOR['card_bg'],
                    fieldbackground=UI_COLOR['card_bg'],
                    foreground=UI_COLOR['text'],
                    borderwidth=0)
    style.configure('Treeview.Heading',
                    font=_font('size_small', bold=True),
                    background='#eef2f7',
                    foreground='#475569',
                    relief='flat',
                    borderwidth=0,
                    padding=(10, 9))
    style.map('Treeview.Heading',
              background=[('active', '#e2e8f0')],
              foreground=[('active', UI_COLOR['accent'])])
    style.map('Treeview',
              background=[('selected', UI_COLOR['accent'])],
              foreground=[('selected', '#ffffff')])
    try:
        style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    except Exception:
        pass

    # 标签页：选中项用主色填充，未选中项浅灰
    try:
        style.configure('TNotebook',
                        background=UI_COLOR['bg'],
                        borderwidth=0,
                        tabmargins=(UI_LAYOUT['pad'], 8, 0, 0))
        style.configure('TNotebook.Tab',
                        font=_font('size', bold=True),
                        padding=(22, 10),
                        background='#e2e8f0',
                        foreground=UI_COLOR['muted'],
                        borderwidth=0)
        style.map('TNotebook.Tab',
                  background=[('selected', UI_COLOR['accent'])],
                  foreground=[('selected', '#ffffff')])
    except Exception:
        pass


class CellTooltip:
    """表格单元格悬浮提示：字段内容被列宽截断时，悬浮显示完整文本。

    用 Toplevel 叠在光标下方（overrideredirect 无边框），不会抢焦点、
    不进入任务栏。内容较短（单元格本身能完整显示）时不弹出。
    """

    MAX_CHARS = 1200          # 超过这个长度截断，避免超大描述撑爆屏幕
    SHOW_DELAY = 350          # 悬停多少毫秒后弹出（避免划过时闪个不停）
    WRAP = 480                # 提示框内自动换行宽度（像素）

    def __init__(self, tree):
        self.tree = tree
        self.win = None
        self.label = None
        self._after_id = None
        self._text = ''

    # ---------- 显示 ----------
    def show(self, text, x, y):
        """在 (x, y) 处显示提示；重复内容不重建窗口。"""
        if text == self._text and self.win is not None:
            return
        self._text = text

        if self.win is None:
            self.win = tk.Toplevel(self.tree)
            self.win.withdraw()
            self.win.overrideredirect(True)      # 无标题栏
            try:
                self.win.attributes('-topmost', True)
            except Exception:
                pass
            frame = tk.Frame(self.win, bg=UI_COLOR['border'], padx=1, pady=1)
            frame.pack(fill=BOTH, expand=True)
            self.label = tk.Label(
                frame, text='', justify=LEFT, anchor=W,
                bg='#fffbeb', fg=UI_COLOR['text'],
                font=_font('size_small'),
                padx=8, pady=6, wraplength=self.WRAP)
            self.label.pack(fill=BOTH, expand=True)

        self.label.config(text=text)
        self.win.update_idletasks()

        # 防止超出屏幕右下角
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = min(x, max(0, sw - w - 8))
        y = min(y, max(0, sh - h - 8))

        self.win.geometry('+%d+%d' % (x, y))
        self.win.deiconify()

    def schedule(self, text, x, y):
        """延时弹出；期间鼠标移走会被 cancel() 取消。"""
        self.cancel()
        self._after_id = self.tree.after(
            self.SHOW_DELAY, lambda: self.show(text, x, y))

    def cancel(self):
        if self._after_id is not None:
            try:
                self.tree.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def hide(self):
        self.cancel()
        self._text = ''
        if self.win is not None:
            try:
                self.win.withdraw()
            except Exception:
                pass


class BaseSpiderGUI:
    """爬虫可视化基类（现代卡片式界面）。

    提供：开始/暂停/停止/刷新/导出、进度与统计卡片、数据表格、分页、
    搜索过滤、列显隐、行详情、可折叠日志。子类只需实现 spider_task()。
    """

    def __init__(self, title='数据采集系统', spider_name='', parent=None,
                 show_header=None):
        if parent is None:
            self.root = _make_window(title)
            self._owns_root = True
            self.container = self.root
            # 独立窗口默认显示标题栏
            self.show_header = True if show_header is None else show_header
        else:
            self.root = parent.winfo_toplevel()
            self._owns_root = False
            self.container = parent
            # 嵌入页签时不显示标题栏（页签本身已标明平台，标题会重复）
            self.show_header = False if show_header is None else show_header

        # 是否用新数据覆盖已存在的重复岗位（由工具栏开关控制）
        self.update_duplicate = False

        self.spider_name = spider_name or title

        # 运行状态
        self.is_running = False
        self.is_paused = False
        self.ui_state = 'idle'
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.spider_thread = None

        # 统计
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self.current_city = ''
        self.current_page_no = 0
        self.start_time = None
        self._task_total = 0

        # 表格
        self.all_rows = []
        self.page_size = 100
        self.current_page = 0
        self._refresh_pending = False
        self._refresh_timer_id = None
        self._filter_text = ''
        self._auto_scroll = None
        self._log_visible = not UI_LAYOUT.get('log_collapsed', True)
        self._log_counter = 0
        self._log_buffer = []              # 待刷新的日志行缓冲
        self._log_flush_scheduled = False

        self._build_ui()

    # ==================== UI 构建 ====================
    def _build_ui(self):
        root_bg = UI_COLOR['bg']

        self._body = tk.Frame(self.container, bg=root_bg)
        self._body.pack(fill=BOTH, expand=True)

        # pack 顺序很关键：先占住 top/bottom 的固定区域，
        # 最后放会 expand 的表格，否则状态栏会被表格挤出可视区。
        if self.show_header:
            self._build_header()        # top（仅独立窗口）
        self._build_status_bar()    # bottom（先占位）
        self._build_log_panel()     # bottom（状态栏之上）
        self._build_pagination()    # bottom（日志之上）
        self._build_toolbar()       # top
        self._build_stats()         # top
        self._build_table()         # top + expand（吃掉剩余空间）

    # ---------- 顶部标题栏（仅独立窗口） ----------
    def _build_header(self):
        bar = tk.Frame(self._body, bg=UI_COLOR['header_bg'], height=48)
        bar.pack(fill=X, side='top')
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=UI_COLOR['header_bg'])
        left.pack(side=LEFT, padx=(UI_LAYOUT['pad'], 0))

        strip = tk.Frame(left, bg=UI_COLOR['accent'], width=4, height=24)
        strip.pack(side=LEFT, padx=(0, 10))
        strip.pack_propagate(False)

        tk.Label(left, text=self.spider_name, bg=UI_COLOR['header_bg'],
                 fg=UI_COLOR['header_fg'], font=_font('size_title', bold=True)
                 ).pack(side=LEFT)

        self.lbl_time = tk.Label(bar, text='', bg=UI_COLOR['header_bg'],
                                 fg=UI_COLOR['header_sub'],
                                 font=_font('size_small'))
        self.lbl_time.pack(side=RIGHT, padx=(0, UI_LAYOUT['pad']))

        self._update_clock()

    # ---------- 卡片工具 ----------
    def _card(self, parent, title=None, **pack_kw):
        """创建一个带边框的白底卡片，返回内部可用容器。"""
        outer = tk.Frame(parent, bg=UI_COLOR['border'])
        outer.pack(**pack_kw)
        inner = tk.Frame(outer, bg=UI_COLOR['card_bg'])
        inner.pack(fill=BOTH, expand=True, padx=1, pady=1)
        if title:
            head = tk.Frame(inner, bg=UI_COLOR['card_bg'])
            head.pack(fill=X, padx=12, pady=(10, 0))
            tk.Label(head, text=title, bg=UI_COLOR['card_bg'],
                     fg=UI_COLOR['muted'], font=_font('size_small', bold=True)
                     ).pack(side=LEFT)
            tk.Frame(inner, bg=UI_COLOR['border'], height=1).pack(
                fill=X, padx=12, pady=(8, 0))
        return inner

    # ---------- 操作工具栏 ----------
    BTN_STYLES = {
        # key: (正常底色, 正常字色, 禁用底色, 禁用字色)
        'success': ('#059669', '#ffffff', '#cbd5e1', '#94a3b8'),
        'warning': ('#d97706', '#ffffff', '#cbd5e1', '#94a3b8'),
        'danger':  ('#dc2626', '#ffffff', '#cbd5e1', '#94a3b8'),
        'info':    ('#0891b2', '#ffffff', '#cbd5e1', '#94a3b8'),
    }

    def _toolbar_button(self, parent, text, kind, cmd, width=10):
        """手动控制配色的按钮。

        不用 ttkbootstrap 的 Button：它的禁用态由主题统一灰化、且会在每次
        config(bootstyle=...) 时重置，导致「采集中」等状态几乎看不见。
        """
        bg, fg, dbg, dfg = self.BTN_STYLES[kind]
        btn = tk.Button(parent, text=text, command=cmd, width=width,
                        font=_font('size', bold=True), relief='flat', bd=0,
                        bg=bg, fg=fg, activebackground=bg,
                        activeforeground=fg, disabledforeground=dfg,
                        cursor='hand2', padx=10, pady=6)
        btn._kind = kind
        btn._dbg = dbg
        btn._dfg = dfg
        return btn

    def _set_button_state(self, btn, state):
        """切换按钮可用性并同步配色（禁用态仍是可读的灰底灰字）。"""
        btn.config(state=state)
        if state == 'disabled':
            btn.config(bg=btn._dbg, fg=btn._dfg)
        else:
            bg, fg, _dbg, _dfg = self.BTN_STYLES[btn._kind]
            btn.config(bg=bg, fg=fg)

    def _build_toolbar(self):
        pad = UI_LAYOUT['pad']
        card = self._card(self._body, fill=X, padx=pad, pady=(pad, 0))
        row = tk.Frame(card, bg=UI_COLOR['card_bg'])
        row.pack(fill=X, padx=12, pady=10)

        self.btn_start = self._toolbar_button(row, '开始采集', 'success',
                                              self._on_start, 11)
        self.btn_start.pack(side=LEFT, padx=(0, 8))

        self.btn_pause = self._toolbar_button(row, '暂停', 'warning',
                                              self._on_pause, 9)
        self.btn_pause.pack(side=LEFT, padx=(0, 8))

        self.btn_stop = self._toolbar_button(row, '停止', 'danger',
                                             self._on_stop, 9)
        self.btn_stop.pack(side=LEFT)

        tk.Frame(row, bg=UI_COLOR['border'], width=1, height=24).pack(
            side=LEFT, padx=14, fill=Y)

        self.btn_refresh = self._toolbar_button(row, '刷新列表', 'info',
                                                self._on_refresh, 10)
        self.btn_refresh.pack(side=LEFT, padx=(0, 8))

        # 「更新重复岗位」开关：按岗位编号去重时，是否用新数据覆盖已有行
        # 用大号字体 + 强调色，避免与普通文案混在一起看不清
        self._update_dup = tk.BooleanVar(value=False)
        self.chk_update = tk.Checkbutton(
            row, text='更新重复岗位', variable=self._update_dup,
            bg=UI_COLOR['card_bg'], fg=UI_COLOR['accent'],
            activebackground=UI_COLOR['card_bg'],
            activeforeground=UI_COLOR['accent'],
            selectcolor=UI_COLOR['card_bg'],
            font=_font('size', bold=True), bd=0, highlightthickness=0,
            padx=10, pady=5, cursor='hand2')
        self.chk_update.pack(side=LEFT, padx=(12, 0))

        # 右侧：状态胶囊 + 自动滚动 + 日志开关
        self._state_pill = tk.Frame(row, bg=UI_COLOR['bg'])
        self._state_pill.pack(side=RIGHT, padx=(16, 0))
        self.lbl_header_state = tk.Label(
            self._state_pill, text='● 就绪', bg=UI_COLOR['bg'],
            fg='#16a34a', font=_font('size_small'),
            padx=10, pady=3)
        self.lbl_header_state.pack()

        self._auto_scroll = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text='自动滚动', variable=self._auto_scroll,
                       bg=UI_COLOR['card_bg'], fg=UI_COLOR['muted'],
                       activebackground=UI_COLOR['card_bg'],
                       selectcolor=UI_COLOR['card_bg'],
                       font=_font('size_small'), bd=0,
                       highlightthickness=0).pack(side=RIGHT, padx=(0, 12))

        self.btn_log = tk.Button(
            row, text='显示日志' if not self._log_visible else '隐藏日志',
            command=self._toggle_log, font=_font('size_small'),
            bg=UI_COLOR['card_bg'], fg=UI_COLOR['accent'],
            activebackground=UI_COLOR['card_bg'], relief='flat',
            bd=0, cursor='hand2')
        self.btn_log.pack(side=RIGHT, padx=(0, 16))

        self._set_ui_state('idle')

    # ---------- 统计卡片 ----------
    def _build_stats(self):
        """进度条与采集统计合并为一行，节省纵向空间。"""
        pad = UI_LAYOUT['pad']
        card = self._card(self._body, fill=X, padx=pad,
                          pady=(UI_LAYOUT['gap'], 0))

        row = tk.Frame(card, bg=UI_COLOR['card_bg'])
        row.pack(fill=X, padx=12, pady=8)

        # 用 grid 两列各 weight=1，让「进度区」与「统计区」各占 50%
        row.grid_columnconfigure(0, weight=1, uniform='half')
        row.grid_columnconfigure(1, weight=1, uniform='half')

        # ---------- 左半：进度条 + 百分比 ----------
        left = tk.Frame(row, bg=UI_COLOR['card_bg'])
        left.grid(row=0, column=0, sticky='ew', padx=(0, 12))

        if _HAS_TB:
            self.progress = tb.Progressbar(
                left, mode='determinate', bootstyle='success-striped',
                maximum=100)
        else:
            self.progress = ttk.Progressbar(left, mode='determinate',
                                            maximum=100)
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))

        self.lbl_progress = tk.Label(left, text='0%', width=4,
                                     bg=UI_COLOR['card_bg'],
                                     fg=UI_COLOR['accent'],
                                     font=_font('size', bold=True))
        self.lbl_progress.pack(side=LEFT)

        # ---------- 右半：统计 + 当前任务 ----------
        right = tk.Frame(row, bg=UI_COLOR['card_bg'])
        right.grid(row=0, column=1, sticky='ew')

        self._metric_labels = {}
        specs = [
            ('count', '已采集', '0', UI_COLOR['accent']),
            ('error', '错误', '0', UI_COLOR['danger']),
            ('elapsed', '耗时', '0s', UI_COLOR['muted']),
        ]
        for key, name, init, color in specs:
            tk.Label(right, text=name, bg=UI_COLOR['card_bg'],
                     fg=UI_COLOR['muted'], font=_font('size_small')
                     ).pack(side=LEFT, padx=(0, 4))
            lbl = tk.Label(right, text=init, bg=UI_COLOR['card_bg'],
                           fg=color, font=_font('size', bold=True))
            lbl.pack(side=LEFT, padx=(0, 16))
            self._metric_labels[key] = lbl

        # 当前任务
        tk.Frame(right, bg=UI_COLOR['border'], width=1, height=18).pack(
            side=LEFT, fill=Y, padx=(0, 12))
        tk.Label(right, text='当前', bg=UI_COLOR['card_bg'],
                 fg=UI_COLOR['muted'], font=_font('size_small')
                 ).pack(side=LEFT, padx=(0, 6))
        self.lbl_current = tk.Label(right, text='—', bg=UI_COLOR['card_bg'],
                                    fg=UI_COLOR['text'],
                                    font=_font('size', bold=True), anchor=W)
        self.lbl_current.pack(side=LEFT, fill=X, expand=True)

    # ---------- 数据表格 ----------
    def _build_table(self):
        pad = UI_LAYOUT['pad']
        card = self._card(self._body, fill=BOTH, expand=True,
                          padx=pad, pady=(UI_LAYOUT['gap'], 0))

        table_wrap = tk.Frame(card, bg=UI_COLOR['card_bg'])
        table_wrap.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._col_defs = list(TABLE_COLUMNS)
        col_keys = ['id'] + [c['key'] for c in self._col_defs]

        self.tree = ttk.Treeview(table_wrap, columns=col_keys,
                                 show='headings', height=16)
        self.tree.heading('#0', text='')
        self.tree.column('#0', width=0, stretch=False)

        self.tree.heading('id', text='#', anchor='center')
        self.tree.column('id', width=48, minwidth=44, anchor='center',
                         stretch=False)

        for col in self._col_defs:
            self.tree.heading(col['key'], text=col['header'], anchor=W)
            self.tree.column(col['key'], width=col.get('width', 110),
                             minwidth=44, anchor=W)

        self.tree.tag_configure('odd', background=UI_COLOR['row_odd'])
        self.tree.tag_configure('even', background=UI_COLOR['row_even'])

        vsb = ttk.Scrollbar(table_wrap, orient='vertical',
                            command=self.tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient='horizontal',
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        self.tree.bind('<MouseWheel>',
                       lambda e: self.tree.yview_scroll(
                           int(-1 * (e.delta / 120)), 'units'))
        self.tree.bind('<Double-1>', self._on_row_double_click)
        self.tree.bind('<Button-3>', self._on_table_right_click)

        # ---------- 单元格悬浮提示：字段内容过长时显示全文 ----------
        self._tip = CellTooltip(self.tree)
        self.tree.bind('<Motion>', self._on_cell_hover, add='+')
        self.tree.bind('<Leave>', lambda e: self._tip.hide(), add='+')
        self.tree.bind('<ButtonPress>', lambda e: self._tip.hide(), add='+')
        self.tree.bind('<MouseWheel>',
                       lambda e: self._tip.hide(), add='+')
        self._hover_cell = None

        self._apply_column_visibility()

    # ---------- 单元格悬浮提示 ----------
    def _on_cell_hover(self, event):
        """鼠标在单元格上停留时，若文本被截断则显示完整内容。

        只在「确实放不下」时提示，避免正常短文本也弹气泡造成干扰。
        """
        tree = self.tree
        if not hasattr(self, '_tip'):
            return

        row_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not row_id or not col:
            self._tip.hide()
            self._hover_cell = None
            return

        cell = (row_id, col)
        if cell == self._hover_cell:
            return                      # 还在同一格，保持现状
        self._hover_cell = cell

        # 取出单元格文本
        values = tree.item(row_id, 'values')
        try:
            idx = int(col.lstrip('#')) - 1
        except ValueError:
            self._tip.hide()
            return
        if idx < 0 or idx >= len(values):
            self._tip.hide()
            return
        text = str(values[idx] or '')
        if not text.strip():
            self._tip.hide()
            return

        # 判断是否被列宽截断：用字体实测文本宽度 vs 该列宽度
        col_key = tree['columns'][idx] if idx < len(tree['columns']) else ''
        try:
            col_width = tree.column(col_key, 'width')
        except Exception:
            col_width = 0
        if col_width <= 0 or self._text_width(text) <= col_width - 12:
            self._tip.hide()            # 能完整显示，不打扰
            return

        # 超长内容截断，避免超大提示框
        shown = text
        if len(shown) > self._tip.MAX_CHARS:
            shown = shown[:self._tip.MAX_CHARS] + '\n……（共 %d 字，已截断）' % len(text)

        self._tip.schedule(shown, event.x_root + 14, event.y_root + 18)

    def _text_width(self, text):
        """按表格字体估算文本像素宽度（多行取最长一行）。"""
        if not text:
            return 0
        try:
            from tkinter import font as tkfont
            f = tkfont.Font(font=_font('size'))
            longest = max(text.split('\n'), key=len) if '\n' in text else text
            return f.measure(longest)
        except Exception:
            return len(text) * 8

    # ---------- 分页栏 ----------
    def _build_pagination(self):
        pad = UI_LAYOUT['pad']
        card = self._card(self._body, fill=X, padx=pad,
                          pady=(UI_LAYOUT['gap'], UI_LAYOUT['gap']),
                          side='bottom')
        # 记录外层容器：日志面板重新 pack 时需要用 before= 恢复到它下方
        self._pagination_card = card.master
        row = tk.Frame(card, bg=UI_COLOR['card_bg'])
        row.pack(fill=X, padx=12, pady=8)

        def _btn(parent, text, cmd, state='normal', width=8):
            if _HAS_TB:
                return tb.Button(parent, text=text, command=cmd,
                                 bootstyle='secondary-outline',
                                 width=width, state=state)
            return tk.Button(parent, text=text, command=cmd, width=width,
                             state=state, font=_font('size_small'))

        self.btn_prev = _btn(row, '上一页', self._on_prev_page, 'disabled')
        self.btn_prev.pack(side=LEFT)

        tk.Label(row, text='第', bg=UI_COLOR['card_bg'],
                 fg=UI_COLOR['muted'], font=_font('size_small')
                 ).pack(side=LEFT, padx=(12, 2))
        self.var_page = tk.StringVar(value='1')
        self.ent_page = tk.Entry(row, textvariable=self.var_page, width=5,
                                 justify='center', font=_font('size_small'),
                                 relief='flat', bg=UI_COLOR['bg'],
                                 highlightthickness=1,
                                 highlightbackground=UI_COLOR['border'],
                                 highlightcolor=UI_COLOR['accent'])
        self.ent_page.pack(side=LEFT, ipady=2)
        self.ent_page.bind('<Return>', self._on_jump_page)

        self.lbl_page = tk.Label(row, text='/ 0 页   共 0 条',
                                 bg=UI_COLOR['card_bg'],
                                 fg=UI_COLOR['muted'], font=_font('size_small'))
        self.lbl_page.pack(side=LEFT, padx=(6, 0))

        self.btn_next = _btn(row, '下一页', self._on_next_page, 'disabled')
        self.btn_next.pack(side=LEFT, padx=(12, 0))

        # 每页条数
        tk.Label(row, text='每页', bg=UI_COLOR['card_bg'],
                 fg=UI_COLOR['muted'], font=_font('size_small')
                 ).pack(side=LEFT, padx=(20, 4))
        self.var_page_size = tk.StringVar(value=str(self.page_size))
        combo = ttk.Combobox(row, textvariable=self.var_page_size, width=5,
                             state='readonly', font=_font('size_small'),
                             values=('20', '50', '100', '200', '500'))
        combo.pack(side=LEFT)
        combo.bind('<<ComboboxSelected>>', self._on_page_size_change)

        # 搜索
        tk.Label(row, text='搜索', bg=UI_COLOR['card_bg'],
                 fg=UI_COLOR['muted'], font=_font('size_small')
                 ).pack(side=LEFT, padx=(20, 4))
        self.var_filter = tk.StringVar()
        ent = tk.Entry(row, textvariable=self.var_filter, width=20,
                       font=_font('size_small'), relief='flat',
                       bg=UI_COLOR['bg'], highlightthickness=1,
                       highlightbackground=UI_COLOR['border'],
                       highlightcolor=UI_COLOR['accent'])
        ent.pack(side=LEFT, ipady=2)
        ent.bind('<Return>', lambda e: self._apply_filter())

        if _HAS_TB:
            tb.Button(row, text='筛选', command=self._apply_filter,
                      bootstyle='info-outline', width=6).pack(side=LEFT, padx=(8, 0))
            tb.Button(row, text='清除', command=self._clear_filter,
                      bootstyle='secondary-outline', width=6).pack(side=LEFT, padx=(6, 0))
        else:
            tk.Button(row, text='筛选', command=self._apply_filter,
                      width=6).pack(side=LEFT, padx=(8, 0))
            tk.Button(row, text='清除', command=self._clear_filter,
                      width=6).pack(side=LEFT, padx=(6, 0))

    # ---------- 日志面板 ----------
    def _build_log_panel(self):
        pad = UI_LAYOUT['pad']
        self._log_card = tk.Frame(self._body, bg=UI_COLOR['border'])
        self._log_inner = tk.Frame(self._log_card, bg=UI_COLOR['log_bg'])
        self._log_inner.pack(fill=BOTH, expand=True, padx=1, pady=1)

        head = tk.Frame(self._log_inner, bg=UI_COLOR['log_bg'])
        head.pack(fill=X, padx=12, pady=(8, 0))
        tk.Label(head, text='运行日志', bg=UI_COLOR['log_bg'],
                 fg=UI_COLOR['log_info'],
                 font=_font('size_small', bold=True)).pack(side=LEFT)

        # 清空按钮：用普通 tk.Button 手动控色。
        # ttkbootstrap 的 link 按钮会拦截点击并带 hover 动画，在日志高频
        # 刷新时表现为「点了没反应/卡顿」。
        self.btn_clear_log = tk.Button(
            head, text='清空', command=self._clear_log,
            relief='flat', bd=0, bg=UI_COLOR['log_bg'],
            fg=UI_COLOR['log_info'], activebackground='#1e293b',
            activeforeground=UI_COLOR['log_fg'],
            font=_font('size_small'), cursor='hand2', padx=8, pady=1)
        self.btn_clear_log.pack(side=RIGHT)

        wrap = tk.Frame(self._log_inner, bg=UI_COLOR['log_bg'])
        wrap.pack(fill=BOTH, expand=True, padx=8, pady=(4, 10))

        self.txt_log = tk.Text(
            wrap, height=UI_LAYOUT['log_height'], wrap='none',
            font=(UI_FONT['mono'], UI_FONT['size_small']),
            bg=UI_COLOR['log_bg'], fg=UI_COLOR['log_fg'],
            insertbackground=UI_COLOR['log_fg'], bd=0,
            highlightthickness=0, state='disabled')
        scroll = ttk.Scrollbar(wrap, orient='vertical',
                               command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        self.txt_log.tag_configure('info', foreground=UI_COLOR['log_fg'])
        self.txt_log.tag_configure('warn', foreground=UI_COLOR['log_warn'])
        self.txt_log.tag_configure('error', foreground=UI_COLOR['log_error'])
        self.txt_log.tag_configure('time', foreground=UI_COLOR['log_info'])

        if self._log_visible:
            self._log_card.pack(fill=X, side='bottom',
                                padx=pad, pady=(UI_LAYOUT['gap'], 0))

    def _toggle_log(self):
        """显示/隐藏日志面板。

        注意：pack_forget 会把控件从 pack 顺序中移除，再次 pack 时它会
        被追加到末尾（在 bottom 布局中表现为跑到分页栏上方）。
        必须用 before= 恢复到原来的槽位。
        """
        self._log_visible = not self._log_visible
        if self._log_visible:
            opts = dict(fill=X, side='bottom', padx=UI_LAYOUT['pad'],
                        pady=(UI_LAYOUT['gap'], 0))
            anchor = getattr(self, '_pagination_card', None)
            if anchor is not None:
                opts['before'] = anchor
            self._log_card.pack(**opts)
            self.btn_log.config(text='隐藏日志')
        else:
            self._log_card.pack_forget()
            self.btn_log.config(text='显示日志')

    def _clear_log(self):
        """清空日志面板。

        必须同时重置计数器和待刷新缓冲，否则清空后旧的 after 回调
        会把内容又写回来（表现为「点了没反应」）。
        """
        try:
            self._log_buffer = []
            self._log_counter = 0
            self.txt_log.configure(state='normal')
            self.txt_log.delete('1.0', END)
            self.txt_log.configure(state='disabled')
        except Exception:
            pass

    # ---------- 底部状态栏 ----------
    def _build_status_bar(self):
        """底部状态栏已移除：状态信息统一在看板「当前」和日志中展示。

        保留 lbl_status / lbl_bottom 两个属性（用不可见 Label 占位），
        避免其它模块调用 config(text=...) 时抛异常。
        """
        self._status_bar = None
        holder = tk.Frame(self._body)
        self.lbl_bottom = tk.Label(holder, text='')
        self.lbl_status = tk.Label(holder, text='')

    # ---------- 列显隐 ----------
    def _apply_column_visibility(self):
        shown = ['id'] + [c['key'] for c in self._col_defs
                          if c.get('visible', True)]
        self.tree['displaycolumns'] = shown

    def _on_table_right_click(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        for col in self._col_defs:
            var = tk.BooleanVar(value=col.get('visible', True))
            menu.add_checkbutton(
                label=col['header'], variable=var,
                command=lambda c=col, v=var: self._toggle_column(c, v.get()))
        menu.add_separator()
        menu.add_command(label='全部显示', command=self._show_all_columns)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _toggle_column(self, col, visible):
        col['visible'] = visible
        self._apply_column_visibility()

    def _show_all_columns(self):
        for col in self._col_defs:
            col['visible'] = True
        self._apply_column_visibility()
        self._set_status('已显示全部列')

    # ---------- 行详情 ----------
    def _on_row_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        values = self.tree.item(item, 'values')
        if not values:
            return
        row = values[1:]

        win = tk.Toplevel(self.root)
        win.title('职位详情')
        win.geometry('720x580')
        win.configure(bg=UI_COLOR['bg'])

        head = tk.Frame(win, bg=UI_COLOR['header_bg'], height=48)
        head.pack(fill=X)
        head.pack_propagate(False)
        tk.Label(head, text='职位详情', bg=UI_COLOR['header_bg'],
                 fg=UI_COLOR['header_fg'],
                 font=_font('size', bold=True)).pack(side=LEFT, padx=16)

        body = tk.Frame(win, bg=UI_COLOR['bg'])
        body.pack(fill=BOTH, expand=True, padx=14, pady=12)

        txt = tk.Text(body, wrap='word', font=_font('size'),
                      padx=16, pady=12, bg=UI_COLOR['card_bg'],
                      fg=UI_COLOR['text'], relief='flat',
                      highlightthickness=1,
                      highlightbackground=UI_COLOR['border'])
        sb = ttk.Scrollbar(body, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        for i, col in enumerate(self._col_defs):
            val = row[i] if i < len(row) else ''
            txt.insert(END, '%s\n' % col['header'], 'label')
            txt.insert(END, '%s\n\n' % (val or '—'))
        txt.tag_configure('label', font=_font('size_small', bold=True),
                          foreground=UI_COLOR['muted'])
        txt.configure(state='disabled')

    # ==================== 线程安全 UI 调度 ====================
    def _ui(self, func):
        try:
            self.root.after(0, func)
        except Exception:
            pass

    # ==================== 日志 ====================
    def _log(self, message, level='info'):
        """写文件日志，并缓冲到界面日志面板。

        原实现每条日志都直接操作 4 次 Tk 控件（2 次 insert + see + configure），
        高频输出时会明显卡顿；现改为缓冲 + 定时批量刷新。
        """
        getattr(logger, level, logger.info)('[%s] %s' % (self.spider_name, message))
        if not hasattr(self, 'txt_log'):
            return

        tag = {'error': 'error', 'warning': 'warn', 'warn': 'warn'}.get(level, 'info')
        self._log_buffer.append((time.strftime('%H:%M:%S'), message, tag))
        # 只在没有待刷新任务时排一次，避免堆积大量 after 回调
        if not self._log_flush_scheduled:
            self._log_flush_scheduled = True
            try:
                self.root.after(120, self._flush_log)
            except Exception:
                self._log_flush_scheduled = False

    def _flush_log(self):
        """把缓冲区一次性写入日志面板（单次进入正常态，减少控件操作）。"""
        self._log_flush_scheduled = False
        if not self._log_buffer:
            return
        batch = self._log_buffer
        self._log_buffer = []

        def _apply():
            try:
                self.txt_log.configure(state='normal')
                for ts, msg, tag in batch:
                    self.txt_log.insert(END, '%s ' % ts, 'time')
                    self.txt_log.insert(END, '%s\n' % msg, tag)
                self._log_counter += len(batch)
                # 超过上限时裁掉最早的一批，保持性能
                if self._log_counter > 800:
                    cut = self._log_counter - 600
                    self.txt_log.delete('1.0', '%d.0' % (cut + 1))
                    self._log_counter = 600
                self.txt_log.see(END)
                self.txt_log.configure(state='disabled')
            except Exception:
                pass

        self._ui(_apply)

    # ==================== 时钟 ====================
    def _update_clock(self):
        """独立窗口的标题栏时钟（嵌入页签时由 SpiderGUI 统一显示）。"""
        lbl = getattr(self, 'lbl_time', None)
        if lbl is None:
            return
        try:
            lbl.config(text=time.strftime('%Y-%m-%d  %H:%M:%S'))
            self.root.after(1000, self._update_clock)
        except Exception:
            pass

    # ==================== 按钮状态机 ====================
    def _set_ui_state(self, state):
        """idle / running / paused / stopping —— 统一控制按钮可用性与配色。"""
        self.ui_state = state

        # 各状态下三个控制按钮的 (可用性, 文案, 配色类型)
        spec = {
            'idle': (('normal', '开始采集', 'success'),
                     ('disabled', '暂停', 'warning'),
                     ('disabled', '停止', 'danger')),
            'running': (('disabled', '采集中', 'success'),
                        ('normal', '暂停', 'warning'),
                        ('normal', '停止', 'danger')),
            'paused': (('disabled', '采集中', 'success'),
                       ('normal', '继续', 'info'),
                       ('normal', '停止', 'danger')),
            'stopping': (('disabled', '停止中', 'success'),
                         ('disabled', '暂停', 'warning'),
                         ('disabled', '停止', 'danger')),
        }[state]

        for btn, (st, text, kind) in zip(
                (self.btn_start, self.btn_pause, self.btn_stop), spec):
            btn._kind = kind
            try:
                btn.config(text=text)
            except Exception:
                pass
            self._set_button_state(btn, st)

        # 刷新按钮：采集期间也可用（此时从内存渲染，不读文件）
        self._set_button_state(self.btn_refresh, 'normal')

        # 「更新重复岗位」开关在采集中不可改，避免中途切换导致行为不一致
        try:
            self.chk_update.config(
                state='normal' if state == 'idle' else 'disabled')
        except Exception:
            pass

        # 顶部状态胶囊（就绪=绿色，与「采集中」一致，避免灰色显得像禁用）
        label, color = {
            'idle': ('就绪', '#16a34a'),
            'running': ('采集中', '#34d399'),
            'paused': ('已暂停', UI_COLOR['log_warn']),
            'stopping': ('停止中', UI_COLOR['log_error']),
        }[state]
        try:
            self.lbl_header_state.config(text='● %s' % label, fg=color)
        except Exception:
            pass
    # ==================== 按钮事件 ====================
    def _on_start(self):
        if self.is_running:
            return

        self.is_running = True
        self.is_paused = False
        self.pause_event.set()
        self.total_count = 0
        self.today_count = 0
        self.error_count = 0
        self._task_total = 0
        self.start_time = time.time()

        self.all_rows = []
        self.current_page = 0
        self._filter_text = ''
        if hasattr(self, 'var_filter'):
            self.var_filter.set('')
        self.tree.delete(*self.tree.get_children())
        self._sync_page_label()
        self.progress['value'] = 0
        self.lbl_progress.config(text='0%')
        self._update_metrics()

        self._set_ui_state('running')
        self._set_status('正在准备采集…')
        self.update_duplicate = bool(self._update_dup.get())
        self._log('开始采集，数据文件：%s（更新重复岗位：%s）'
                  % (self.default_data_file() or '(默认)',
                     '是' if self.update_duplicate else '否'))
        log_file = getattr(logger, 'filename', '')
        if log_file:
            self._log('日志文件：%s' % log_file)

        self._schedule_refresh_timer()
        self.spider_thread = threading.Thread(
            target=self._run_task_guarded, daemon=True)
        self.spider_thread.start()

    def _run_task_guarded(self):
        try:
            self.spider_task()
        except Exception as e:
            logger.exception('采集任务异常终止')
            self._ui(lambda: self.on_error('任务异常: %s' % e))
            self._ui(lambda: self.on_complete('采集异常结束'))

    def _on_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self._set_ui_state('running')
            self._set_status('继续采集中…')
            self._log('继续采集')
        else:
            self.is_paused = True
            self.pause_event.clear()
            self._set_ui_state('paused')
            self._set_status('已暂停（当前请求结束后生效）')
            self._log('已暂停')

    def _on_stop(self):
        if not self.is_running:
            return
        if not messagebox.askyesno(
                '确认停止', '确定停止当前采集吗？\n已采集的数据会保存。',
                parent=self.root):
            return
        # 先置停止标志：采集线程在下一个检查点（含 sleep / 请求返回）立刻退出
        self.is_running = False
        self.is_paused = False
        self.pause_event.set()      # 唤醒处于暂停等待的线程
        if self._refresh_timer_id is not None:
            try:
                self.root.after_cancel(self._refresh_timer_id)
            except Exception:
                pass
            self._refresh_timer_id = None
        self._stop_ts = time.time()
        self._set_ui_state('stopping')
        self._set_status('正在停止…')
        self._log('用户点击停止，正在结束当前请求…')
        self._do_refresh()
        self._poll_thread_exit()

    def _poll_thread_exit(self):
        """等采集线程真正退出后恢复界面，并显示已经等了多久。

        单个请求最长 15s（各平台 REQUEST_TIMEOUT），所以这里把已等待
        时间显示出来，避免用户以为程序卡死。
        """
        thread = self.spider_thread
        if thread is not None and thread.is_alive():
            waited = time.time() - getattr(self, '_stop_ts', time.time())
            if waited >= 1:
                self._set_status('正在停止…已等待 %.0fs（等待当前请求返回）' % waited)
            self.root.after(200, self._poll_thread_exit)
            return
        waited = time.time() - getattr(self, '_stop_ts', time.time())
        self._set_ui_state('idle')
        elapsed = time.time() - self.start_time if self.start_time else 0
        self._set_status('已停止（本次采集 %d 条，耗时 %.0fs，停止耗时 %.1fs）'
                         % (self.today_count, elapsed, waited))

    # ==================== 爬虫回调 ====================
    def _update_metrics(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        try:
            self._metric_labels['count'].config(text=str(self.today_count))
            self._metric_labels['error'].config(text=str(self.error_count))
            self._metric_labels['elapsed'].config(text='%.0fs' % elapsed)
        except Exception:
            pass

    def on_progress(self, current, total, city=''):
        def _update():
            self.total_count = current
            self._task_total = total
            pct = int(current / total * 100) if total > 0 else 0
            self.progress['value'] = pct
            self.lbl_progress.config(text='%d%%' % pct)
            self.current_city = city
            self.lbl_current.config(text=city or '—')
            self._update_metrics()
            self._set_status('正在采集：%s（%d/%d）' % (city, current, total))
            self.lbl_bottom.config(text='当前：%s ｜ 进度 %d/%d' % (city, current, total))
        self._ui(_update)
        self._log('进度 %d/%d：%s' % (current, total, city))

    def on_page_progress(self, page_id, page_added, city_total, elapsed):
        scope = self.current_city if self.current_city and '页' not in self.current_city else ''
        text = '%s 第 %d 页（新增 %d，累计 %d，%.0fs）' % (
            scope, page_id, page_added, city_total, elapsed)

        def _update():
            self.current_page_no = page_id
            self.lbl_bottom.config(text=text)
            self._set_status('正在采集：%s' % text)
            self._update_metrics()
        self._ui(_update)
        self._log(text)

    def on_error(self, msg):
        self.error_count += 1
        self._ui(lambda: (self._set_status('错误：%s' % msg), self._update_metrics()))
        self._log('错误：%s' % msg, level='error')

    def on_data(self, row):
        self.today_count += 1
        self.all_rows.append(row)
        if not self._refresh_pending:
            self._refresh_pending = True
            self.root.after(200, self._do_refresh)
        if self.today_count % 50 == 0:
            self._log('已采集 %d 条' % self.today_count)
            self._ui(self._update_metrics)

    def on_complete(self, msg='采集完成'):
        self.is_running = False
        self.is_paused = False
        if self._refresh_timer_id is not None:
            try:
                self.root.after_cancel(self._refresh_timer_id)
            except Exception:
                pass
            self._refresh_timer_id = None
        elapsed = time.time() - self.start_time if self.start_time else 0
        summary = '%s（本次 %d 条，耗时 %.0fs）' % (msg, self.today_count, elapsed)

        def _finish():
            self._set_ui_state('idle')
            self._set_status(summary)
            self._update_metrics()
            if '停止' not in msg:
                self.progress['value'] = 100
                self.lbl_progress.config(text='100%')
            self._do_refresh()
        self._ui(_finish)
        self._log(summary)

    def check_pause(self):
        return wait_while_paused(self.pause_event, lambda: self.is_running)

    # ==================== 分页 / 过滤 ====================
    def _on_jump_page(self, event=None):
        try:
            page = int(self.var_page.get())
        except (TypeError, ValueError):
            self._sync_page_label()
            return
        page = max(1, min(page, self._total_pages()))
        self.current_page = page - 1
        self._refresh_table()

    def _on_page_size_change(self, event=None):
        try:
            size = int(self.var_page_size.get())
        except (TypeError, ValueError):
            return
        self.page_size = max(10, size)
        self.current_page = 0
        self._refresh_table()

    def _apply_filter(self):
        self._filter_text = (self.var_filter.get() or '').strip()
        self.current_page = 0
        self._refresh_table()
        if self._filter_text:
            self._set_status('已筛选「%s」，命中 %d 条'
                             % (self._filter_text, len(self._visible_rows())))

    def _clear_filter(self):
        self.var_filter.set('')
        self._filter_text = ''
        self.current_page = 0
        self._refresh_table()
        self._set_status('已清除筛选')

    def _visible_rows(self):
        if not self._filter_text:
            return self.all_rows
        kw = self._filter_text.lower()
        return [r for r in self.all_rows
                if any(kw in str(v).lower() for v in r)]

    def _total_pages(self):
        return max(1, (len(self._visible_rows()) - 1) // self.page_size + 1)

    def _sync_page_label(self):
        rows = self._visible_rows()
        suffix = ('（筛选自 %d 条）' % len(self.all_rows)) if self._filter_text else ''
        self.var_page.set(str(self.current_page + 1))
        self.lbl_page.config(text='/ %d 页   共 %d 条%s'
                             % (self._total_pages(), len(rows), suffix))

    def _on_prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()

    def _on_next_page(self):
        if self.current_page < self._total_pages() - 1:
            self.current_page += 1
            self._refresh_table()

    def _do_refresh(self):
        self._refresh_pending = False
        self._refresh_table()

    def _schedule_refresh_timer(self):
        if self._refresh_timer_id is not None:
            try:
                self.root.after_cancel(self._refresh_timer_id)
            except Exception:
                pass
        self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)

    def _on_periodic_tick(self):
        if self._refresh_pending:
            self._do_refresh()
        self._update_metrics()
        if self.is_running:
            self._refresh_timer_id = self.root.after(1000, self._on_periodic_tick)
        else:
            self._refresh_timer_id = None

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        rows = self._visible_rows()
        start = self.current_page * self.page_size
        page_data = rows[start:start + self.page_size]

        for offset, row in enumerate(page_data):
            seq = start + offset + 1
            values = (str(seq),) + tuple(
                str(v) if v is not None else '' for v in row)
            tag = 'even' if offset % 2 else 'odd'
            self.tree.insert('', END, values=values, tags=(tag,))

        self._sync_page_label()
        pages = self._total_pages()
        self.btn_prev.config(state='normal' if self.current_page > 0 else 'disabled')
        self.btn_next.config(
            state='normal' if self.current_page < pages - 1 else 'disabled')

        if self.is_running and self._auto_scroll and self._auto_scroll.get():
            self.tree.yview_moveto(1.0)

    # ==================== 其他 ====================
    def _set_status(self, text):
        try:
            self.lbl_status.config(text=text)
        except Exception:
            pass

    def default_data_file(self):
        return None

    def _refresh_from_memory(self, note=''):
        """从内存 all_rows 重新渲染表格（采集进行中刷新用）。

        采集时新数据先进入内存 all_rows，写盘有 SAVE_INTERVAL 节流，
        所以磁盘文件可能落后于界面。此时若去读文件，会把刚采到的行弄丢，
        因此运行期间只重渲染内存数据，并直接跳到最后一页（跟随最新数据）。
        """
        rows = self._visible_rows()
        pages = self._total_pages()
        self.current_page = max(0, pages - 1)

        self._refresh_pending = False
        self._refresh_table()
        self._update_metrics()
        text = '列表已刷新（内存 %d 条，已跳到第 %d/%d 页）%s' \
               % (len(rows), self.current_page + 1, pages, note)
        self._set_status(text)
        self._log('刷新列表：%s' % text)

    def _on_refresh(self):
        """刷新列表。

        采集进行中：从内存 all_rows 重新渲染（不会丢失尚未写盘的数据）。
        采集中断/结束后：从数据文件重新读取（可加载历史数据）。
        """
        if self.is_running:
            self._refresh_from_memory('，写入文件仍按节流进行')
            return

        f = self.default_data_file() or simpledialog.askstring(
            '刷新列表', '输入数据文件路径（取消则退出）:', parent=self.root)
        if not f:
            return
        if not os.path.exists(f):
            self._set_status('文件不存在：%s' % f)
            return
        try:
            rows = _read_xlsx_rows(f)
            data = [tuple(r) for r in rows
                    if r and str(r[0]) != str(XLSX_HEADERS[0])]
            self.all_rows = data
            self.current_page = 0
            self._filter_text = ''
            if hasattr(self, 'var_filter'):
                self.var_filter.set('')
            self._refresh_table()
            # 底部状态条不再显示刷新结果，统一走日志与状态栏文案
            self._set_status('刷新完成，共 %d 条' % len(data))
            self._log('刷新列表：%s，共 %d 条'
                      % (os.path.basename(f), len(data)))
        except Exception as e:
            self._set_status('刷新失败：%s' % e)
            logger.error('刷新列表失败：%s' % e)

    def spider_task(self):
        raise NotImplementedError('子类必须实现 spider_task 方法')

    def run(self):
        if self._owns_root:
            self.root.mainloop()


def _run_guopin_gui(panel, data_file):
    """国聘采集的 GUI 驱动逻辑（GuoPinGUI / GuopinPanel 共用）。"""
    from guopin import GuoPin

    GuoPin.run(
        data_file,
        pause_event=panel.pause_event,
        is_running=lambda: panel.is_running,
        update_duplicate=getattr(panel, 'update_duplicate', None),
        on_progress=panel.on_progress,
        on_page=panel.on_page_progress,
        on_data=panel.on_data,
        on_complete=panel.on_complete,
    )


class GuoPinGUI(BaseSpiderGUI):
    """国聘采集可视化界面（独立窗口）。"""

    def __init__(self):
        super().__init__(title='国聘数据采集系统', spider_name='国聘')

    def default_data_file(self):
        return os.path.join(_BASE_DIR, '国聘数据.xlsx')

    def spider_task(self, data_file=None):
        _run_guopin_gui(self, data_file or self.default_data_file())


class ZhilianPanel(BaseSpiderGUI):
    """智联招聘采集面板。"""

    def __init__(self, master):
        container = tk.Frame(master, bg=UI_COLOR['bg'])
        super().__init__(title='', spider_name='智联招聘', parent=container)

    def default_data_file(self):
        return os.path.join(_BASE_DIR, '智联数据.xlsx')

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

    def _run_zhilian(self, data_file=None):
        from zhipin import ZhiPin
        data_file = data_file or os.path.join(_BASE_DIR, '智联数据.xlsx')

        def _on_progress(prov, city, added):
            def _u():
                self._set_status('正在采集：%s-%s（新增 %d）' % (prov, city, added))
                self.lbl_bottom.config(text='当前：%s-%s ｜ 新增 %d'
                                            % (prov, city, added))
            self.root.after(0, _u)

        try:
            ZhiPin.run(data_file,
                       ask=self._ask,
                       pause_event=self.pause_event,
                       is_running=lambda: self.is_running,
                       update_duplicate=self.update_duplicate,
                       on_progress=_on_progress,
                       on_data=self.on_data,
                       on_complete=self.on_complete,
                       on_error=self.on_error)
        except Exception as e:
            logger.error('智联招聘采集异常：%s' % e)
            self.on_error('智联招聘: %s' % e)
            self.on_complete('智联招聘异常结束')


class GuopinPanel(BaseSpiderGUI):
    """国聘采集面板。"""

    def __init__(self, master):
        container = tk.Frame(master, bg=UI_COLOR['bg'])
        super().__init__(title='', spider_name='国聘', parent=container)

    def default_data_file(self):
        return os.path.join(_BASE_DIR, '国聘数据.xlsx')

    def spider_task(self, data_file=None):
        _run_guopin_gui(self, data_file or self.default_data_file())


class NcssPanel(BaseSpiderGUI):
    """国家大学生就业服务平台采集面板。"""

    sources = None

    def __init__(self, master):
        container = tk.Frame(master, bg=UI_COLOR['bg'])
        super().__init__(title='', spider_name='国家大学生就业服务平台',
                         parent=container)

    def default_data_file(self):
        return os.path.join(_BASE_DIR, '国家大学生就业服务平台.xlsx')

    def spider_task(self, data_file=None):
        from ncss import Ncss

        data_file = data_file or self.default_data_file()
        try:
            Ncss.run(
                data_file,
                sources=self.sources,
                pause_event=self.pause_event,
                is_running=lambda: self.is_running,
                update_duplicate=self.update_duplicate,
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


class BossPanel(BaseSpiderGUI):
    """BOSS直聘采集面板。"""

    city_scope = 'all'
    position_scope = 'all'
    # 传 None 时由 Boss.run 从 config/boss.json 读取 max_pages
    max_pages = None
    with_detail = True

    def __init__(self, master):
        container = tk.Frame(master, bg=UI_COLOR['bg'])
        super().__init__(title='', spider_name='BOSS直聘', parent=container)

    def default_data_file(self):
        return os.path.join(_BASE_DIR, 'BOSS直聘数据.xlsx')

    def spider_task(self, data_file=None):
        from Boss import Boss

        data_file = data_file or self.default_data_file()
        try:
            Boss.run(
                data_file,
                city_scope=self.city_scope,
                position_scope=self.position_scope,
                max_pages=self.max_pages,
                with_detail=self.with_detail,
                pause_event=self.pause_event,
                is_running=lambda: self.is_running,
                update_duplicate=self.update_duplicate,
                on_progress=self.on_progress,
                on_page=self.on_page_progress,
                on_data=self.on_data,
                on_complete=self.on_complete,
                on_error=self.on_error,
            )
        except Exception as e:
            logger.error('BOSS直聘采集异常：%s' % e)
            self.on_error('BOSS直聘: %s' % e)
            self.on_complete('BOSS直聘异常结束')


class SpiderGUI:
    """主窗口：多页签，各平台独立采集、独立展示。

    时间显示在页签行的右端，与页签同排；页签内部不再重复显示平台名称。
    """

    def __init__(self):
        self.root = _make_window('数据采集系统')
        self.root.title('招聘数据采集系统')

        style = ttk.Style() if not _HAS_TB else self.root.style
        try:
            style.configure('TNotebook', background=UI_COLOR['bg'],
                            borderwidth=0,
                            # tabmargins 的 left 会作为第一个页签的前置留白，
                            # 而页签自身还有 padding。这里让 left=0，
                            # 由外层 wrap 的 padx 统一控制左边缘，确保与卡片对齐。
                            tabmargins=(0, 8, 0, 0))
        except Exception:
            pass

        wrap = tk.Frame(self.root, bg=UI_COLOR['bg'])
        wrap.pack(fill=BOTH, expand=True)

        if _HAS_TB:
            # 不传 bootstyle：由 _apply_theme_to_style 统一配置 Tab 外观
            self.notebook = tb.Notebook(wrap)
        else:
            self.notebook = ttk.Notebook(wrap)
        # wrap 内统一留出 pad，使「页签左边缘」与「卡片左边缘」同为 pad 位置
        self.notebook.pack(fill=BOTH, expand=True,
                           padx=UI_LAYOUT['pad'],
                           pady=(UI_LAYOUT['gap'], 0))

        # 时钟：用 place 叠在页签行的右端，与页签同排显示
        self.lbl_clock = tk.Label(
            wrap, text='', bg=UI_COLOR['bg'], fg=UI_COLOR['muted'],
            font=_font('size_small'))
        self.lbl_clock.place(relx=1.0, x=-UI_LAYOUT['pad'], y=14, anchor='ne')
        self._tick_clock()

        self.tab_zhi = ZhilianPanel(self.root)
        self.tab_gp = GuopinPanel(self.root)
        self.tab_ncss = NcssPanel(self.root)
        self.tab_boss = BossPanel(self.root)

        self.notebook.add(self.tab_zhi.container, text='智联招聘')
        self.notebook.add(self.tab_gp.container, text='国聘')
        self.notebook.add(self.tab_ncss.container, text='国家大学生就业服务平台')
        self.notebook.add(self.tab_boss.container, text='BOSS直聘')

    def _tick_clock(self):
        try:
            self.lbl_clock.config(text=time.strftime('%Y-%m-%d  %H:%M:%S'))
            self.root.after(1000, self._tick_clock)
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    SpiderGUI().run()

