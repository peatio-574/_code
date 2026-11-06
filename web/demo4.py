# coding='utf-8'
"""
读取 用户数据1.xlsx 中的 user_id，调用微博接口获取：
    是否认证 / 认证说明文字 / 认证类型 / 粉丝数
并写回 用户数据1.xlsx。

说明：
    1. 只处理 DEBUG_LIMIT 条（默认 20000，即全量），不会强制爬完；
    2. 支持断点续跑：C 列已有结果（且不是“获取失败”）的行会跳过，
       cookie 失效后换上新 cookie 直接重跑即可接着爬；
    3. 认证说明文字统一取 /ajax/profile/detail 的 desc_text：
        - uid=1322847342 实际是“本地资讯博主（泉州） 微博社区志愿者”，
          而 verified_reason 只有“微博原创视频博主”；
        - uid=5333693607 实际没有认证说明，desc_text 为空，
          而 verified_reason 只有“超话粉丝大咖（…）”这类成就标签。
       所以不能用 verified_reason，也不能用 verified_detail 拼。
    4. 认证类型按蓝V/黄V/金V/红V四类划分，规则见 classify_verified；
    5. cookie 会过期，失效后请重新从浏览器复制 COOKIE。
"""
import sys
import time
import random
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import requests
from openpyxl import load_workbook

BASE_DIR = Path(__file__).parent
EXCEL_PATH = BASE_DIR / '用户数据1.xlsx'
SHEET_NAME = None           # None 表示使用第一个工作表
UID_COL = 1                 # A 列 user_id
OUT_START_COL = 3           # C 列开始写入结果
DEBUG_LIMIT = 20000         # 单次最多处理多少条（20000≈全量）
REQUEST_DELAY = (0.1, 0.5)  # 每次请求间隔，避免触发风控
SAVE_EVERY = 100            # 每处理多少条保存一次

COOKIE = 'SCF=An5CiYgAPdwNWTeOtLSAQNnsLUhxApM7fJJdD316Sr_CKkFRwsvliEcY1_pHmHD_O4WAfetab6Cw9hcnsIm5qIA.; SINAGLOBAL=295319485820.42224.1784718627874; XSRF-TOKEN=uDlpFyFIy4fx5znIKe0lwSlk; _s_tentry=weibo.com; Apache=3909404483906.6064.1793855142685; ULV=1793855142689:2:1:1:3909404483906.6064.1793855142685:1784718627876; SUB=_2A25H6BxbDeRhGe9O61IQ8y_KyzSIHXVkhBGTrDV8PUNbmtAbLVDfkW9NdwcIRC8hxD0xlNQqjypoCwTqhcnXAnx4; SUBP=0033WrSXqPxfM725Ws9jqgMF55529P9D9WWC6D6WC4klDRn.yGyXGOy85NHD95Q4eh57eKepSo5RWs4DqcjMi--NiK.Xi-2Ri--ciKnRi-zN1K57eh20eKq715tt; ALF=02_1796471051; WBPSESS=ydPUIuE03TLHiYiedj9EIBI2VsRPX1TwnwcFAp2dL3ZmQ3fM1VV-QlqGV123Q_Pt98XrMBHW8XOMEKiu910XPBBww2lYughqYssGbmNIHRYqD2vvsntgX9jZ57cjqpzQUaT-gCTS1gOkXopqPRv1wA=='

HEADERS = {
    'x-requested-with': 'XMLHttpRequest',
    'x-xsrf-token': 'uDlpFyFIy4fx5znIKe0lwSlk',
    'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36'),
    'cookie': COOKIE,
}

RESULT_HEADERS = ['是否认证', '认证说明文字', '认证类型', '粉丝数']


class CookieExpiredError(RuntimeError):
    """cookie 失效 / 被风控时抛出，直接中止，避免把整表写成失败"""


def fetch_json(session, url, params, headers):
    """请求接口并解析 JSON；拿到登录跳转页时抛出 CookieExpiredError"""
    resp = session.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text.startswith('{'):
        if 'retcode=6102' in text or 'login' in text.lower() or '通行证' in text:
            raise CookieExpiredError(
                'Cookie 已失效（接口返回登录页 / retcode=6102），'
                '请重新从浏览器复制 COOKIE 后再运行')
        raise RuntimeError(f'接口返回非 JSON: {text[:120]}')
    return resp.json()


def classify_verified(user):
    """
    认证类型判断：
        蓝V：verified_type 为 1~7（政府/企业/媒体/校园/网站/应用/团体机构）
        金V：个人认证且 verified_type_ext == 1（橙V中的大V，即金V）
        黄V：个人认证（verified_type == 0）但不是金V
        红V：达人认证（verified_type 为 200/220，垂直领域自媒体）
        未认证：verified 为 false
    """
    if not user.get('verified'):
        if user.get('verified_type') in (200, 220):
            return '红V'
        return '未认证'

    vtype = user.get('verified_type')
    ext = user.get('verified_type_ext')

    if vtype == 0:
        return '金V' if ext == 1 else '黄V'
    if vtype in (1, 2, 3, 4, 5, 6, 7):
        return '蓝V'
    if vtype in (200, 220):
        return '红V'
    return '已认证'


def format_count(count):
    """粉丝数兜底格式化（接口没有 followers_count_str 时使用）"""
    if count is None:
        return ''
    if count >= 100_000_000:
        return f'{count / 100_000_000:.1f}亿'
    if count >= 10_000:
        return f'{count / 10_000:.1f}万'
    return str(count)


def get_desc_text(uid, session, headers):
    """认证说明文字统一取 profile/detail 的 desc_text"""
    data = fetch_json(session, 'https://weibo.com/ajax/profile/detail',
                      {'uid': uid}, headers)
    return ((data.get('data') or {}).get('desc_text') or '').strip()


def get_user_info(uid, session):
    """profile/info 拿认证类型、粉丝数；profile/detail 拿认证说明文字"""
    uid = str(uid).strip()
    if not uid:
        raise ValueError('uid 为空')

    headers = dict(HEADERS)
    headers['referer'] = f'https://weibo.com/u/{uid}'
    data = fetch_json(session, 'https://weibo.com/ajax/profile/info',
                      {'uid': uid}, headers)

    user = (data.get('data') or {}).get('user')
    if not data.get('ok') or not user:
        msg = data.get('msg') or data.get('message') or str(data)[:200]
        raise RuntimeError(f'接口返回异常: {msg}')

    time.sleep(random.uniform(0.3, 0.8))
    reason = get_desc_text(uid, session, headers)

    return {
        'screen_name': user.get('screen_name', ''),
        'verified': '已认证' if user.get('verified') else '未认证',
        'reason': reason,
        'level': classify_verified(user),
        'followers': user.get('followers_count_str')
                     or format_count(user.get('followers_count')),
    }


def main():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f'找不到文件: {EXCEL_PATH}')

    wb = load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME] if SHEET_NAME else wb.worksheets[0]

    # 写表头（C1:F1）
    for offset, title in enumerate(RESULT_HEADERS):
        ws.cell(row=1, column=OUT_START_COL + offset, value=title)

    # 取出待处理 uid：已爬取（C 列有结果且不是“获取失败”）的行直接跳过
    rows = []
    skipped = 0
    for row_idx in range(2, ws.max_row + 1):
        uid = ws.cell(row=row_idx, column=UID_COL).value
        if uid is None or str(uid).strip() == '':
            continue

        status = ws.cell(row=row_idx, column=OUT_START_COL).value
        if status is not None and str(status).strip() not in ('', '获取失败'):
            skipped += 1
            continue

        rows.append((row_idx, str(uid).strip()))
        if len(rows) >= DEBUG_LIMIT:
            break

    print(f'已爬取跳过 {skipped} 行，本次待处理 {len(rows)} 条'
          f'（单次上限 {DEBUG_LIMIT} 条）')
    if not rows:
        print('没有待处理的数据，已全部完成')
        return

    session = requests.Session()
    success, failed = 0, 0
    cookie_dead = False

    for i, (row_idx, uid) in enumerate(rows, 1):
        try:
            info = get_user_info(uid, session)
            values = [info['verified'], info['reason'],
                      info['level'], info['followers']]
            for offset, value in enumerate(values):
                ws.cell(row=row_idx, column=OUT_START_COL + offset, value=value)
            success += 1
            print(f"[{i:>2}/{len(rows)}] 第{row_idx}行 {uid} {info['screen_name']} | "
                  f"{info['verified']} | {info['level']} | {info['followers']} | "
                  f"{info['reason']}")
        except CookieExpiredError as e:
            cookie_dead = True
            print(f'\n[中止] {e}')
            break
        except Exception as e:
            failed += 1
            # 失败时如果原来已有结果就保留，避免把已抓好的数据覆盖掉
            if not ws.cell(row=row_idx, column=OUT_START_COL).value:
                ws.cell(row=row_idx, column=OUT_START_COL, value='获取失败')
            print(f'[{i:>2}/{len(rows)}] 第{row_idx}行 {uid} 失败: {e}')

        if i % SAVE_EVERY == 0 or i == len(rows):
            wb.save(EXCEL_PATH)
            print(f'    -- 已保存到 {EXCEL_PATH.name}')

        if i < len(rows):
            time.sleep(random.uniform(*REQUEST_DELAY))

    wb.save(EXCEL_PATH)
    print(f'完成：成功 {success} 条，失败 {failed} 条，结果已写入 {EXCEL_PATH.name}')
    if cookie_dead:
        sys.exit(1)


if __name__ == '__main__':
    main()
