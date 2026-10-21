# coding='utf-8'
"""RavenPack 新闻详情接口封装（POST /api/thread/metadata）。

只有两个方法：
    calc_stt(topic, group, event_type, sub_type=None)  -> 5 位 stt
    fetch_metadata(story_id, eid=None, stt=None)       -> 接口原始 JSON

用法：
    from ravenpack import calc_stt, fetch_metadata
    stt = calc_stt('society', 'legal', 'patent-infringement')
    data = fetch_metadata('852B9A9B3B12F1C49053391D7B7EA32D', 'CE8251', stt)
"""
import hashlib
import html
import math
import os
import sys
import time

import requests
import xlsxwriter
from openpyxl import load_workbook

API = 'https://app.ravenpack.com/api/thread/metadata'

COOKIE = (
    'cookie_consent=1; vdp_known="Haoyan.Chen@anu.edu.au"; '
    'vizsid=.eJwlj0GKwzAMRe_idQmWZVtRV3OTIFkyKe2kkDSLYZi7j0sXf_cevP8blr77sYbraz_9EpabhWvQDuYtQ'
    '_TUmSi3qlDcFQ3mUrFa65UQk2Qh0TZHisQmtYCWQgAJazdUSSJWUuoOrKhNc23UwC1iRiJNscSoWIuhk8wFxYwhSQ'
    '-X0I69L6_n3bfR45WAkSM5zZzxParIAp1amnl0mgozDs-_5fYYyirPH9mmtvr2Jds5uZ2TnAM4D98_Lz_Imwh__z0'
    'tTXg.athaRg.Whp_QH_URBRIOVzVwZ9nJDHzzlM'
)

HEADERS = {
    'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'),
    'accept': 'application/json, text/plain, */*',
    'content-type': 'application/json',
    'origin': 'https://app.ravenpack.com',
    'referer': 'https://app.ravenpack.com/datasets/',
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


def calc_stt(topic, group, event_type, sub_type=None):
    """stt = md5("topic,group,type[,sub_type]")[:5]，空值跳过。"""
    parts = [x for x in (topic, group, event_type, sub_type) if x]
    return hashlib.md5(','.join(parts).encode('utf-8')).hexdigest()[:5]



def fetch_metadata(story_id, eid=None, stt=None, timeout=60):
    """请求 /api/thread/metadata，返回接口原始 JSON（无此新闻时返回 {}）。

    story_id  新闻 ID（story_id 与 thread_id 一致，同一值即可）
    eid       实体 ID，拼进 query（entity:xxx）
    stt       事件类型标识，拼进 query（stt:xxx）；不传也能取到数据

    注：前端还会带 searchClickOrder（点击位次埋点），实测仅被接口回显，
    不影响返回内容，故不发送。
    """
    try:
        sid = str(story_id or '').strip().lstrip('\ufeff')
        if not sid:
            raise ValueError('story_id 不能为空')

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

        resp = _get_session().post(API, json=payload, timeout=timeout)
        if resp.status_code in (401, 403):
            raise PermissionError(f'Cookie 失效（HTTP {resp.status_code}），请更新 vizsid')
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except:
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


def extract_text(data:dict):
    """返回全文：标题 + 各段落，段间空一行；无数据返回空串。"""
    messages = data.get('metadata').get('messages')
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

def single(story_id='AA7B057181AA84948CC5A937D0B4184C', eid='7B895D', stt='ff4db'):
    data = fetch_metadata(story_id, eid, stt)
    if not data:
        return '异常'
    url = data.get('metadata').get('messages')[0].get('url')
    if url:
        return url
    content = extract_text(data)
    return content


# ==================== 批量：遍历 xlsx 回写 ====================
# 表格需含 RP_STORY_ID / RP_ENTITY_ID / STT 三列，
# 运行后自动追加 URL / TEXT_LEN / CONTENT / STATUS 四列：
#   STATUS = done  已执行，后续运行跳过
#   STATUS = error single() 返回「异常」，默认也跳过，--retry 可重试
KEY_COLUMNS = ('RP_STORY_ID', 'RP_ENTITY_ID', 'STT')
NEW_COLUMNS = ('URL', 'TEXT_LEN', 'CONTENT', 'CONTENT')
STATUS_DONE = 'done'
STATUS_ERROR = 'error'
SKIP_STATUS = (STATUS_DONE, STATUS_ERROR)

SLEEP = 0.05               # 每条之间的间隔（秒）
EXCEL_CELL_MAX = 32767





def run_xlsx(path, limit=None, retry=False, sleep=SLEEP):
    """遍历表格调用 single()，结果写回原文件（流式读写，内存恒定）。

    path    xlsx 路径
    limit   本次最多处理多少条（分批执行用）；None 表示处理到文件末尾
    retry   是否重试上次 STATUS=error 的行

    写入规则：
        single() 返回「异常」 -> URL 列写「异常」，STATUS=error
        返回以 http 开头    -> URL 列写入链接，STATUS=done
        其他               -> CONTENT 列写正文、TEXT_LEN 写字符数，STATUS=done

    退出后自动保存；中途 Ctrl+C 会丢弃本批未完成部分（原文件不受影响）。
    """
    skip = (STATUS_DONE,) if retry else SKIP_STATUS

    src = load_workbook(path, read_only=True)
    src_ws = src.active
    rows_iter = src_ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None:
        src.close()
        raise ValueError('表格为空')

    names = [str(x).strip() if x is not None else '' for x in header]
    missing = [name for name in KEY_COLUMNS if name not in names]
    if missing:
        src.close()
        raise ValueError(f'缺少列：{", ".join(missing)}')
    for name in NEW_COLUMNS:
        if name not in names:
            names.append(name)

    col = {name: i for i, name in enumerate(names)}
    src_width = len(header)
    width = len(names)
    i_url, i_len, i_text, i_status = (col[n] for n in ('URL', 'TEXT_LEN', 'CONTENT', 'STATUS'))

    print(f'文件  : {path}')
    print(f'列数  : {src_width} -> {width}')
    print(f'本批  : {("最多 %d 条" % limit) if limit else "全部待处理行"}'
          f'{("，重试 error 行" if retry else "")}')

    tmp = path + '.tmp.xlsx'
    dst_wb = xlsxwriter.Workbook(tmp, {'constant_memory': True})
    dst_ws = dst_wb.add_worksheet(src_ws.title or 'Sheet1')

    dst_ws.freeze_panes(1, 0)

    processed = ok = error = skipped = 0
    started = time.time()

    def flush(row_index, row):
        for c in range(width):
            value = _clean(row[c])
            if value is None or value == '':
                continue
            dst_ws.write(row_index, c, value)

    try:
        for row_index, row in enumerate(rows_iter, 1):
            row = list(row) + [None] * (width - len(row))

            if row[i_status] in skip:
                skipped += 1
                flush(row_index, row)
                continue

            if limit is not None and processed >= limit:
                flush(row_index, row)
                continue

            sid, eid, stt = (row[col[n]] for n in KEY_COLUMNS)
            result = single(sid, eid, stt)
            processed += 1

            if result == '异常':
                row[i_status] = STATUS_ERROR
                row[i_url] = '异常'
                row[i_len] = None
                row[i_text] = None
                error += 1
            elif str(result).startswith('http'):
                row[i_status] = STATUS_DONE
                row[i_url] = result
                row[i_len] = None
                row[i_text] = None
                ok += 1
            else:
                row[i_status] = STATUS_DONE
                row[i_url] = None
                row[i_text] = result
                row[i_len] = len(result or '')
                ok += 1

            flush(row_index, row)

            if processed % 2000 == 0:
                rate = processed / max(time.time() - started, 1e-6)
                print(f'  已处理 {processed}（成功 {ok} / 异常 {error}）'
                      f'  {rate:.2f} 条/s', flush=True)

            if sleep:
                time.sleep(sleep)
    except KeyboardInterrupt:
        print('\n[中断] 正在保存已处理结果…')
    finally:
        dst_wb.close()
        src.close()
        os.replace(tmp, path)

    elapsed = time.time() - started
    print(f'\n本次处理 {processed} 条（成功 {ok}，异常 {error}），跳过 {skipped} 条，'
          f'耗时 {elapsed:.1f}s')
    return processed


def main(argv):
    args = argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        print('批量用法：')
        print('  python ravenpack.py 测试.xlsx            # 处理全部待执行行')
        print('  python ravenpack.py 测试.xlsx -n 500     # 分批：本次最多 500 条')
        print('  python ravenpack.py 测试.xlsx --retry    # 重试 STATUS=error 的行')
        return 0

    path = args[0]
    limit = None
    retry = '--retry' in args
    if '-n' in args:
        limit = int(args[args.index('-n') + 1])

    if not os.path.exists(path):
        print(f'文件不存在：{path}')
        return 1
    run_xlsx(path, limit=limit, retry=retry)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))



