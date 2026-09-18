# coding='utf-8'
import sys

import time

import threading

from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


from newPlayWright import PlayWrightClass, logger
from openpyxl import load_workbook


MAX_WORKERS = 4  # 并发线程数


def login(pw, username, passwd):
    try:
        logger.info(f'【{username}】账号开始登录')
        url = 'https://www.moneyga.me/home/index/requirelogin'
        pw.goto(url)

        username_ele = '//div[@style="display: block;"]//input[@placeholder="Username"]'
        pw.input(username_ele, username)
        pw.input('//div[@style="display: block;"]//input[@placeholder="Password"]', passwd)
        pw.click('//button[text()="Enter Game"]')
        return True
    except Exception as e:
        logger.error(f'【{username}】账号登录失败：{e}')
        return False


def buy(pw, username):
    try:
        logger.info(f'【{username}】账号开始购买体力')
        shops = [22, 152]
        for shop in shops:
            pw.goto(f'https://www.moneyga.me/map/tile/{shop}')
            pw.input('//input[@name="amount_3"]', '2')
            pw.click('//button[text()="Buy Products"]')
            break
        pw.goto('https://www.moneyga.me/dashboard/assetsdebts')
        pw.click('(//div[text()="Use"])[1]')
        pw.click('//div[text()="Confirm"]')
        success_ele = '//div[contains(text(), "You consumed a Food Package")]'
        time.sleep(1)
        status = pw.get_count(success_ele)
        return status
    except Exception as e:
        logger.error(f'【{username}】账号购买体力失败：{e}')
        return False


def work(pw, username):
    try:
        logger.info(f'【{username}】账号开始工作')
        pw.goto('https://www.moneyga.me/dashboard/companies')
        pw.click('(//td[text()="Worker at "]/a)[1]')
        pw.click('//a[text()="Begin Work"]')

        for roll in range(10):
            pw.click('//button[text()="Work Now"]')
            if not pw.get_count('//a[contains(text(),"Click here to work your next job")]'):
                return True
            pw.click('//a[contains(text(),"Click here to work your next job")]')

        logger.error(f'【{username}】账号工作失败')
        return False

    except Exception as e:
        logger.error(f'【{username}】账号工作失败:{e}')
        return False


def run_account(pw, username, passwd):
    """单个账号执行：登录 -> 购买 -> 工作，返回写入备注的结果文本。"""
    logger.info(f'\n开始执行【{username}】账号....')
    money = login(pw, username, passwd)
    if not money:
        return '登录失败'
    bought = buy(pw, username)
    if not bought:
        return '购买失败'
    worked = work(pw, username)
    return '成功' if worked else '失败'


def _worker(chunk, ws, wb, file, remark_col, lock):
    """一个线程处理一批账号，线程内复用同一个浏览器实例。"""
    pw = PlayWrightClass()
    try:
        for row, username, passwd in chunk:
            s1 = time.time()
            try:
                remark = run_account(pw, username, passwd)
            except Exception as e:
                remark = f'执行异常：{e}'

            # 多线程写 xlsx：加锁，避免并发写坏工作簿
            with lock:
                ws.cell(row=row, column=remark_col).value = remark
                wb.save(file)

            logger.info(f'结果：【{username}】{remark}')
            print(f'【{username}】耗时：{time.time() - s1:.1f}s')

            # 清掉该账号 cookie，下一个账号从干净会话开始
            try:
                pw.clear_cookie()
            except Exception as e:
                logger.error(f'【{username}】清理cookie失败：{e}')
    finally:
        try:
            pw.close()
        except Exception as e:
            logger.error(f'关闭浏览器失败：{e}')


def execute(file=None):
    """读取 xlsx，从第3行起按 账号/密码 执行 登录 -> 购买 -> 工作，
    并把结果写入该行“备注”列（E列）。多线程并发执行，线程数 MAX_WORKERS。"""

    account_col = 2  # B：账号
    pwd_col = 4  # D：密码
    remark_col = 5  # E：备注
    start_row = 3  # 数据起始行

    wb = load_workbook(file)
    ws = wb.active

    # 只收集账号非空的有效数据行，忽略尾部（及中间）空行
    data_rows = []
    for row in range(start_row, ws.max_row + 1):
        username = ws.cell(row=row, column=account_col).value
        passwd = ws.cell(row=row, column=pwd_col).value
        if username is None or passwd is None or str(username).strip() == '':
            continue
        data_rows.append((row, str(username).strip(), str(passwd).strip()))

    logger.info(f'开始执行,共{len(data_rows)}行数据,线程数{MAX_WORKERS}')

    if not data_rows:
        return

    # 按轮询把账号分给各线程，负载更均衡
    worker_count = min(MAX_WORKERS, len(data_rows))
    chunks = [data_rows[i::worker_count] for i in range(worker_count)]

    lock = threading.Lock()
    threads = []
    for chunk in chunks:
        t = threading.Thread(
            target=_worker,
            args=(chunk, ws, wb, file, remark_col, lock),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()


if __name__ == '__main__':
    import os
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    file = os.path.join(base, '数据.xlsx')
    execute(file)
