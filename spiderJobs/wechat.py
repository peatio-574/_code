# coding='utf-8'
"""医护知音（微信公众号）招聘岗位采集。

数据采集流程：扫微信客户端进程内存拿文章链接（存 wechat_links.json）
-> 逐篇访问文章页 -> 正文配图交视觉模型读成岗位行 -> 按统一列写入 xlsx。

与其它平台保持一致的地方：
  * 读写 xlsx 走 BaseSpider（set_column_style / load_yesterday_data /
    _append_rows / _save），去重按「岗位编号」，列顺序即 XLSX_HEADERS；
  * 暂停/停止走 _wait / _sleep，回调签名与 GuoPin/ZhiPin 相同
    （on_progress / on_page / on_data / on_complete / on_error）。

与其它平台不同的地方：
  * 没有「城市分页」概念，采集单元是**一篇文章**；因此 get_page_info 的入参是链接，
    进度回调里的 city 位置放文章标题；
  * 岗位在图片里，必须走视觉模型，没有规则兜底 —— 没配 Key 直接报错，不静默返回空。
"""
import base64
import ctypes
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import requests

from getJobs import BaseSpider, create_session
from Logger import logger


# ==================== 路径（脚本 / exe 同目录为准） ====================
# 打包成 exe 后 sys.executable 是 exe 路径，所以下面三样都落在 exe 同目录，
# 打包脚本（打包.bat）也会在那里预建目录 —— 用户可以直接打开查看/编辑。
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 链接清单放在程序目录（必须可写），不进 config/（那个目录打包后只读）
LINKS_FILE = os.path.join(_BASE_DIR, 'wechat_links.json')

#: 文章配图落盘目录（exe 同目录，外部可读写）。
#: 不用 `.cache` 这类隐藏目录：用户需要能直接翻看识别用的原图。
IMAGE_DIR = os.path.join(_BASE_DIR, '医护知音图片')

#: xlsx 附件落盘目录（同上，外部可读写）。
ATTACH_DIR = os.path.join(_BASE_DIR, '医护知音附件')

#: 微信长链必须带 chksm 才给正文。实测（同一条链接对比）：
#:   无 chksm -> 17825 字节，302 到 wappoc_appmsgcaptcha，没有正文
#:   有 chksm -> 3572237 字节，正常文章页
#: 而且 chksm 的内容不校验（填 x / 1 / 随机 hex 都能过），只要非空。
#: 内存里扫出来的分享链接常常只有 __biz/mid/idx/sn，这种一请求就被拦 ——
#: 所以**发请求时**补一个占位值。清单里存的仍是原样，不做改写。
DUMMY_CHKSM = 'x' * 64

#: 平台名：界面页签、日志前缀、xlsx「来源」列都用它。
#: 采集的是「医护知音」，公众号本身只是发布者，不是招聘单位 ——
#: 所以它只出现在「来源」列，绝不会被当成「公司名称」。
WEB_NAME = '医护知音'


def link_key(url):
    """链接去重用的身份键。

    同一篇文章在微信内存里会以多种参数变体出现：chksm / scene / sessionid /
    clicktime / #rd 各不相同。直接比整串 URL 会当成不同文章，同一篇被反复抓、
    反复调模型 —— 实测清单里 86 条只有 22 篇不同文章。

    文章身份是 __biz + mid + idx；取不到时退回 URL 本身。
    """
    url = str(url or '').strip()
    if '/s?' not in url:
        return url
    try:
        q = dict(parse_qsl(urlsplit(url).query, keep_blank_values=False))
    except ValueError:
        return url
    if q.get('__biz') and q.get('mid'):
        return '%s:%s:%s' % (q['__biz'], q['mid'], q.get('idx') or '1')
    return url


def request_url(url):
    """把 URL 变成「能真正拿到正文」的形式，仅供发请求使用。

    只做一件事：长链缺 chksm 时补一个占位值（见 DUMMY_CHKSM 的注释）。
    其他参数一个都不动（不用 urlencode 重排，避免把 __biz 的 = 编码成 %3D），
    短链也不动 —— 清单里存的始终是原样 URL。
    """
    url = str(url or '').strip()
    if '/s?' not in url:
        return url
    try:
        parts = urlsplit(url)
        names = {k for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    except ValueError:
        return url
    if 'chksm' in names:
        return url
    # 末尾有时带 #rd 这类片段，chksm 要插在 ? 之后、# 之前
    head, _, frag = url.partition('#')
    sep = '&' if '?' in head else '?'
    out = '%s%schksm=%s' % (head, sep, DUMMY_CHKSM)
    return out + ('#' + frag if frag else '')



# ==================== 内存扫描：微信进程 ====================
# 这一段与原 Wechat/mem_scan_links.py 逐字一致，只把 print 换成 logger。
# Windows 结构体声明（相当于 C 的 struct，不是业务对象）：
# VirtualQueryEx / Process32FirstW 会把内核数据直接写进你提供的这块内存，
# 所以字段顺序、类型、大小必须和 Windows SDK 完全一致。传 dict/tuple 会被拒绝。

class _MemoryInfo(ctypes.Structure):
    """一块内存区域的描述（对应 MEMORY_BASIC_INFORMATION）。"""
    _fields_ = [
        ('BaseAddress', ctypes.c_void_p),
        ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', wintypes.DWORD),
        ('RegionSize', ctypes.c_size_t),
        ('State', wintypes.DWORD),
        ('Protect', wintypes.DWORD),
        ('Type', wintypes.DWORD),
    ]


class _ProcessEntry(ctypes.Structure):
    """进程列表里的一条记录（对应 PROCESSENTRY32W）。"""
    _fields_ = [
        ('dwSize', wintypes.DWORD),        # 调用前必须先填 sizeof(本结构体)
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),  # ← 进程 ID
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),  # ← 进程名
    ]


class WechatMemReader:


    def __init__(self):
        self.exes = ('Weixin.exe', 'WeChatAppEx.exe')  # 要扫的进程
        self.chunk = int(8 * 1024 * 1024)   # 每次读多少字节，默认 8MB
        self.overlap = int(8 * 1024)  # 相邻块重叠字节数，默认 8KB（防链接跨块被切断）
        self.max_addr = 0x7FFFFFFFFFFF     # x64 用户态地址上界

        # Windows API 常量
        self.VM_READ = 0x0010              # 允许读进程内存
        self.QUERY_INFO = 0x0400           # 允许查内存布局
        self.SNAP_PROC = 0x00000002        # 快照内容：进程列表
        self.MEM_COMMIT = 0x1000           # 内存已提交（有数据）
        self.PAGE_GUARD = 0x100            # 守护页，读它会让微信崩溃！

        # 算可读的保护位：0x02 只读 / 0x04 读写 / 0x20 可执行读 / 0x40 可执行读写
        self.readable = frozenset((0x02, 0x04, 0x20, 0x40))
        # 内核句柄 + 读缓冲（缓冲懒创建）
        self.k32 = ctypes.windll.kernel32
        self._declare_api()
        self._buffer = None


    def _declare_api(self):
        """声明 API 签名。

        必须写：ctypes 默认把返回值当 32 位整数，而句柄在 x64 上是
        8 字节指针。不声明会被截断，句柄无效 —— 表现为
        「OpenProcess 看着成功了，但一读内存就失败」。
        """
        k = self.k32
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     ctypes.POINTER(_MemoryInfo),
                                     ctypes.c_size_t]
        k.VirtualQueryEx.restype = ctypes.c_size_t
        k.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE,
                                      ctypes.POINTER(_ProcessEntry)]
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = [wintypes.HANDLE,
                                     ctypes.POINTER(_ProcessEntry)]
        k.Process32NextW.restype = wintypes.BOOL


    def scan_process(self):
        """扫描微信进程"""
        procs = []
        for exe in self.exes:
            snap = self.k32.CreateToolhelp32Snapshot(self.SNAP_PROC, 0)
            if not snap or snap == wintypes.HANDLE(-1).value:
                continue
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)  # 必须先填大小
            try:
                ok = self.k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower() == exe.lower():
                        procs.append((exe, entry.th32ProcessID))
                    ok = self.k32.Process32NextW(snap, ctypes.byref(entry))
            finally:
                self.k32.CloseHandle(snap)

        if not procs:
            logger.warning('没找到微信进程（%s），请先打开微信客户端' % (self.exes,))
            return []
        logger.info('共%d个微信进程' % len(procs))
        return procs


    def scan_memory(self, procs, biz):
        """扫描内存"""
        info = []

        for exe, pid in procs:
            # 打开进程拿读权限。失败通常是权限不匹配
            # （微信以管理员运行，而本脚本不是）。
            handle = self.k32.OpenProcess(self.VM_READ | self.QUERY_INFO, False, pid)
            if not handle:
                logger.warning('  pid=%s 打不开（微信若以管理员运行，本脚本也要提权）' % pid)
                continue

            if self._buffer is None:      # 懒创建，整轮扫描复用这一块
                self._buffer = ctypes.create_string_buffer(self.chunk + self.overlap)
            buf = self._buffer
            cap = len(buf)

            read_total = 0
            mbi = _MemoryInfo()
            mbi_size = ctypes.sizeof(mbi)
            addr = 0
            try:
                # 从地址 0 往后，一段一段问「这段能读吗」
                while addr < self.max_addr:
                    if not self.k32.VirtualQueryEx(handle, ctypes.c_void_p(addr),
                                                   ctypes.byref(mbi), mbi_size):
                        break  # 查询失败 = 到头了

                    base = mbi.BaseAddress or 0
                    size = mbi.RegionSize or 0
                    nxt = base + size

                    # 守护页最危险：读它会让微信直接崩溃闪退。
                    # (有长度 + 已提交 + 可读 + 不是守护页) 三个条件都满足才读
                    ok_region = bool(mbi.RegionSize and mbi.State == self.MEM_COMMIT
                                     and mbi.Protect in self.readable
                                     and not (mbi.Protect & self.PAGE_GUARD))

                    if ok_region:
                        # 一段可能几百 MB，分块读；相邻块重叠 overlap 字节，
                        # 否则横跨两块边界的链接会被切成两半、谁都匹配不上。
                        off = 0
                        while off < size:
                            want = min(cap, size - off)
                            got = ctypes.c_size_t(0)
                            if (self.k32.ReadProcessMemory(handle, ctypes.c_void_p(base + off), buf, want, ctypes.byref(got))
                                    and got.value):
                                read_total += got.value
                                data = ctypes.string_at(buf, got.value)

                                # ① 短链 id    /s/ 后面 20~24 位。
                                info = self.single_proc_scan_short_link(info, data, biz)
                                # ② 完整分享链（下面统一去噪）
                                info = self.single_proc_scan_long_link(info, data, biz)
                            off += self.chunk

                    if nxt <= addr:               # 防死循环
                        break
                    addr = nxt
            finally:
                self.k32.CloseHandle(handle)
            logger.info('  %s pid=%s：读 %.0f MB，初步累计%d条'
                        % (exe, pid, read_total / 1024 / 1024, len(info)))
        return info


    def single_proc_scan_short_link(self, links, data, biz):
        # ① 短链 id    /s/ 后面 20~24 位。
        result = re.compile(rb'/s/([A-Za-z0-9_-]{20,24})(?![A-Za-z0-9_-])').finditer(data)
        for m in result:
            short_link = 'https://mp.weixin.qq.com/s/' + m.group(1).decode('ascii', 'ignore')

            # 短链：/s/ 后面直接跟 id，后面没有 ?
            rule = re.compile(r'/s/[A-Za-z0-9_-]{20,24}(?:[?#].*)?$').search(short_link)
            if rule and biz in short_link and short_link not in links:
                links.append(short_link)
        return links


    def single_proc_scan_long_link(self, links, data, biz):
        # ② 完整分享链（下面统一去噪）
        for m in re.compile(rb'mp\.weixin\.qq\.com/s\?[^"\'<>\s]{20,300}').finditer(data):
            long_link = 'https://' + m.group(0).decode('ascii', 'ignore')

            if '?' not in long_link:
                continue
            if '${' in long_link or '{{' in long_link:  # 模板变量
                continue

            # 分享链接必须有合法 __biz
            m = re.compile(r'[?&]__biz=([^&#]{4,80})').search(long_link)
            if not m or not m.group(1) or m.group(1).startswith('='):
                continue

            # 分享链接必须有合法 sn
            rule = re.compile(r'[?&]sn=([0-9a-fA-F]{8,})').search(long_link)
            if rule and biz in long_link and long_link not in links:
                links.append(long_link)
        return links


    def get_links(self, biz=''):
        """扫描微信内存，把**没见过的**链接追加进 LINKS_FILE，返回新增条数。

        去重基准是存量数据（status 真假都算已存在），按 link_key 的
        __biz+mid+idx 判断 —— 同一篇文章会以不同 chksm/scene 反复出现在内存里，
        直接比整串 URL 会让它重复入库、重复调模型。

        新增的一律 status=false，等 run() 抓完再改 true。
        """
        procs = self.scan_process()
        if not procs:
            return 0
        found = self.scan_memory(procs, biz)
        logger.info(f'【{WEB_NAME}】内存扫描到 {len(found)} 条（含重复）')

        if not os.path.exists(LINKS_FILE):
            # 必须是合法的 JSON 空对象；写 0 字节会让下面的 json.load 直接崩
            with open(LINKS_FILE, 'w', encoding='utf-8-sig') as f:
                json.dump({}, f)
        with open(LINKS_FILE, encoding='utf-8-sig') as f:
            raw = f.read()
        # 空文件 / 只剩 BOM / 纯空白，都当作空清单，不要抛 JSONDecodeError
        data = json.loads(raw) if raw.strip().lstrip('\ufeff') else {}

        count = 0
        unique_links = list(data.keys())

        foud = list(set(found))
        for url in foud:
            if not url:
                continue
            unique_link = link_key(url)
            if unique_link not in unique_links:
                data[unique_link] = {'url': url, 'status': False}
                unique_links.append(unique_link)
                count += 1

        logger.info(f'【{WEB_NAME}】新增 {count} 条')
        # 原子写：直接 open('w') 会先清空文件，中途出错就留下 0 字节残文件，
        # 所有链接都读不回来（这正是之前 JSONDecodeError 的来源）
        tmp = LINKS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8-sig') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LINKS_FILE)
        return count



# ==================== 岗位名判定 ====================
# 模型返回的行必须过这道判据，否则「大专及以上」「岗位名称」这类会被写进交付表。

_CN_NUM = "一二三四五六七八九十"

#: 以这些词开头的行是条件/字段，不是岗位名。
#: 末尾的 `\s*(?:[:：]|$)` 很关键：必须"自成字段"才算，
#: 否则「健康管理中心医师」会被"健康"误杀。
_FIELD_PREFIX = re.compile(
    r"^(?:学历|专业|职称|资格|年龄|性别|要求|任职要求|岗位职责|职责|招聘人数|人数|名额|"
    r"待遇|薪酬|薪资|福利|报名|报名时间|报名方式|考试|面试|笔试|联系|电话|地址|邮箱|"
    r"工作地点|工作时间|其他|备注|说明|条件|招聘条件|应聘条件|政治|身体|健康)"
    r"\s*(?:[:：]|$)")

#: 编号前缀：「（一）」「(1)」「1.」「一、」「01 」
_NUM_PREFIX = re.compile(
    r"^(?:[（(][%s\d]{1,3}[)）]|[%s]{1,3}\s*[、.．]|\d{1,3}\s*[、.．)）]|\d{2}\s+)\s*"
    % (_CN_NUM, _CN_NUM))

#: 文章里的章节标题，不是岗位
_SECTION_WORDS = re.compile(
    r"基本情况|基本条件|招聘条件|招聘原则|招考范围|招考对象|范围和对象|招聘岗位|岗位要求|"
    r"岗位设置|报名方式|报名时间|招聘程序|招聘流程|招聘办法|资格条件|资格要求|应聘条件|"
    r"待遇|薪酬|福利|其他事项|注意事项|纪律|监督|联系方式|简介|概况|招聘计划|招聘名额|"
    r"招聘人数|考试|考核|考察|体检|聘用|公示|录用|说明|附件|须知|范围|对象|计划|条件|"
    r"程序|流程|办法|原则|要求|职责")

#: 职业后缀。用来区分「中医学」(专业) 和「中医科医师」(岗位)
_JOB_SUFFIX = (
    "医师", "医生", "护士", "护师", "技师", "药师", "会计", "主任", "主管", "治疗师",
    "检验师", "检验员", "影像", "康复", "中医", "护理", "助产", "文员", "干事", "工程师",
    "研究员", "管理员", "专员", "岗位", "出纳", "统计", "病案", "药剂", "麻醉", "超声")

_HEADER_WORDS = {
    "其他要求", "其它要求", "其他条件", "其它条件",
    "岗位名称", "招聘岗位", "岗位", "职位", "职位名称", "科室", "招聘人数", "人数", "名额",
    "学历", "学历要求", "专业", "专业名称", "专业要求", "年龄", "年龄要求",
    "职称", "职称要求", "备注", "序号", "岗位代码", "岗位编码",
    "专业技术", "专技", "管理岗", "工勤岗", "其他", "合计", "小计", "总计"}

#: 表格模板里的占位符。闸门只查形式特征，这类需要单独挡一道
_PLACEHOLDER = re.compile(r'请填写|请选择|示例|待定|详见|同上|^X{2,}$|^x{2,}$'
                          r'|^岗位名称$|^职位名称$|^岗位$|^职位$|^名称$|^备注$'
                          r'|^合计$|^总计$|^小计$')


def _clean(text):
    return re.sub(r"[ \t\u3000]+", " ", (text or "").strip()).strip("；;。，, ")


def _plain_text(fragment):
    """去标签、解实体、压空白。用于取 <a> 标签里的文件名。"""
    text = re.sub(r'<[^>]+>', '', fragment or '')
    text = html_mod.unescape(html_mod.unescape(text))
    return _clean(text.replace('\\x26', '&').replace('\\/', '/'))


def normalize_position_name(raw):
    """剥掉编号前缀与"招聘/诚聘"这类动词，返回干净的岗位名。"""
    text = _clean(raw)
    text = _NUM_PREFIX.sub("", text)
    text = re.sub(r"^(?:本次|现|拟|将|计划|共|合计)?(?:招聘|诚聘|急招|现招|招录|引进)", "", text)
    text = re.sub(r"^(?:本次|现|拟|将|计划|共|合计)", "", text)
    text = re.sub(r"(?:岗位|职位)$", "", text)
    return text.strip(" ：:、.．·-—")


def looks_like_position(raw):
    """这个字符串像不像一个岗位名。不像的宁可丢掉，也不要塞进交付表。"""
    name = normalize_position_name(raw)
    if re.fullmatch(r"不限|专业不限|不限专业|若干|若干名|无", name):
        return False
    if not (2 <= len(name) <= 16):
        return False
    if _FIELD_PREFIX.match(name):
        return False
    # 「大专以上」「本科及以上」「全日制专科」都是学历条目
    if re.match(r"^(?:大专|本科|硕士|博士|研究生|中专|高中|初中|全日制|统招|应届)", name):
        return False
    if name.endswith(("以上", "以下", "及以上", "及以下")):
        return False
    if "及以上" in name or name.endswith(("学历", "学位", "资格", "证书")):
        return False
    if re.search(r"简介|概况|须知|说明|流程|附件|附录|声明|待遇|福利|联系我们|报名表|岗位表|一览表",
                 name):
        return False
    if _SECTION_WORDS.search(name):
        return False
    # 机构名不是岗位名
    if re.search(r"(医院|卫生院|卫生服务中心|疾控中心|保健院|医学院|医科大学|集团)", name) \
            and not any(name.endswith(s) for s in _JOB_SUFFIX):
        return False
    # 「中医学」「临床医学」是专业名
    if name.endswith(("学", "专业")) and not any(name.endswith(s) for s in _JOB_SUFFIX):
        return False
    if any(ch in name for ch in "：:；;"):
        return False
    if re.fullmatch(r"[\d\W_]+", name):
        return False
    if name in _HEADER_WORDS or name in ("整篇公告", "（整篇公告）"):
        return False
    return True


# ==================== 采集类 ====================

class Wechat(BaseSpider):
    """医护知音（）岗位采集类。

    采集单元是文章链接，不是城市分页；其余（去重、写盘、暂停停止）与其它平台一致。
    """

    #: 界面上显示的平台名，也写进 xlsx 的「来源」列。
    web_name = WEB_NAME

    # ---------- 视觉模型 ----------
    #: 直接写死在这里。换号改这一行即可。
    API_KEY = 'sk-a69251bc743e48afa776ab443a92d4c9'
    BASE_URL = 'https://api.deepseek.com/chat/completions'
    MODEL = 'deepseek-flash'
    #: low / high / auto。表格必须 high，low 会把小字压糊，人数和学历全认错
    DETAIL = 'high'
    #: 必须给足：推理模型会把额度全花在思考上。实测同一张岗位表
    #:   8192  -> finish_reason=length，reasoning_tokens=8192，正文长度 0
    #:   32768 -> finish_reason=stop，正常返回
    MAX_TOKENS = 65536

    #: 正文送进模型的字符上限。公告正文通常几千字，全发进去没必要，
    #: 但岗位清单常写在正文中后段，截太短会漏，取 8000 约等于 4-5 屏中文。
    MAX_TEXT_CHARS = 8000

    #: 单次请求最多送几张图。一篇 15 张图 base64 后可达 20MB+，
    #: 请求会超时或直接被服务端拒，限 8 张足够覆盖多页岗位表。
    MAX_IMAGES = 8

    #: 连续多少条跳验证页才判定为「真被限流」。
    #: 实测单条偶发验证很常见（29 条里 1 条），下一轮请求就恢复，
    #: 立刻停整轮会让整批卡住；连续 3 条才说明是 IP 层面的限流。
    BLOCK_STREAK_LIMIT = 3

    #: 跳验证页后原地重试几次。实测同一条被拦后，下一次请求就通过了
    #: （验证页是一次性的，重试会带上服务端刚下发的 poc_sid cookie）。
    BLOCK_RETRY = 2

    #: 重试前的等待秒数，按第几次重试线性放大（3s / 6s），别打太急。
    BLOCK_RETRY_WAIT = 3.0

    # ---------- 抓取参数 ----------
    DEFAULT_DELAY = 8.0          # 每篇间隔（秒）。实测 8 秒能连打 20 条不撞验证墙
    REQUEST_TIMEOUT = 30         # 文章页超时
    VLM_TIMEOUT = 300            # 单次模型调用超时

    # ---------- 微信页面常量 ----------
    MP = 'https://mp.weixin.qq.com'
    CST = timezone(timedelta(hours=8))
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

    #: ① 验证墙：立刻停，等 10-30 分钟
    BLOCK_MARKERS = ('antispider', '请输入验证码', '您的访问过于频繁',
                     '我们的系统检测到您网络中存在异常访问请求', '环境异常',
                     '完成验证后即可继续访问')
    #: ② 验证页的真实形态（不含上面任何一句中文，只看文本会漏判成"改版"）
    CAPTCHA_MARKERS = ('wappoc_appmsgcaptcha', 'poc_token', 'appmsgcaptcha')
    #: ③ 微信自己说这篇没了：跳过单篇，继续下一篇
    UPSTREAM_MARKERS = ('该内容已被发布者删除', '此内容因违规无法查看', '该公众号已迁移',
                        '此内容被多人投诉', '参数错误')
    #: ④ 客户端提示页：只在"没抓到标题"时才成立。
    #: 这几个词在正常文章页的模板里也有，先判会把好文章全误杀。
    SESSION_MARKERS = ('请在微信客户端打开', '请在微信中打开', '请在微信客户端中打开',
                       '请登录后查看', '登录后可继续访问')

    #: 小于这个字节的图是图标/分割线/加载占位
    MIN_IMAGE_BYTES = 3000
        
    PROMPT = """你是招聘信息结构化助手。输入包含：
  * 文章标题；
  * 正文文字（可能为空，也可能就是岗位清单）；
  * 若干张图片（可能没有图片）。

岗位信息可能在正文文字里（如"招聘护士3名、临床医师2名"），
也可能在图片的表格里。**两处都要看**，不要因为没图就说没有岗位。

请严格输出一个 JSON 对象，不要输出任何解释文字：
{"单位": "发布招聘的单位全称，从标题、正文、图片里判断，如'广安市岳池县妇幼保健院'；"
         "文章没有单一招聘单位时（如'三支一扶''选调生''事业单位统考'这类计划），"
         "填该计划/活动在标题里的完整名称，如'西藏自治区2026年高校毕业生三支一扶计划'；"
         "**绝对不能填公众号名称**；判断不出来就填空串",
 "省份": "单位所在省份，不带'省'字，如'四川'；直辖市填市名如'重庆'；判断不出来就填空串",
 "城市": "单位所在城市，不带'市'字，如'广安'；判断不出来就填空串",
 "岗位": [ {...}, ... ]}

岗位数组里每个元素包含：
{"岗位": "岗位名称，如'内科医师'", "人数": 整数或 null, "学历": "如'全日制本科及以上'或空串",
 "专业": "如'临床医学、内科学'或空串", "年龄": "如'35周岁及以下'或空串",
 "职称/资格": "如'初级及以上''护士执业资格''规培合格证'或空串",
 "其他要求": "『备注』列内容 + 『其他条件』列里**不属于职称/资格证**的要求（如工作经历、服从安排、体检要求、性别限制）；资格证类内容请放职称/资格；没有就空串",
 "依据": "**该岗位所在行的原文，逐字照抄**；文字里来的就抄那句话，图片里来的就抄那一行，"
         "把所有列都抄全，不要改写、不要省略"}

规则：
1. 单位只能是招聘方本身（单位名，或计划/活动的名称），**绝不能填公众号名**
   （公众号名是发布者，不是招聘单位）；不要填上级主管单位；
2. 省份和城市从单位名称里的行政区划判断，如"广安市岳池县妇幼保健院" -> 省份"四川"、城市"广安"；
   "遂宁市中心医院" -> "四川"/"遂宁"；"重庆医科大学附属大足医院" -> "重庆"/"重庆"；
   单位名里看不出城市时，城市可填到区县，如"青白江"；都判断不出来就填空串，不要猜；
3. 只提取岗位行，不要把"基本条件/招聘程序/报名方式"等标题当岗位；
4. 人数只填阿拉伯数字；看不清就填 null；
5. 依据必须原文照抄，**必须包含该行的岗位名、人数、学历、专业、年龄、职称/资格等全部列**，
   这是后续核对凭证，抄不全就无法复核；
6. "其他要求"放"优先条件 / 工作经验年限 / 职责能力"这类内容；没有就填空串；
7. 正文和图片都没有岗位信息（宣传海报/二维码/照片/纯通知）时，"岗位"返回空数组，
   单位/省份/城市仍要尽量从标题判断出来。
"""

    _session = None

    # ==================== 配置 / 会话 ====================

    @classmethod
    def session(cls):
        """复用连接（带 certifi + 系统证书库，与其它平台一致）。"""
        if cls._session is None:
            cls._session = create_session()
        return cls._session

    @classmethod
    def vlm_api_key(cls):
        """取视觉模型 Key：直接读类属性 API_KEY（写死在文件顶部）。"""
        return str(cls.API_KEY or '').strip()

    # ==================== 链接清单 ====================

    @classmethod
    def load_links(cls):
        """读 LINKS_FILE，返回 (全部清单, 待抓 url 列表)。

        文件由 WechatMemReader.get_links 维护，结构是 dict：
            {"<link_key>": {"url": ..., "status": false}, ...}
        key 就是 link_key，所以天然按文章身份去重。

        也兼容旧的 list 结构 [{"url":..., "status":...}, ...]：
        读进来后统一成 dict 返回，调用方不用关心文件是哪种格式。
        """
        with open(LINKS_FILE, encoding='utf-8-sig') as f:
            raw = f.read()
        # 空文件 / 只剩 BOM / 纯空白都当作空清单；损坏的 JSON 也降级成空清单，
        # 否则一次写坏就再也跑不起来
        if not raw.strip().lstrip('\ufeff'):
            return {}, []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error('【%s】链接清单损坏（%s），按空清单继续：%s'
                         % (cls.web_name, e, os.path.basename(LINKS_FILE)))
            return {}, []

        # 统一成 dict：兼容旧版 list 结构 [{"url":..., "status":...}, ...]
        if isinstance(data, list):
            merged = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                url = str(item.get('url') or '')
                if not url:
                    continue
                key = link_key(url)
                val = bool(item.get('status'))
                if key in merged:
                    # 任一变体抓过就算抓过
                    if val:
                        merged[key]['status'] = True
                else:
                    merged[key] = {'url': url, 'status': val}
            data = merged
        elif isinstance(data, dict) and ('links' in data or 'urls' in data):
            merged = {}
            for item in (data.get('links') or data.get('urls') or []):
                if isinstance(item, dict) and item.get('url'):
                    merged[link_key(item['url'])] = {
                        'url': item['url'], 'status': bool(item.get('status'))}
            data = merged
        elif not isinstance(data, dict):
            return {}, []

        # 清掉结构不对的条目，避免后面 KeyError
        clean = {}
        for k, v in data.items():
            if not (isinstance(v, dict) and v.get('url')):
                continue
            url = str(v['url']).strip()
            if not url:
                continue
            key = link_key(url)
            status = bool(v.get('status'))
            if key in clean:
                if status:
                    clean[key]['status'] = True
            else:
                clean[key] = {'url': url, 'status': status}
        deal_links = [v['url'] for v in clean.values() if not v['status']]
        return clean, deal_links

    @classmethod
    def save_links(cls, data, url):
        """把 url 这篇的 status 改成 true 并写回 LINKS_FILE。

        data 是 {link_key: {"url","status"}} 的 dict；用 link_key 直接定位。
        key 不存在时补一条（清单被手工改过、或短链/长链 key 不一致时会走到这里），
        否则会抛 KeyError 让整轮采集崩掉。
        """
        key = link_key(url)
        item = data.get(key)
        if isinstance(item, dict):
            item['status'] = True
            if not item.get('url'):
                item['url'] = url
        else:
            data[key] = {'url': url, 'status': True}
        cls._write_links(data)

    @staticmethod
    def _write_links(data):
        """把清单整体写回文件。

        用临时文件 + os.replace 原子替换：直接 open('w') 覆盖时，
        如果写到一半进程被杀，文件会变成残缺 JSON，所有链接都读不回来。
        """
        tmp = LINKS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8-sig') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LINKS_FILE)


    # ==================== 页面解析（只取标题/时间/配图） ====================

    @staticmethod
    def _find(page, *patterns, cast=None):
        """按顺序试多个正则，返回第一个非空捕获组；cast=int 时转整数。

        合起来取代原来三个单行工具：
            _var(page, name)        -> _find(page, r'var name = "([^"]*)"', ...)
            _meta(page, prop)       -> _find(page, r'<meta ... content="([^"]*)"')
            _first_int(patterns)    -> _find(page, *patterns, cast=int)
        """
        for pattern in patterns:
            m = re.search(pattern, page)
            if not m or not m.groups():          # 正则写错（没有捕获组）就跳过，不要抛
                continue
            # 页面里的值常带 HTML 实体（og:url 里的 &amp;），必须还原，
            # 否则写进 xlsx 的链接是死链、link_key 也解析不出参数
            value = html_mod.unescape(m.group(1) or '').strip()
            if not value:
                continue
            if cast is None:
                return value
            try:
                return cast(value)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _var(cls, page, name):
        """取 `var name = "..."`，单双引号都试。"""
        return cls._find(page, r'var %s = "([^"]*)"' % name,
                         r"var %s = '([^']*)'" % name)

    @classmethod
    def _meta(cls, page, prop):
        """取 `<meta property="..." content="...">`。"""
        return cls._find(page, r'<meta[^>]*property="%s"[^>]*content="([^"]*)"'
                         % re.escape(prop))

    @classmethod
    def _first_int(cls, patterns, page):
        """按顺序试多个正则，返回第一个能转成整数的捕获组。"""
        return cls._find(page, *patterns, cast=int)

    @classmethod
    def content_of(cls, page):
        """取正文区域的 HTML（#js_content 内部）。

        和 images_of 共用同一段定位逻辑：新图文模板没有 #js_content，
        那种页面返回空串（正文是图片）。
        """
        start = page.find('id="js_content"')
        if start < 0:
            start = page.find("id='js_content'")
        if start < 0:
            return ''
        start = page.find('>', start)
        if start < 0:
            return ''
        start += 1
        end = len(page)
        for marker in ('<script', '<div class="rich_media_tool', 'id="js_pc_qr_code"',
                       '<div class="rich_media_area_extra'):
            pos = page.find(marker, start)
            if 0 < pos < end:
                end = pos
        return page[start:end]

    @classmethod
    def text_of(cls, page):
        """正文转纯文本：去标签、解实体、压空白。

        有些公众号把岗位直接写在正文里（"招聘护士3名、医师2名"），
        没有表格也没有截图，只靠图片识别会漏掉这一类。
        """
        html = cls.content_of(page)
        if not html:
            return ''
        html = re.sub(r'(?i)<br\s*/?>', '\n', html)
        html = re.sub(r'(?i)</(p|div|li|tr|h[1-6]|section)>', '\n', html)
        html = re.sub(r'<[^>]+>', '', html)
        text = html_mod.unescape(html_mod.unescape(html))
        lines = [ln.strip() for ln in text.splitlines()]
        return '\n'.join(ln for ln in lines if ln)

    @staticmethod
    def _decode_escaped(page):
        """还原页面里被转义过的 HTML 片段。

        微信把「正文」以 JS 字符串存在 ``content_noencode`` 里，形如::

            \\x3ca target=\\x22_blank\\x22 data-miniprogram-appid=\\x22wx...\\x22

        不解码的话，附件/小程序链接根本匹配不到 —— 纯附件文章的正文和
        配图都是空的，解码是唯一能发现 xlsx 的途径。
        """
        if '\\x3c' not in page and '\\x22' not in page:
            return page
        mapping = (('\\x3c', '<'), ('\\x3e', '>'), ('\\x22', '"'),
                   ('\\x26', '&'), ('\\x0a', '\n'), ('\\x27', "'"),
                   ('\\/', '/'))
        out = page
        for a, b in mapping:
            if a in out:
                out = out.replace(a, b)
        return out

    @classmethod
    def attachments_of(cls, page):
        """页面里的附件（xlsx / xls / docx / pdf 等），按优先级返回。

        两种形式都要认：
          * 直链附件：``<a data-linktype="file" data-linkurl="https://...">``
            —— 可以直接 HTTP 下载，表格结构最完整；
          * 小程序附件：``data-miniprogram-appid=... data-miniprogram-path=...``
            —— 下载要小程序 session，普通请求拿不到，只能记下来告诉调用方。

        返回 [{'url': 可下载地址或空, 'mini': (appid, path) 或 None, 'name': 文件名}]。
        """
        # 微信把正文塞在 content_noencode 里且做了 \x3c 转义，
        # 不解码的话纯附件文章（正文/配图都空）一个附件都发现不了
        page = cls._decode_escaped(page)
        out = []
        seen = set()

        def add(url, mini, name):
            key = url or ('mini:' + (mini[1] if mini else ''))
            if not key or key in seen:
                return
            seen.add(key)
            out.append({'url': url or '', 'mini': mini, 'name': name})

        # ① 直链附件：<a ... data-linkurl="...">，文件名在标签文字里
        for m in re.finditer(r'<a\b[^>]*data-linkurl="([^"]+)"[^>]*>(.*?)</a>',
                             page, re.I | re.S):
            url = html_mod.unescape(m.group(1)).replace('\\x26', '&').replace('\\/', '/')
            name = _plain_text(m.group(2))
            if re.search(r'\.(?:xlsx?|docx?|pdf|zip|rar)(?:$|\?)', url, re.I) \
                    or re.search(r'\.(?:xlsx?|docx?|pdf)', name, re.I):
                add(url, None, name)

        # ② 小程序附件：<a ... data-miniprogram-appid="..." data-miniprogram-path="...">
        for m in re.finditer(r'<a\b[^>]*data-miniprogram-appid="([^"]+)"[^>]*'
                             r'data-miniprogram-path="([^"]+)"[^>]*>(.*?)</a>',
                             page, re.I | re.S):
            appid = m.group(1)
            path = html_mod.unescape(m.group(2)).replace('\\x26', '&')
            name = _plain_text(m.group(3))
            # 只收附件类（路径里带 file，或名字是文档扩展名）
            if 'file' in path.lower() or re.search(r'\.(?:xlsx?|docx?|pdf)', name, re.I):
                add('', (appid, path), name)

        # ③ 裸的 xlsx 直链（少数模板直接给 URL）
        for m in re.finditer(r'(https?://[^\s"\'<>\\)]+\.(?:xlsx?))(?!\w)', page, re.I):
            add(html_mod.unescape(m.group(1)), None, '')

        # 直链优先，其次小程序
        out.sort(key=lambda a: 0 if a['url'] else 1)
        return out

    @classmethod
    def download_attachment(cls, item, dest_dir):
        """下载直链附件，返回本地路径；下载不了返回 ''。"""
        url = item.get('url') or ''
        if not url:
            return ''                        # 小程序附件，HTTP 拿不到
        try:
            os.makedirs(dest_dir, exist_ok=True)
            name = item.get('name') or os.path.basename(url.split('?')[0]) or 'attachment'
            name = re.sub(r'[\\/:*?"<>|]+', '_', name)[-80:]
            if not os.path.splitext(name)[1]:
                name += '.xlsx'
            target = os.path.join(dest_dir, name)
            if os.path.exists(target) and os.path.getsize(target) > 1024:
                return target
            resp = cls.session().get(url, timeout=60, allow_redirects=True,
                                     headers={'User-Agent': cls.UA,
                                              'Referer': cls.MP + '/'})
            body = resp.content or b''
            if len(body) < 1024:
                return ''
            with open(target, 'wb') as f:
                f.write(body)
            logger.info('【%s】附件已下载：%s（%.0f KB）'
                        % (cls.web_name, os.path.basename(target), len(body) / 1024))
            return target
        except Exception as e:
            logger.warning('【%s】附件下载失败（%s）：%s'
                           % (cls.web_name, item.get('name') or url[:40], e))
            return ''

    @staticmethod
    def read_xlsx(path, max_rows=200):
        """把 xlsx 读成二维文本表格，直接可以喂给 _ask。

        只读第一个 sheet；超过 max_rows 行截断（岗位表不会那么长，
        截断是为了防止有人把整本台账传上来把 prompt 撑爆）。
        """
        try:
            from openpyxl import load_workbook
        except ImportError:
            return []
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                ws = wb.active
                rows = []
                for row in ws.iter_rows(max_row=max_rows, values_only=True):
                    cells = ['' if c is None else str(c).strip() for c in row]
                    while cells and not cells[-1]:
                        cells.pop()
                    if any(cells):
                        rows.append(cells)
                return rows
            finally:
                wb.close()
        except Exception as e:
            logger.warning('【%s】读取附件失败（%s）：%s'
                           % (Wechat.web_name, os.path.basename(str(path)), e))
            return []

    @classmethod
    def images_of(cls, page):
        """页面里的配图 URL（只要公众号图床，跳过头像/二维码/表情）。

        两种模板要分开处理，否则会一张图都拿不到：
          * 普通文章：正文在 #js_content 里，到 <script 之类的位置就算结束；
          * 新图文（picture_page）：**没有** #js_content，图片散在整页里。
            这种页面开头就有一个 <script>，如果还按"遇到 script 就结束"，
            结果就是 0 张图（实测：某篇 2.2MB 页面拿到 0 张图）。
        """
        start = page.find('id="js_content"')
        if start < 0:
            start = page.find("id='js_content'")

        if start < 0:
            body = page                      # 新图文模板：扫全页
        else:
            body = page[start:]
            end = len(body)
            for marker in ('<script', '<div class="rich_media_tool', 'id="js_pc_qr_code"',
                           '<div class="rich_media_area_extra'):
                pos = body.find(marker)
                if 0 < pos < end:
                    end = pos
            body = body[:end]

        urls, seen = [], set()
        for m in re.finditer(r'<img\b[^>]*>', body, re.I):
            tag = m.group(0)
            src = (re.search(r'data-src="([^"]+)"', tag)
                   or re.search(r'src="([^"]+)"', tag))
            if not src:
                continue
            # 页面里是 HTML 转义过的，\x26 是微信自己的转义
            url = (src.group(1).replace('&amp;', '&')
                   .replace('\\x26', '&').replace('\\/', '/'))
            if url.startswith('//'):
                url = 'https:' + url
            if not url.startswith('http'):
                continue
            # 图床不止 mmbiz.qpic.cn：正文里真正的岗位表常在 mmecoa.qpic.cn，
            # 只认 mmbiz 会把关键的表格图全部丢掉（实测一篇只剩 2 张装饰图）
            if '.qpic.cn/' not in url:
                continue
            if 'jump_author_avatar' in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    @classmethod
    def parse_article(cls, page, page_url=''):
        """HTML -> {title, account, published_at, images, canonical, ...}。

        失败抛 RuntimeError(kind, msg)：blocked 停整轮，其余跳过单篇。
        """
        if any(m in page for m in cls.BLOCK_MARKERS) and len(page) < 80000:
            raise RuntimeError('blocked: 微信返回了验证页（被临时限流），需等 10-30 分钟再跑')

        # 验证页是 302 过来的，最终 URL 才是证据
        if any(m in (page_url or '') for m in cls.CAPTCHA_MARKERS):
            raise RuntimeError('blocked: 被重定向到人机验证页，需等 10-30 分钟并降低频率')

        ret = cls._first_int((r"var ret = '(\d+)'", r'"ret":\s*(-?\d+)'), page)
        if ret not in (None, 0, 1):
            raise RuntimeError('upstream: 微信错误页 ret=%s（链接过期/已删/签名失效）' % ret)

        if any(m in page for m in cls.UPSTREAM_MARKERS):
            raise RuntimeError('upstream: 微信说这篇不在了（已删除 / 违规 / 已迁移）')

        title = cls._var(page, 'msg_title') or cls._meta(page, 'og:title')
        if not title:
            if any(m in page for m in cls.SESSION_MARKERS):
                raise RuntimeError('session: 微信返回了客户端/登录提示页')
            if len(page) < 30000:
                raise RuntimeError('blocked: 页面只有 %d 字节，像是未登录或限流' % len(page))
            raise RuntimeError('shape: 页面 %d 字节但没有标题（多半是微信改版）' % len(page))

        og_url = cls._meta(page, 'og:url') or page_url or ''

        ct = cls._first_int((r'var ct = "(\d+)"', r"var ct = '(\d+)'",
                             r'create_time["\']?\s*[:=]\s*["\']?(\d{9,})'), page)

        # 页面里的 var 优先；老模板没有 var 的，从 og:url 的查询串里取
        try:
            og_query = dict(parse_qsl(urlsplit(og_url).query, keep_blank_values=True))
        except ValueError:
            og_query = {}

        biz = cls._var(page, 'biz') or og_query.get('__biz', '')
        mid = (cls._var(page, 'mid') or cls._var(page, 'appmsgid')
               or og_query.get('mid', ''))
        idx = cls._var(page, 'idx') or og_query.get('idx', '') or '1'
        sn_match = re.search(r'var sn = "([0-9a-f]{16,})"', page)
        sn = (sn_match.group(1) if sn_match else '') or og_query.get('sn', '')

        if mid:
            # 逐项判空，不能用 endswith('=') —— __biz 的 padding 本身就以 = 结尾
            parts = []
            if biz:
                parts.append('__biz=' + biz)
            parts.append('mid=' + str(mid))
            parts.append('idx=' + str(idx))
            if sn:
                parts.append('sn=' + str(sn))
            canonical = cls.MP + '/s?' + '&'.join(parts)
        else:
            canonical = og_url

        published = ''
        if ct:
            try:
                published = datetime.fromtimestamp(int(ct), cls.CST).strftime('%Y-%m-%d')
            except (OverflowError, OSError, ValueError):
                published = ''
        if not published:
            m = re.search(r'id="publish_time"[^>]*>\s*([^<]{8,30})<', page)
            if m:
                published = m.group(1).strip()

        return {
            'title': str(title).replace('&amp;', '&'),
            # 公众号名三种写法都见过：
            #   var nick_name = "..."      老模板
            #   nick_name: '医护知音'       当前模板（JSON 风格，无 var）
            # 只认 nick_name，不认 nickname —— 后者会匹配到
            # data-miniprogram-nickname（小程序名），不是公众号名
            'account': (cls._var(page, 'nick_name')
                        or cls._find(page,
                                      r'\bnick_name\s*:\s*["\']([^"\']+)',
                                      r'\bnick_name["\']?\s*[:=]\s*["\']([^"\']+)')
                        or ''),
            'published_at': published,
            'images': cls.images_of(page),
            'text': cls.text_of(page),
            'canonical': canonical,
            'biz': biz, 'mid': str(mid or ''), 'idx': str(idx or ''), 'sn': sn,
            'record_id': ('%s:%s:%s' % (biz, mid, idx)) if mid else canonical,
        }

    # ==================== 视觉模型 ====================

    @staticmethod
    def _encode(path):
        """图片 -> data URL。

        MIME 按**文件头**判断，不看扩展名：图床常返回 GIF/WebP 而文件名是 .jpg，
        扩展名不对会让部分接口直接拒收整张图。
        """
        with open(path, 'rb') as f:
            body = f.read()
        head = body[:16]
        if head.startswith(b'\xff\xd8\xff'):
            mime = 'jpeg'
        elif head.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'png'
        elif head.startswith(b'GIF8'):
            mime = 'gif'
        elif head[:4] == b'RIFF' and head[8:12] == b'WEBP':
            mime = 'webp'
        elif head.startswith(b'BM'):
            mime = 'bmp'
        else:
            suffix = os.path.splitext(str(path))[1].lower().lstrip('.')
            mime = 'jpeg' if suffix in ('jpg', 'jpeg') else (suffix or 'png')
        return 'data:image/%s;base64,%s' % (mime, base64.b64encode(body).decode())

    @classmethod
    def _ask(cls, images, title='', text='', sheet=''):
        """调一次模型。

        images 可以为空；sheet 是 xlsx 附件的二维表格文本（优先于图片和正文）。
        三者都可能同时为空（只发标题，用于识别单位/省市）。
        """
        key = cls.vlm_api_key()
        if not key:
            return {'ok': False, 'error': '未填写视觉模型 Key（wechat.py 顶部的 Wechat.API_KEY）'}

        text = (text or '').strip()
        if len(text) > cls.MAX_TEXT_CHARS:
            text = text[:cls.MAX_TEXT_CHARS] + '\n…（正文过长，已截断）'
        sheet = (sheet or '').strip()
        if len(sheet) > cls.MAX_TEXT_CHARS:
            sheet = sheet[:cls.MAX_TEXT_CHARS] + '\n…（表格过长，已截断）'

        head = '文章标题：%s\n\n' % (title or '（无标题）')
        if sheet:
            head += '附件表格（xlsx，机器可读，以此为准）：\n%s\n\n' % sheet
        if text:
            head += '正文文字：\n%s\n\n' % text
        else:
            head += '正文文字：（无）\n\n'
        if not sheet and not text:
            head += '（本篇文章没有正文和附件，岗位信息只可能在图片里）\n\n'

        content = [{'type': 'text', 'text': head + cls.PROMPT}]
        # 图片逐个编码；损坏/丢失的单张跳过，不能让它毁掉整篇
        picked = 0
        for path in images:
            if picked >= cls.MAX_IMAGES:
                break
            try:
                data_url = cls._encode(path)
            except Exception as e:
                logger.warning('【%s】图片编码失败（跳过）：%s -> %s'
                               % (cls.web_name, os.path.basename(str(path)), e))
                continue
            content.append({'type': 'image_url',
                            'image_url': {'url': data_url, 'detail': cls.DETAIL}})
            picked += 1

        body = {
            'model': cls.MODEL,
            'messages': [{'role': 'user', 'content': content}],
            'temperature': 0.0,
            'max_tokens': cls.MAX_TOKENS,
        }
        try:
            resp = cls.session().post(cls.BASE_URL, json=body, timeout=cls.VLM_TIMEOUT,
                                      headers={'Authorization': 'Bearer %s' % key})
            raw = resp.text
        except requests.RequestException as e:
            return {'ok': False, 'error': '请求视觉模型失败：%s' % e}
        except Exception as e:
            return {'ok': False, 'error': '调用视觉模型异常：%s: %s'
                                          % (type(e).__name__, e)}

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {'ok': False, 'error': '响应不是 JSON：%s' % raw[:200]}
        if isinstance(payload, dict) and payload.get('error'):
            return {'ok': False, 'error': str(payload['error'])[:300]}
        try:
            choice = payload['choices'][0]
            answer = choice['message']['content']
        except (KeyError, IndexError, TypeError):
            return {'ok': False, 'error': '响应结构异常：%s' % raw[:200]}

        # 额度被思考用完时 content 是空的，这不叫"没岗位"，要单独报出来
        if not (answer or '').strip():
            usage = payload.get('usage') or {}
            reason = choice.get('finish_reason')
            reasoning = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
            return {'ok': False,
                    'error': '模型没有输出正文（finish_reason=%s, reasoning_tokens=%s）'
                             '—— 多半是 max_tokens 不够' % (reason, reasoning)}
        return {'ok': True, 'answer': answer, 'usage': payload.get('usage') or {}}

    @staticmethod
    def _parse_rows(answer):
        """从模型输出里取 (单位, 省份, 城市, 岗位列表)。

        期望格式 {"单位":..., "省份":..., "城市":..., "岗位":[...]}；
        也兼容模型直接返回数组（老提示词/模型忽略格式时），那种情况
        单位/省份/城市留空。
        """
        text = (answer or '').strip()
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()

        # 先按对象解析
        start, end = text.find('{'), text.rfind('}')
        if 0 <= start < end:
            try:
                obj = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                unit = str(obj.get('单位') or '').strip()
                province = str(obj.get('省份') or '').strip()
                city = str(obj.get('城市') or '').strip()
                jobs = obj.get('岗位')
                if isinstance(jobs, list):
                    return unit, province, city, [r for r in jobs if isinstance(r, dict)]

        # 退回数组格式
        start, end = text.find('['), text.rfind(']')
        if start < 0 or end <= start:
            return '', '', '', []
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return '', '', '', []
        return '', '', '', [row for row in data if isinstance(row, dict)]

    @classmethod
    def _gate(cls, row):
        """校验闸门：岗位名必须像岗位，人数必须能回溯到依据片段。"""
        name = str(row.get('岗位') or '').strip()
        if not looks_like_position(name):
            return False, '岗位名不合法'
        if _PLACEHOLDER.search(normalize_position_name(name)):
            return False, '表格占位符'
        evidence = str(row.get('依据') or '')
        count = row.get('人数')
        if count is not None:
            try:
                value = int(count)
            except (TypeError, ValueError):
                return False, '人数不是整数'
            if not (1 <= value <= 200):
                return False, '人数越界'
            if evidence and str(value) not in evidence:
                return False, '人数未出现在依据片段里（疑似幻觉）'
        return True, ''

    @classmethod
    def vlm_positions(cls, images, title='', text='', sheet='', sheet_note=''):
        """按优先级取岗位：图片 > 正文 > xlsx 附件。

        顺序（用户指定）：
          1. 逐张识别图片 —— **识别一张就打印一张的结果**（界面日志同步可见），
             最后把所有图片读到岗位合并；
          2. 图片没读到 -> 正文；
          3. 正文也没有 -> 最后才用 xlsx 附件。

        sheet 是已经拼好的表格文本；sheet_note 说明附件状态（给失败提示用）。
        返回 (岗位行, 元信息)，meta['source'] 是 'image' / 'text' / 'xlsx' / ''。
        """
        meta = {'rows': 0, 'rejected': [], 'error': '', 'source': '',
                'unit': '', 'province': '', 'city': ''}
        if not images and not (title or '').strip() and not (text or '').strip() \
                and not sheet:
            meta['error'] = '没有附件、配图、标题或正文'
            return [], meta

        # ① 图片：逐张送模型，识别一张显示一张
        image_rows = cls._vlm_images(images, title, meta)
        # 图片阶段可能已经从模型的输出里认出了单位/省市（存在 _unit 里）
        unit, province, city = (meta.pop('_unit', ''), meta.pop('_province', ''),
                                meta.pop('_city', ''))
        if image_rows:
            meta.update({'unit': unit, 'province': province, 'city': city,
                         'source': 'image', 'rows': len(image_rows), 'error': ''})
            return image_rows, meta

        # ② 正文（图片没读到）
        if (text or '').strip():
            if images:
                logger.info('【%s】图片没读到岗位，改用正文重试' % cls.web_name)
            result = cls._ask([], title, text, '')
            if result.get('ok'):
                u2, p2, c2, rows2 = cls._parse_rows(result['answer'])
                if rows2:
                    meta.update({'unit': u2, 'province': p2, 'city': c2,
                                 'source': 'text'})
                    return cls._finish_rows(rows2, meta)
                if not unit:
                    unit, province, city = u2, p2, c2
                elif not meta['error']:
                    meta['error'] = ''
            elif not meta['error']:
                meta['error'] = result.get('error') or ''

        # ③ xlsx 附件（最后才用）
        if sheet:
            if images or (text or '').strip():
                logger.info('【%s】正文没读到岗位，改用 xlsx 附件重试' % cls.web_name)
            result = cls._ask([], title, '', sheet)
            if result.get('ok'):
                u3, p3, c3, rows3 = cls._parse_rows(result['answer'])
                if rows3:
                    meta.update({'unit': u3, 'province': p3, 'city': c3,
                                 'source': 'xlsx'})
                    return cls._finish_rows(rows3, meta)
                if not unit:
                    unit, province, city = u3, p3, c3
            elif not meta['error']:
                meta['error'] = result.get('error') or ''

        # ④ 附件存在但拿不到（小程序）：仍然发一次，让模型从标题认单位/省市
        #    否则纯附件文章会一条日志都没有、连单位都空着
        if sheet_note and not images and not (text or '').strip():
            result = cls._ask([], title, '', '')
            if result.get('ok'):
                u4, p4, c4, _ = cls._parse_rows(result['answer'])
                if not unit:
                    unit, province, city = u4, p4, c4

        meta.update({'unit': unit, 'province': province, 'city': city})
        if not meta['error']:
            # 附件拿不到且没有图/正文可读时，说清楚原因，别只说"没读到岗位"
            meta['error'] = sheet_note or '图片、正文和附件都没读到岗位'
        return [], meta

    @classmethod
    def _vlm_images(cls, images, title, meta):
        """逐张识别图片，识别一张就把这一张的岗位打进日志，返回合并后的岗位行。

        OCR 预筛在 download_images 里做完了（不合格的图不会被保存），
        这里拿到的都是「可能有岗位信息」的图，逐张送 AI：
        一篇 8 张图一次性送过去要等所有图都看完才有输出，界面上几十秒没动静；
        逐张送则每看完一张就出一行「图片 3/8：2 条岗位」，
        而且某张图糊了/认错不会带偏其他张。
        """
        if not images:
            return []
        total = len(images)
        merged, seen = [], set()
        for idx, path in enumerate(images, start=1):
            name = os.path.basename(str(path))
            result = cls._ask([path], title, '', '')
            if not result.get('ok'):
                err = result.get('error') or '未知错误'
                if not meta.get('error'):
                    meta['error'] = err
                logger.warning('【%s】  图片 %d/%d（%s）：识别失败 - %s'
                               % (cls.web_name, idx, total, name, err[:60]))
                continue

            u, p, c, raw = cls._parse_rows(result['answer'])
            if not meta.get('_unit') and u:
                meta['_unit'], meta['_province'], meta['_city'] = u, p, c

            rows, _ = cls._finish_rows(list(raw), {'rejected': []})
            if not rows:
                logger.info('【%s】  图片 %d/%d（%s）：没读到岗位'
                            % (cls.web_name, idx, total, name))
                continue

            logger.info('【%s】  图片 %d/%d（%s）：%d 条岗位'
                        % (cls.web_name, idx, total, name, len(rows)))
            added = 0
            for job in rows:
                # 同一张表跨页时，下一页常重复上一页的末行。
                # 按「岗位+人数+学历」去重，比只比岗位名安全（同名不同要求不会被吞）。
                key = (job.get('岗位') or '', str(job.get('人数') or ''),
                       job.get('学历') or '')
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                merged.append(job)
                added += 1
                logger.info('【%s】    %d. %s'
                            % (cls.web_name, len(merged), cls.job_brief(job)))
            if not added:
                logger.info('【%s】    （这几条和前面的图重复，已跳过）'
                            % cls.web_name)
        return merged

    @classmethod
    def _finish_rows(cls, raw_rows, meta):
        """闸门过滤 + 依据补全，返回 (rows, meta)。"""
        rows, rejected = [], []
        for item in raw_rows:
            passed, reason = cls._gate(item)
            if not passed:
                rejected.append('%s（%s）' % (str(item.get('岗位'))[:12], reason))
                continue
            rows.append({
                '岗位': normalize_position_name(str(item.get('岗位')).strip()),
                '人数': int(item['人数']) if item.get('人数') is not None else '',
                '学历': str(item.get('学历') or '').strip(),
                '专业': str(item.get('专业') or '').strip(),
                '年龄': str(item.get('年龄') or '').strip(),
                '职称/资格': str(item.get('职称/资格') or '').strip(),
                '其他要求': str(item.get('其他要求') or '').strip()[:120],
                '依据': str(item.get('依据') or '')[:400],
            })

        # 把整表文本附到每行依据里：有些字段写在表头或相邻行，
        # 只留本行片段会导致核对时"值在原文找不到"
        if rows:
            whole = ' ｜ '.join(str(r.get('依据') or '').strip() for r in rows if r.get('依据'))
            for row in rows:
                own = str(row.get('依据') or '').strip()
                if whole and whole not in own:
                    row['依据'] = (own + ' ｜整表：' + whole)[:600]

        meta.update({'rows': len(rows), 'rejected': rejected})
        if rows:
            meta['error'] = ''
        return rows, meta

    @staticmethod
    def job_brief(job):
        """把一条岗位压成一行日志：岗位 | 人数 | 学历 | 专业 | 资格 | 其他。"""
        def val(key):
            v = job.get(key)
            if v in (None, ''):
                return '-'
            return str(v).replace('\n', ' ').strip()

        return ('%s | 人数:%s | 学历:%s | 专业:%s | 资格:%s | 其他:%s'
                % (val('岗位'), val('人数'), val('学历'), val('专业'),
                   val('职称/资格'), val('其他要求')))

    # ==================== 图片 OCR 预筛 ====================
    # 一篇公众号文章常带十几张图，其中大部分是封面、二维码、宣传海报、
    # 领导照片，真正的岗位表往往只有一两张。每张图都送视觉模型很贵
    # （base64 后几百 KB，一次调用几十秒），所以先用 OCR 粗筛一遍：
    # 只有文字里出现岗位迹象的图才送 AI。
    #
    # 用 Windows 自带的 OCR（Windows.Media.Ocr），不用 tesseract / rapidocr：
    #   * tesseract 要另外装 exe + 中文语言包，打包和部署都麻烦；
    #   * rapidocr 要带 numpy + opencv + onnxruntime，体积 180MB 以上；
    #   * 系统 OCR 是 Windows 组件，中文开箱可用，只额外占约 38MB。

    #: OCR 语言。中文 Windows 默认就装了 zh-Hans-CN。
    OCR_LANG = 'zh-Hans-CN'

    #: 命中任意一个词就认为「这张图可能有岗位信息」。
    #: 不用「招聘」「报名」这类词 —— 封面图和海报上几乎都有，会全部误判。
    OCR_STRONG_WORDS = (
        '岗位', '职位', '职称', '职务', '科室',
        '医师', '医生', '护士', '护师', '技师', '药师', '药剂',
        '护理', '临床', '影像', '检验', '麻醉', '超声', '助产',
        '学历', '专业', '人数', '名额', '招聘人数',
        '本科', '大专', '专科', '硕士', '博士', '研究生', '中专',
    )

    #: OCR 结果是否「看起来有岗位表」。text 为 None 表示没条件 OCR。
    @classmethod
    def ocr_looks_like_jobs(cls, text):
        """判断 OCR 出来的文字像不像岗位表。

        返回 True/False；text 为空或 None 都返回 False（调用方决定怎么兜底）。
        """
        if not text:
            return False
        # Windows OCR 会把中文逐字拆开，字之间带空格（"招 聘 岗 位 表"），
        # 不压掉空格的话任何关键词都匹配不上。
        flat = re.sub(r'\s+', '', text)
        if len(flat) < 8:
            return False
        hits = sum(1 for w in cls.OCR_STRONG_WORDS if w in flat)
        # 命中 2 个以上基本可以确定是岗位表；
        # 只命中 1 个时要求文字够多，避免"护士"两个字就把海报送进去。
        return hits >= 2 or (hits >= 1 and len(flat) >= 15)

    @classmethod
    def ocr_text(cls, path):
        """调用 Windows OCR 提取图片文字。

        返回 (文字, 是否可用)：
          ('...', True)   OCR 跑成功了（文字可能为空 = 图上没字）
          ('', False)     OCR 不可用（非 Windows / 没装 winsdk / 没中文语言包）
        不可用时调用方应当放行所有图片，退回原来的「全部送 AI」行为。
        """
        try:
            from winsdk.windows.globalization import Language
            from winsdk.windows.graphics.imaging import BitmapDecoder
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.storage import FileAccessMode, StorageFile
        except Exception:
            return '', False

        src = os.path.abspath(str(path))
        work = src
        try:
            work = cls._shrink_for_ocr(src)
            lines = cls._run_ocr_async(work)
            if lines is None:
                return '', False
            return '\n'.join(lines), True
        except Exception as e:
            logger.warning('【%s】OCR 失败（%s）：%s'
                           % (cls.web_name, os.path.basename(src), e))
            return '', False
        finally:
            # 只有自己缩过图才需要清临时文件，原件不动
            if work != src:
                try:
                    os.remove(work)
                except OSError:
                    pass

    @classmethod
    def _run_ocr_async(cls, path):
        """在独立事件循环里跑 OCR。返回文字行列表，引擎建不起来时返回 None。"""
        import asyncio

        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage import FileAccessMode, StorageFile

        async def _read():
            engine = OcrEngine.try_create_from_language(Language(cls.OCR_LANG))
            if engine is None:
                # 兜底：用当前用户配置的语言（中文 Windows 上就是 zh-Hans-CN）
                engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                return None
            f = await StorageFile.get_file_from_path_async(path)
            stream = await f.open_async(FileAccessMode.READ)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(bitmap)
            return [ln.text for ln in result.lines]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_read())

        # 当前线程已有事件循环（正常采集流程不会走到这里）：
        # asyncio.run 会报错，改到独立线程里跑一个自己的循环
        import threading
        box = {}

        def _worker():
            try:
                box['v'] = asyncio.run(_read())
            except Exception as e:
                box['e'] = e
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(60)
        if 'e' in box:
            raise box['e']
        return box.get('v')

    @classmethod
    def _shrink_for_ocr(cls, src):
        """OCR 引擎对图片尺寸有限制（通常 10000px），超了就等比缩小。

        返回可用于 OCR 的路径；不需要缩小就原样返回 src。
        """
        try:
            from PIL import Image
            from winsdk.windows.media.ocr import OcrEngine
            limit = int(getattr(OcrEngine, 'max_image_dimension', 10000) or 10000)
        except Exception:
            return src
        try:
            with Image.open(src) as img:
                w, h = img.size
                if max(w, h) <= limit:
                    return src
                ratio = limit / float(max(w, h))
                small = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))),
                                   Image.LANCZOS)
                if small.mode not in ('RGB', 'L'):
                    small = small.convert('RGB')
                out = src + '.ocr.jpg'
                small.save(out, 'JPEG', quality=90)
                return out
        except Exception:
            return src

    @classmethod
    def screen_image(cls, path):
        """OCR 预筛一张图。True=有岗位信息，False=明显没有，None=判断不了。

        None 的语义是「该放行」：OCR 不可用或出错时宁可多花一次 AI 调用，
        也不能把真正的岗位表丢掉。
        """
        text, usable = cls.ocr_text(path)
        if not usable:
            return None
        if cls.ocr_looks_like_jobs(text):
            return True
        return False

    # ==================== 配图下载 ====================

    @classmethod
    def download_images(cls, urls, dest, limit=15):
        """下载配图：先落盘，再用 OCR 判断，不符合的删掉。

        流程（每张图）：
          1. 下载并保存到目标文件；
          2. 太小（图标/分割线）的删掉；
          3. OCR 粗筛 —— 没有岗位迹象的（封面、二维码、海报）删掉；
          4. 通过检查的留下。

        最终目录里只有可能有岗位信息的图；重跑时直接复用这些。
        OCR 不可用时一律保留（宁可多存几张，不能丢岗位表）。
        """
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as e:
            logger.warning('【%s】创建图片目录失败：%s' % (cls.web_name, e))
            return []

        urls = list(urls)[:limit]
        total = len(urls)
        saved, dropped = [], 0
        for idx, url in enumerate(urls, start=1):
            # 扩展名按 URL 里的真实格式取：图上常是 gif/webp，写成 .jpg 会存错
            low = url.lower()
            for ext in ('.png', '.gif', '.webp', '.jpg', '.jpeg', '.bmp'):
                if ext in low:
                    break
            else:
                ext = '.jpg'
            ext = '.jpg' if ext == '.jpeg' else ext

            # 编号用「第几张」而不是「已存几张」：中间有图被删掉时，
            # 用已存数量编号会让后面的图整体挪位，重跑时复用判断就全乱了。
            target = os.path.join(dest, '%02d%s' % (idx, ext))

            # 已下过就复用：重跑同一篇不该再向图床要一遍
            try:
                if os.path.exists(target) and os.path.getsize(target) > cls.MIN_IMAGE_BYTES:
                    saved.append(target)
                    continue
            except OSError:
                pass

            try:
                resp = cls.session().get(url, timeout=20,
                                         headers={'Referer': cls.MP + '/',
                                                  'User-Agent': cls.UA})
                body = resp.content or b''
                with open(target, 'wb') as f:
                    f.write(body)
            except (requests.RequestException, OSError) as e:
                logger.warning('【%s】  图片 %d/%d 下载失败：%s'
                               % (cls.web_name, idx, total, e))
                cls._drop_file(target)
                continue

            # 保存后再判断：不符合的直接删掉
            if len(body) < cls.MIN_IMAGE_BYTES:
                cls._drop_file(target)           # 图标、分割线、加载占位
                continue
            if cls.screen_image(target) is False:
                dropped += 1
                logger.info('【%s】  图片 %d/%d：OCR 未发现岗位信息，已删除'
                            % (cls.web_name, idx, total))
                cls._drop_file(target)
                continue

            saved.append(target)

        if total:
            note = '，OCR 筛掉 %d 张' % dropped if dropped else ''
            logger.info('【%s】配图 %d 张，保存 %d 张%s'
                        % (cls.web_name, total, len(saved), note))
        return saved

    @staticmethod
    def _drop_file(path):
        """删掉一张图；不存在或删不掉都不该影响整篇采集。"""
        try:
            os.remove(path)
        except OSError:
            pass

    # ==================== 采集（与其它平台同名同形） ====================

    @classmethod
    def get_page_info(cls, url, media_root=None):
        """抓一篇文章并识别岗位。返回 dict 或 None（与其它采集类保持一致）。

        链接不做可用性判断 —— 扫描阶段已经筛过，这里只管访问；
        打不开就让微信自己报错（ret / 验证页 / 删稿），按失败处理。

        dict 内容：
            {url, title, account, published_at, canonical, record_id, unit,
             province, city, source, jobs: [...], judged, error: '失败原因'}
        """
        if cls._should_stop():
            return None

        extra = {'url': url, 'title': '', 'account': '', 'published_at': '',
                 'canonical': '', 'record_id': '', 'unit': '', 'province': '',
                 'city': '', 'source': '', 'jobs': [], 'judged': '', 'error': ''}
        if not url:
            extra['error'] = '空链接'
            return extra

        # 跳验证页是「一次性」的：实测同一条 URL 被拦后，立刻再请求一次就正常了。
        # 所以这里原地重试几次，比直接跳过或停整轮划算得多。
        attempt = 0
        resp = None
        art = {}
        # 发请求用 request_url（缺 chksm 的补占位值），日志和清单里仍是原样 URL
        fetch_url = request_url(url)
        while True:
            attempt += 1
            if cls._should_stop():
                return None
            try:
                resp = cls.session().get(fetch_url, timeout=cls.REQUEST_TIMEOUT,
                                         allow_redirects=True,
                                         headers={'User-Agent': cls.UA,
                                                  'Referer': cls.MP + '/'})
                resp.encoding = 'utf-8'
                art = cls.parse_article(resp.text, resp.url)
                break
            except requests.RequestException as e:
                extra['error'] = 'network: 请求失败：%s' % e
                return extra
            except RuntimeError as e:
                msg = str(e)
                # 只有验证页值得重试；删稿/违规（upstream）重试也没用
                if msg.startswith('blocked') and attempt <= cls.BLOCK_RETRY:
                    logger.warning('【%s】第 %d 次被验证页拦，%d 秒后重试同一条'
                                   % (cls.web_name, attempt,
                                      cls.BLOCK_RETRY_WAIT * attempt))
                    if not cls._sleep(cls.BLOCK_RETRY_WAIT * attempt):
                        return None       # 用户在等待期间点了停止
                    continue
                # "blocked: ..." / "upstream: ..." / "session: ..." —— kind 决定上层停不停
                extra['error'] = msg
                return extra
            except Exception as e:
                # 解析器自身出错（页面结构异常）：当单篇失败，不拖垮整轮
                extra['error'] = 'internal: 解析异常 %s: %s' % (type(e).__name__, e)
                return extra

        extra.update({k: art.get(k) or '' for k in
                      ('title', 'account', 'published_at', 'canonical', 'record_id')})

        xlsx_atts = []
        try:
            # ① 先看有没有 xlsx 附件（机器可读，最准）
            sheet_text, sheet_note = '', ''
            atts = cls.attachments_of(resp.text)
            xlsx_atts.extend(
                a for a in atts
                if re.search(r'\.xlsx?$', (a.get('name') or ''), re.I)
                or 'xlsx' in (a.get('url') or '').lower())
            if xlsx_atts:
                slug = re.sub(r'[^0-9A-Za-z_]+', '_',
                              str(art.get('record_id') or 'unknown'))[-60:]
                dest = os.path.join(media_root or ATTACH_DIR, slug)
                table = []
                for item in xlsx_atts:
                    local = cls.download_attachment(item, dest)
                    if local:
                        table = cls.read_xlsx(local)
                        if table:
                            logger.info('【%s】读取附件 %s：%d 行'
                                        % (cls.web_name,
                                           os.path.basename(local), len(table)))
                            break
                if table:
                    # 二维数组转成 TSV 文本，比 JSON 省 token 也更好读
                    sheet_text = '\n'.join('\t'.join(r) for r in table)
                else:
                    names = '、'.join((a.get('name') or '附件')[:20] for a in xlsx_atts)
                    if all(not a.get('url') for a in xlsx_atts):
                        sheet_note = ('文章带 xlsx 附件（%s），但在小程序里'
                                      '（需要微信客户端才能打开），无法直接下载' % names)
                    else:
                        sheet_note = '附件下载或解析失败：%s' % names
                    logger.warning('【%s】%s' % (cls.web_name, sheet_note))

            # ② 图片：第一张是公众号头图/封面，从来不含岗位表，直接跳过省一次下载
            files = []
            if art.get('images'):
                images = art['images'][1:-1]
                if images:
                    slug = re.sub(r'[^0-9A-Za-z_]+', '_',
                                  str(art.get('record_id') or 'unknown'))[-60:]
                    dest = os.path.join(media_root or IMAGE_DIR, slug)
                    files = cls.download_images(images, dest)

            # ③ 按 图片 -> 正文 -> xlsx 的顺序识别（vlm_positions 内部降级，
            #    图片是逐张识别、识别一张显示一张）
            jobs, meta = cls.vlm_positions(files, art.get('title') or '',
                                           art.get('text') or '',
                                           sheet_text, sheet_note)
        except Exception as e:
            extra['error'] = 'internal: 识别异常 %s: %s' % (type(e).__name__, e)
            return extra

        extra['jobs'] = jobs
        extra['unit'] = meta.get('unit') or ''
        extra['province'] = meta.get('province') or ''
        extra['city'] = meta.get('city') or ''
        extra['source'] = meta.get('source') or ''
        extra['attachments'] = len(xlsx_atts)
        extra['error'] = '' if jobs else (meta.get('error') or '附件、图片和正文都没读到岗位')
        return extra

    @classmethod
    def parser_page_info(cls, page_info, crawl_date=None):
        """把一篇的识别结果解析成 xlsx 行。

        返回 [[采集日期, 来源, 省份, 城市, ...], ...]，列顺序即 XLSX_HEADERS。
        省份/城市由模型从单位名判断；单位名填「公司名称」列。
        """
        crawl_date = crawl_date or datetime.now().strftime('%Y-%m-%d')
        if not page_info or not page_info.get('jobs'):
            return []

        rows = []
        # 岗位编号用页面里解析出来的 record_id（biz:mid:idx），它只在访问过之后才有
        basis_prefix = page_info.get('record_id') or page_info.get('canonical') \
            or page_info.get('url') or ''
        # 公司名称只用模型的识别结果。**不能退回公众号名** —— 公众号是发布者
        # （医护知音），拿它当公司名会把每篇没有明确单位的文章都写成"医护知音"。
        unit = page_info.get('unit') or ''
        province = page_info.get('province') or ''
        city = page_info.get('city') or ''
        published = page_info.get('published_at') or ''

        for job in page_info['jobs']:
            # 岗位编号：同一篇 + 同一岗位名 => 同一编号，重跑会更新而不是新增。
            # 用人数的哈希会把"人数修正"当成新岗位，所以不参与。
            basis = '%s:%s' % (basis_prefix, job.get('岗位') or '')
            job_no = 'WX' + hashlib.md5(basis.encode('utf-8')).hexdigest()[:14]

            desc_parts = []
            if published:
                desc_parts.append('发布时间：%s' % published)
            for key in ('年龄', '职称/资格', '其他要求', '依据'):
                if job.get(key):
                    desc_parts.append('%s：%s' % (key, job[key]))

            # 工作地点：省份 + 城市 + 单位名；单位名里已经含城市就不重复拼
            # （"四川广安广安市岳池县妇幼保健院" -> "广安市岳池县妇幼保健院"）
            if city and city in unit:
                place = unit
            else:
                place = ''.join(p for p in (province, city, unit) if p)

            # 18 个列值，顺序与 XLSX_HEADERS 去掉前四列后一致
            values = [
                job.get('岗位') or '',                        # 职位名称
                job_no,                                      # 岗位编号
                unit,                                        # 公司名称
                '', '', '',                                  # 公司性质/规模/行业
                '', '', '',                                  # 招聘类型/性质/类别
                '',                                          # 薪资范围
                job.get('人数') or '',                       # 招聘人数
                job.get('学历') or '',                       # 学历要求
                '',                                          # 经验要求
                job.get('专业') or '',                       # 专业要求
                place,                                       # 工作地点
                '', '',                                      # 详细地址/报名截止
                '；'.join(desc_parts),                       # 职位描述
            ]
            rows.append([crawl_date, cls.web_name, province, city] + values)
        return rows

    # ==================== 提取链接（界面按钮） ====================

    @classmethod
    def fetch_links(cls, biz=''):
        """扫微信内存，把新链接并入清单。返回 (新增条数, 清单总数, 待抓条数)。

        对应界面上的「提取公众号链接」按钮 —— 采集流程里不再自动扫内存，
        扫不扫、什么时候扫完全由用户点这个按钮决定。
        """
        try:
            if not os.path.exists(LINKS_FILE):
                cls._write_links({})     # get_links 里直接 open 读，先建空文件
            added = WechatMemReader().get_links(biz=biz)
        except Exception as e:
            logger.error('【%s】提取链接失败：%s' % (cls.web_name, e))
            raise

        try:
            data, deal_links = cls.load_links()
        except FileNotFoundError:
            data, deal_links = {}, []
        logger.info('【%s】提取完成：新增 %s 条，清单共 %d 条，待抓 %d 条'
                    % (cls.web_name, added, len(data), len(deal_links)))
        return added, len(data), len(deal_links)

    # ==================== 主流程 ====================

    @classmethod
    def run(cls, data_file='医护知音数据.xlsx', biz='', pause_event=None,
            is_running=None, on_progress=None,
            on_page=None, on_data=None, on_complete=None, on_error=None):
        """采集入口：读链接清单 -> 逐篇抓取识别 -> 增量写入 xlsx。

        **不扫微信内存**：链接统一由界面上的「提取公众号链接」按钮写入清单
        （见 fetch_links）。这样「开始采集」只做一件事 —— 按清单抓取，
        连点几次也不会重复读 5 GB 内存。
        """
        if not cls.vlm_api_key():
            msg = ('【%s】未填写视觉模型 Key：请打开 wechat.py，'
                   '把 Wechat.API_KEY 改成你的 sk-xxx' % cls.web_name)
            logger.error(msg)
            return

        # ① 读清单：清单不存在时 load_links 会抛 FileNotFoundError，当作空清单
        try:
            data, deal_links = cls.load_links()
        except FileNotFoundError:
            data, deal_links = {}, []

        # ② 检查清单
        logger.info('【%s】待抓 %d 条（清单共 %d 条）'
                    % (cls.web_name, len(deal_links), len(data)))

        if not data:
            logger.error('【%s】链接清单为空：先点「提取公众号链接」扫一遍内存，'
                         '或在微信里打开过公众号文章再重试' % cls.web_name)
            return
        if not deal_links:
            logger.info('【%s】没有待抓的文章（清单 %d 条的 status 都是 true）'
                        % (cls.web_name, len(data)))
            return
        todo = deal_links


        # ② 打开工作簿（表头、样式、去重索引都交给 BaseSpider）
        wb, ws = cls.set_column_style(data_file)
        yesterday_data = cls.load_yesterday_data(data_file)
        cls._begin_run(pause_event, is_running)

        # 界面在点「开始」时会把表格清空（_on_start 里 all_rows = []），
        # 所以先把文件里已有的行推给界面，否则爬取过程中表格一直是空的。
        if on_data:
            try:
                from getJobs import _read_xlsx_rows
                for row in _read_xlsx_rows(data_file)[1:]:      # 跳过表头
                    if row and str(row[0]).strip():
                        on_data(tuple(row))
            except Exception as e:
                logger.warning('【%s】加载已有数据到界面失败：%s' % (cls.web_name, e))

        all_rows, seen = [], cls.init_seen(yesterday_data)
        total_added, stopped, failed = 0, False, 0
        blocked_streak = 0        # 连续几条跳验证页，用来区分"偶发"和"真限流"
        started = time.time()

        try:
            for seq, url in enumerate(todo, start=1):
                # 暂停时阻塞；点停止立刻返回
                if not cls._wait():
                    logger.info('【%s】用户终止采集' % cls.web_name)
                    stopped = True
                    break

                # 在抓取之前就打，否则要等下载图片+调模型几十秒才看得到
                logger.info('【%s】[%d/%d] 开始爬取链接：%s'
                            % (cls.web_name, seq, len(todo), url))
                if on_progress:
                    on_progress(seq, len(todo), url)

                info = None
                added = 0
                crashed = ''
                try:
                    info = cls.get_page_info(url)
                except Exception as e:
                    # 异常不等于"这篇没岗位"：不能标 true，否则以后永远不再重试
                    crashed = '%s: %s' % (type(e).__name__, e)
                    logger.error('【%s】第%d篇异常：%s' % (cls.web_name, seq, crashed))
                    if on_error:
                        on_error('第%d篇：%s' % (seq, crashed))

                title = (info or {}).get('title') or str(url)[:60]
                if not info and not crashed:
                    stopped = True                # get_page_info 返回 None = 已点停止
                    break

                err = (info or {}).get('error') or ''
                if err.startswith('blocked'):
                    # 单条跳验证页是**偶发**的，不是 IP 限流 —— 实测连打 29 条
                    # 只有第 17 条被跳验证，第 18 条立刻恢复正常。
                    # 所以先跳过这一条继续跑，连续多次才认定真被限流。
                    blocked_streak += 1
                    logger.warning('【%s】本条跳验证页（连续 %d 次），跳过继续'
                                   % (cls.web_name, blocked_streak))
                    if blocked_streak >= cls.BLOCK_STREAK_LIMIT:
                        logger.error('【%s】连续 %d 条跳验证页，判定为限流，停止本轮：%s'
                                     % (cls.web_name, blocked_streak, err))
                        if on_error:
                            on_error(err)
                        stopped = True
                        break
                    failed += 1
                    if on_error:
                        on_error('%s：%s' % (title[:26], err))
                    # 不标 true（下次重试），继续下一条。
                    # 稍微多等一会儿：刚跳完验证立刻连打更容易再被拦。
                    if seq < len(todo):
                        cls._sleep(max(cls.DEFAULT_DELAY, 5.0))
                    continue
                blocked_streak = 0            # 成功一条就把计数清零

                if crashed or (err and not (info or {}).get('jobs')):
                    failed += 1
                    why = crashed or err
                    logger.info('【%s】   爬取结果：失败 - %s' % (cls.web_name, why))
                    if on_error and not crashed:
                        on_error('%s：%s' % (title[:26], err))
                else:
                    info = info or {}
                    parsed = cls.parser_page_info(info)
                    added = cls._append_rows(parsed, all_rows, seen, ws, write=True,
                                             on_data=on_data)
                    total_added += added
                    jobs = info.get('jobs') or []
                    logger.info('【%s】   公司名称：%s（%s%s）'
                                % (cls.web_name, info.get('unit') or '-',
                                   info.get('province') or '', info.get('city') or ''))
                    logger.info('【%s】   爬取结果：%d 条岗位，新增 %d 条（来源：%s）'
                                % (cls.web_name, len(jobs), added,
                                   {'image': '图片', 'text': '正文',
                                    'xlsx': 'xlsx附件'}.get(
                                       info.get('source') or '', '未知')))
                    # 图片是逐张识别的，每张的岗位在识别时就打过了，
                    # 这里再列一遍会让同一批岗位在日志里出现两次。
                    if info.get('source') != 'image':
                        for n, job in enumerate(jobs, 1):
                            logger.info('【%s】     %d. %s' % (cls.web_name, n,
                                                              cls.job_brief(job)))
                    # 全部被去重跳过时（added == 0），_append_rows 不会触发 on_data，
                    # 界面上就一直是空的。这里补推一次，让"本次爬到的岗位"能看见。
                    if not added and parsed and on_data:
                        for row in parsed:
                            on_data(row)
                    if parsed and wb is not None:
                        cls._save(wb, data_file)  # BaseSpider 内部按 SAVE_INTERVAL 节流

                # 每爬完一条就写回 status=true。
                # 不标的四种：程序异常、解析异常、被限流、网络失败 ——
                # 都是"这次没拿到"，下次还要重试；标了就永久跳过，等于把文章丢了。
                if not crashed and not err.startswith(('blocked', 'network', 'internal')):
                    cls._mark_done(data, url)
                    logger.info('【%s】   已标记：status=true' % cls.web_name)
                else:
                    logger.info('【%s】   未标记（下次重试）' % cls.web_name)

                elapsed = time.time() - started
                if on_page:
                    on_page(seq, added, len(all_rows), elapsed)

                if seq < len(todo) and not cls._sleep(cls.DEFAULT_DELAY):
                    stopped = True
                    break
        finally:
            # 先落盘、再通知界面（与其它平台一致：界面恢复"开始"时数据已在磁盘）
            try:
                cls._save(wb, data_file, force=True)
            except Exception as e:
                logger.error('【%s】保存失败：%s' % (cls.web_name, e))

        if on_complete:
            on_complete(cls._finish_message(total_added, stopped, failed))

    @classmethod
    def _mark_done(cls, data, url):
        """把 url 这一篇标成 status=true 并立刻写回文件。"""
        cls.save_links(data, url)
