# coding='utf-8'
"""RavenPack 新闻详情接口封装 + 批量回写。

接口：
    calc_stt(topic, group, event_type, sub_type=None)  -> 5 位 stt
    fetch_metadata(story_id, eid=None, stt=None)       -> 接口原始 JSON
    extract_text(data)                                 -> 全文（标题 + 段落）
    single(story_id, eid, stt)                         -> 链接 / '异常' / 全文

批量：
    修改下方「运行配置」后直接执行 python ravenpack.py
    表格需含 RP_STORY_ID / RP_ENTITY_ID / STT，
    运行后补齐 URL / TEXT_LEN / CONTENT / STATUS 四列：
        STATUS=done   已执行（下次自动跳过）
        STATUS=error  调用异常（下次同样跳过，RETRY=True 时重跑）
"""
import hashlib
import html
import logging
import math
import os
import random
import sys
import time
from logging.handlers import RotatingFileHandler

import requests
import xlsxwriter
from openpyxl import load_workbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'ravenpack.log')


def _setup_logger():
    """异常日志：写入 ravenpack.log，单文件 10MB，保留 5 份。"""
    log = logging.getLogger('ravenpack')
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024,
                                  backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
    log.addHandler(handler)
    return log


logger = _setup_logger()

# ==================== 运行配置 ====================
# 要处理的表格；命令行传路径时以命令行为准（python ravenpack.py 测试_01.xlsx）
XLSX_FILE = os.path.join(BASE_DIR, '测试_parts', '测试_01.xlsx')
LIMIT = 100000        # 本次最多处理多少条；None 表示处理完所有待执行行
RETRY = False         # True 时重跑上次 STATUS=error 的行

SLEEP_MIN = 1.0       # 每条之间的最小间隔（秒）
SLEEP_MAX = 3.0       # 最大间隔；实际值在区间内随机，避免固定节奏被识别
SAVE_EVERY = 20       # 每处理多少条打印一次进度
PRINT_SECONDS = 15    # 或者每隔多少秒打印一次（先到者生效，避免长间隔下看不到进度）

# 熔断：连续失败达到阈值就停止请求（多半已被限流/封 IP），
# 剩余行原样保留，换个时间或用代理再跑即可续上。
MAX_FAILS = 5         # 连续失败多少次停止
COOLDOWN = 300        # 触发熔断后不再重试，直接退出（秒），仅用于日志说明

# 代理池（可选）：如 ['http://user:pass@1.2.3.4:8080', 'socks5://...']
# 留空则直连；失败时会自动切换到下一个代理。
PROXIES = []
# =================================================

API = 'https://app.ravenpack.com/api/thread/metadata'

COOKIE = (
    'cookie_consent=1; vdp_known="Haoyan.Chen@anu.edu.au"; vizsid=.eJwlz0tuwzAMBNC7aB0YpH6UsupNDJIi4aCtAzjxIih696rI_g1m5iesfthjC9fncdolrLcRroFaBgKRiiMRuraWJWuj0mMXdkQQr5gTMVDHCiw4uIAmaBSlFshcmMRyrnVo7z21Zuwk1DRJbUPS6Chdu2vKYnEAah-eOQJ6kXAJ-jh8fd4_bZ97oKbJOBoXjWkgOLeq0fNAj4VolqllSTNn33z7mpGN7y_eF91s_-D9XGycC58TnA873i_f5F-E3z_eH033.athJcw.EQCTNOYWvAvbyvHsfqP-JgAuK34; _ga=GA1.2.1672970193.1792559476; _gid=GA1.2.647707326.1792559476; _twpid=tw.1792559476257.8916625631284528; _hjSessionUser_444256=eyJpZCI6IjE0MWQ5MjM1LWY3OGMtNTRhYi04NWM5LTc5OGJkZmEwOWIxNCIsImNyZWF0ZWQiOjE3OTI1NTk0ODkxNzUsImV4aXN0aW5nIjp0cnVlfQ==; _gat_UA-94068430-1=1; _hjSession_444256=eyJpZCI6IjE1NTgwN2M4LTVjYTMtNDg1Yy1hOGRhLWFlNGQ3NWI3MGUyMyIsImMiOjE3OTI2Njk5OTQzMTEsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MX0=; _twsid=1792669993940-500541082.7.1792670008206'
)

HEADERS = {
    'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'),
    'accept': 'application/json, text/plain, */*',
    'content-type': 'application/json',
    'origin': 'https://app.ravenpack.com',
    'host': 'app.ravenpack.com',
    'referer': 'https://app.ravenpack.com/dataset/A322EC0AE7D40734B6E586CABA440F41/?start_date=2000-01-01&end_date=2026-01-01',
}

_session = None


def _get_session():
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        for part in COOKIE.split('; '):
            name, value = part.split('=', 1)
            s.cookies.set(name, value, domain='app.ravenpack.com', path='/')
        _session = s
    return _session


# ==================== 接口 ====================

def calc_stt(topic, group, event_type, sub_type=None):
    """stt = md5("topic,group,type[,sub_type]")[:5]，空值跳过。"""
    parts = [x for x in (topic, group, event_type, sub_type) if x]
    return hashlib.md5(','.join(parts).encode('utf-8')).hexdigest()[:5]


# 最近一次请求的结果类型，供上层熔断判断：
#   ok / empty(404) / auth(401,403) / rate(429) / server(5xx) / net(超时/连接)
LAST_ERROR = 'ok'
_proxy_index = 0


def _current_proxy():
    """返回当前代理配置；代理池为空时返回 None（直连）。"""
    if not PROXIES:
        return None
    proxy = PROXIES[_proxy_index % len(PROXIES)]
    return {'http': proxy, 'https': proxy}


def _rotate_proxy():
    """切换到下一个代理，并丢弃旧连接（换 IP 后 Session 要重建）。"""
    global _proxy_index, _session
    _proxy_index += 1
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None
    if PROXIES:
        logger.warning('切换代理 -> %s', PROXIES[_proxy_index % len(PROXIES)])


def fetch_metadata(story_id, eid=None, stt=None, timeout=60):
    """请求 /api/thread/metadata，返回原始 JSON；任何异常或无此新闻时返回 {}。

    失败原因会写入 ravenpack.log，并把类型记到模块变量 LAST_ERROR。
    """
    global LAST_ERROR

    sid = str(story_id or '').strip().lstrip('\ufeff')
    if not sid:
        logger.warning('story_id 为空，跳过（eid=%s stt=%s）', eid, stt)
        LAST_ERROR = 'empty'
        return {}

    try:
        query = ' '.join(x for x in (
            f'entity:{eid}' if eid else '',
            f'stt:{stt}' if stt else '',
        ) if x)

        payload = {
            'thread_id': sid,
            'page': None,
            'story_ts': None,
            'story_id': sid,
            'source_key': None,
            'subThread': False,
            'grouped': False,
            'query': query,
            'original_language': False,
            'source_type': 'RAVENPACK',
            'multiple_ids': None,
            'searchUUID': None,
            'product': 'rpa',
        }

        resp = _get_session().post(API, json=payload, timeout=timeout,
                                   proxies=_current_proxy())

        if resp.status_code == 429:
            LAST_ERROR = 'rate'
            retry_after = resp.headers.get('Retry-After', '')
            logger.error('触发限流（HTTP 429）story_id=%s eid=%s stt=%s Retry-After=%s',
                         sid, eid, stt, retry_after or '未提供')
            return {}
        if resp.status_code in (401, 403):
            LAST_ERROR = 'auth'
            logger.error('未授权（HTTP %s）：Cookie 失效或已被风控 story_id=%s eid=%s stt=%s',
                         resp.status_code, sid, eid, stt)
            return {}
        if resp.status_code == 404:
            LAST_ERROR = 'empty'
            logger.warning('新闻不存在（HTTP 404）story_id=%s eid=%s stt=%s',
                           sid, eid, stt)
            return {}
        if resp.status_code >= 500:
            LAST_ERROR = 'server'
            logger.error('服务端错误（HTTP %s）story_id=%s eid=%s stt=%s',
                         resp.status_code, sid, eid, stt)
            return {}
        if not resp.ok:
            LAST_ERROR = 'server'
            logger.error('请求失败（HTTP %s）story_id=%s eid=%s stt=%s body=%s',
                         resp.status_code, sid, eid, stt, resp.text[:200])
            return {}

        try:
            data = resp.json()
        except ValueError:
            # 返回 HTML 通常是 WAF 拦截页
            LAST_ERROR = 'rate'
            logger.error('返回非 JSON（疑似被拦截）story_id=%s eid=%s stt=%s body=%s',
                         sid, eid, stt, resp.text[:200])
            return {}

        LAST_ERROR = 'ok'
        return data
    except requests.Timeout:
        LAST_ERROR = 'net'
        logger.error('请求超时 story_id=%s eid=%s stt=%s timeout=%ss',
                     sid, eid, stt, timeout)
        return {}
    except requests.RequestException as exc:
        LAST_ERROR = 'net'
        logger.error('网络异常 story_id=%s eid=%s stt=%s %s: %s',
                     sid, eid, stt, type(exc).__name__, exc)
        return {}
    except (KeyError, IndexError, TypeError) as exc:
        LAST_ERROR = 'server'
        logger.error('数据结构异常 story_id=%s eid=%s stt=%s %s: %s',
                     sid, eid, stt, type(exc).__name__, exc)
        return {}


def _flatten(node):
    """把 content 里的嵌套结构拼成纯文本。"""
    if node is None:
        return ''
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        return ''.join(_flatten(x) for x in node)
    if isinstance(node, dict):
        return _flatten(node.get('content'))
    return ''


def extract_text(data):
    """返回全文：标题 + 各段落，段间换行；无数据返回空串。"""
    messages = ((data or {}).get('metadata') or {}).get('messages') or []
    if not messages:
        return ''

    msg = messages[0]
    parts = []

    title = html.unescape(_flatten(msg.get('annotation_hd') or msg.get('hd'))).strip()
    if title:
        parts.append(title)

    for block in msg.get('annotation_body') or []:
        text = html.unescape(_flatten(block.get('content'))).strip()
        if text:
            parts.append(text)

    return '\n'.join(parts)


def single(story_id, eid=None, stt=None):
    """取一条新闻：有 url 返回 url；异常返回 '异常'；否则返回全文。"""
    data = fetch_metadata(story_id, eid, stt)
    messages = ((data or {}).get('metadata') or {}).get('messages') or []
    if not messages:
        logger.warning('无消息内容 story_id=%s eid=%s stt=%s', story_id, eid, stt)
        return '异常'

    url = messages[0].get('url')
    if url:
        return url

    text = extract_text(data)
    if not text:
        logger.warning('正文为空 story_id=%s eid=%s stt=%s', story_id, eid, stt)
        return '异常'
    return text


# ==================== 批量回写 ====================

KEY_COLUMNS = ('RP_STORY_ID', 'RP_ENTITY_ID', 'STT')
RESULT_COLUMNS = ('URL', 'TEXT_LEN', 'CONTENT', 'STATUS')
STATUS_DONE = 'done'
STATUS_ERROR = 'error'
SKIP_STATUS = (STATUS_DONE, STATUS_ERROR)

EXCEL_CELL_MAX = 32767
ILLEGAL = {c: None for c in range(0x20) if chr(c) not in '\t\n\r'}
HEADER_FMT = {'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
              'align': 'center'}


def _clean(value):
    """去非法控制字符、截断超长文本；数字保持数字类型。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    text = str(value)
    if len(text) > EXCEL_CELL_MAX:
        text = text[:EXCEL_CELL_MAX]
    if ILLEGAL.keys() & set(text):
        text = text.translate(ILLEGAL)
    return text


def _normalize_header(header):
    """去重表头（重复列只保留第一列），并补齐结果列。

    返回 (输出列名列表, 列名 -> 源列下标)；新列的源下标为 None。
    """
    names = []
    src = {}
    for i, raw in enumerate(header):
        name = str(raw).strip() if raw is not None else ''
        if not name:
            name = f'COL{i + 1}'
        if name in src:          # 重复列合并到首次出现的位置
            continue
        src[name] = i
        names.append(name)

    for name in RESULT_COLUMNS:
        if name not in src:
            src[name] = None
            names.append(name)
    return names, src


def _fmt_duration(seconds):
    """秒 -> 1h02m / 12m30s / 45s 这种易读格式。"""
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h{m:02d}m'
    if m:
        return f'{m}m{s:02d}s'
    return f'{s}s'


def run_xlsx(path, limit=None, retry=False, save_every=SAVE_EVERY):
    """遍历表格调用 single() 并回写原文件（流式读写，内存恒定）。

    写入规则：
        single() 返回 '异常'      -> URL 列写 '异常'，STATUS=error
        返回 http 链接            -> URL 列写链接，STATUS=done
        返回正文                  -> CONTENT 列写正文、TEXT_LEN 写字符数，STATUS=done

    已 STATUS=done / error 的行会在下次运行时自动跳过。
    Ctrl+C 中断时会把已处理部分保存下来。
    """
    skip = (STATUS_DONE,) if retry else SKIP_STATUS

    src_wb = load_workbook(path, read_only=True)
    src_ws = src_wb.active
    rows_iter = src_ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None:
        src_wb.close()
        raise ValueError('表格为空')

    total_rows = max((src_ws.max_row or 1) - 1, 0)

    raw_names = [str(x).strip() if x is not None else '' for x in header]
    missing = [name for name in KEY_COLUMNS if name not in raw_names]
    if missing:
        src_wb.close()
        raise ValueError(f'缺少列：{", ".join(missing)}')

    names, src = _normalize_header(header)
    width = len(names)
    pos = {name: i for i, name in enumerate(names)}
    i_url: int = pos['URL']
    i_len: int = pos['TEXT_LEN']
    i_text: int = pos['CONTENT']
    i_status: int = pos['STATUS']
    i_sid: int = pos['RP_STORY_ID']
    i_eid: int = pos['RP_ENTITY_ID']
    i_stt: int = pos['STT']

    print(f'文件  : {path}')
    print(f'列    : {len(header)} -> {width}（{names}）')
    print(f'数据  : 共 {total_rows} 行')
    print(f'本批  : {"最多 %d 条" % limit if limit else "全部待执行行"}'
          f'{"，重试 error 行" if retry else ""}')
    print(f'节奏  : 每条间隔 {SLEEP_MIN}~{SLEEP_MAX}s，'
          f'每 {save_every} 条或 {PRINT_SECONDS}s 打印进度')
    print(f'日志  : {LOG_FILE}', flush=True)
    logger.info('开始处理 file=%s total=%s limit=%s retry=%s',
                path, total_rows, limit, retry)

    tmp = path + '.tmp.xlsx'
    dst_wb = xlsxwriter.Workbook(tmp, {'constant_memory': True})
    dst_ws = dst_wb.add_worksheet(src_ws.title or 'Sheet1')
    head_fmt = dst_wb.add_format(HEADER_FMT)
    for c, name in enumerate(names):
        dst_ws.write(0, c, name, head_fmt)
    dst_ws.freeze_panes(1, 0)
    dst_ws.set_column(i_text, i_text, 80)

    processed = ok = error = skipped = 0
    interrupted = False
    written = 0
    fails = 0
    started = time.time()
    last_print = started

    def _report(force=False):
        """打印进度：按条数或按时间触发；含百分比与预计剩余时间。"""
        nonlocal last_print
        now = time.time()
        if not force:
            if processed % save_every != 0 and now - last_print < PRINT_SECONDS:
                return
        elapsed = now - started
        rate = processed / elapsed if elapsed > 0 else 0
        # 剩余 = 总行数 - 已处理 - 已跳过（跳过的是历史已完成行）
        remaining = max(total_rows - processed - skipped, 0)
        # 本批上限也会影响剩余量
        if limit is not None:
            remaining = min(remaining, max(limit - processed, 0))
        pct = (processed + skipped) / total_rows * 100 if total_rows else 0
        eta = _fmt_duration(remaining / rate) if rate > 0 else '未知'
        print(f'  [{processed + skipped:>6}/{total_rows}  {pct:5.1f}%] '
              f'成功 {ok}  异常 {error}  跳过 {skipped}  '
              f'| {rate:.2f} 条/s | 已用 {_fmt_duration(elapsed)}  '
              f'剩余约 {eta}', flush=True)
        last_print = now

    try:
        for row_no, row in enumerate(rows_iter, 1):
            # 按输出列从源行取值（新列为 None）
            out: list = [None] * width
            for c, name in enumerate(names):
                s = src[name]
                if s is not None and s < len(row):
                    out[c] = row[s]

            if interrupted:
                pass          # 已中断：剩余行只原样写出，不再请求
            elif out[i_status] in skip:
                skipped += 1
            elif limit is not None and processed >= limit:
                pass          # 超过本批上限：原样保留，留给下次
            else:
                sid, eid, stt = out[i_sid], out[i_eid], out[i_stt]
                try:
                    result = single(sid, eid, stt)
                except KeyboardInterrupt:
                    interrupted = True
                    print('\n[中断] 停止请求，正在原样写出剩余行…', flush=True)
                    logger.warning('用户中断 file=%s 已处理=%s', path, processed)
                    result = None
                except Exception:
                    # 单条异常不能中断整批；记录完整堆栈
                    logger.exception('单条执行异常 story_id=%s eid=%s stt=%s',
                                     sid, eid, stt)
                    result = '异常'

                if result is None:
                    pass      # 当前行未被处理，保持原样
                else:
                    processed += 1
                    # 熔断判断：连续失败说明可能已被限流/封 IP
                    if LAST_ERROR in ('rate', 'auth', 'server', 'net'):
                        fails += 1
                        if fails >= MAX_FAILS:
                            interrupted = True
                            print(f'\n[熔断] 连续 {fails} 次请求失败'
                                  f'（{LAST_ERROR}），已停止并保存。', flush=True)
                            print(f'建议：等待 {COOLDOWN} 秒以上、更换 IP/代理，'
                                  f'或降低频率后重新运行。', flush=True)
                            logger.error('触发熔断 连续失败=%s 最后错误=%s '
                                         'file=%s 已处理=%s',
                                         fails, LAST_ERROR, path, processed)
                            if PROXIES:
                                _rotate_proxy()
                    else:
                        fails = 0

                    if result == '异常':
                        out[i_url] = '异常'
                        out[i_len] = None
                        out[i_text] = None
                        out[i_status] = STATUS_ERROR
                        error += 1
                    elif str(result).startswith('http'):
                        out[i_url] = result
                        out[i_len] = None
                        out[i_text] = None
                        out[i_status] = STATUS_DONE
                        ok += 1
                    else:
                        out[i_url] = None
                        out[i_text] = result
                        out[i_len] = len(result or '')
                        out[i_status] = STATUS_DONE
                        ok += 1

                    _report()

                    if not interrupted:
                        try:
                            time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))
                        except KeyboardInterrupt:
                            interrupted = True
                            print('\n[中断] 停止请求，正在原样写出剩余行…',
                                  flush=True)
                            logger.warning('用户中断 file=%s 已处理=%s',
                                           path, processed)

            for c in range(width):
                value = _clean(out[c])
                if value is None or value == '':
                    continue
                dst_ws.write(row_no, c, value)
            written = row_no
    except Exception:
        logger.exception('批量处理异常终止 file=%s 已处理=%s', path, processed)
        raise
    finally:
        dst_wb.close()
        src_wb.close()
        os.replace(tmp, path)

    elapsed = time.time() - started
    _report(force=True)
    print(f'\n本次处理 {processed} 条（成功 {ok}，异常 {error}），跳过 {skipped} 条，'
          f'耗时 {_fmt_duration(elapsed)}', flush=True)
    print(f'输出行数：{written}（源表数据行全部保留，未处理行原样写出）', flush=True)
    if error:
        print(f'异常明细已记录到日志：{LOG_FILE}', flush=True)
    logger.info('处理结束 file=%s 处理=%s 成功=%s 异常=%s 跳过=%s 耗时=%.1fs',
                path, processed, ok, error, skipped, elapsed)


if __name__ == '__main__':
    # 可直接指定文件：python ravenpack.py 测试_parts\测试_02.xlsx
    target = sys.argv[1] if len(sys.argv) > 1 else XLSX_FILE
    if not os.path.exists(target):
        print(f'文件不存在：{target}')
        sys.exit(1)
    run_xlsx(target, limit=LIMIT, retry=RETRY)
