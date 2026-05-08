# -*- coding: utf-8 -*-
import sys
import time
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import playwright.async_api as async_api
from Logger import logger
from Config import get_config_value

class PhoneQueryWorker:
    """异步工作器，每个实例拥有独立的 Browser"""

    def __init__(self, playwright, worker_id):
        self.playwright = playwright
        self.browser = None
        self.page = None
        self.worker_id = worker_id

    async def initialize(self):
        """初始化浏览器"""
        logger.info(f"[Worker-{self.worker_id}] 启动浏览器...")

        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-gpu',
            '--no-first-run',
            '--start-maximized',
            '--lang=zh-CN,zh',
        ]

        self.browser = await self.playwright.chromium.launch(
            channel='chrome',
            headless=False,
            args=browser_args,
            ignore_default_args=["--enable-automation"],
        )

        context = await self.browser.new_context(
            viewport=None,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        )

        self.page = await context.new_page()

        logger.info(f"[Worker-{self.worker_id}] 访问网站...")
        await self.page.goto('https://shop.10086.cn/mall_280_280.html', wait_until='domcontentloaded')
        await asyncio.sleep(2)

        logger.info(f"[Worker-{self.worker_id}] ✅ 初始化完成")

    async def query_phone(self, phone):
        """查询单个手机号"""
        try:
            # 输入手机号
            input_location = '(//input[@iprompt="请输入手机号码"])[1]'
            await self.page.click(input_location)
            await self.page.fill(input_location, "")
            await self.page.fill(input_location, str(phone))
            await asyncio.sleep(0.5)
            await self.page.press(input_location, 'Enter')
            await asyncio.sleep(2)  # 等待响应

            # 获取结果
            count = await self.page.locator('//div[text()="请正确输入移动手机号码"]').count()
            return count
        except Exception as e:
            logger.error(f"[Worker-{self.worker_id}] ❌ 查询 {phone} 失败: {e}")
            return '查询失败'

    async def close(self):
        """关闭浏览器"""
        try:
            if self.page:
                await self.page.close()
            if self.browser:
                await self.browser.close()
            logger.info(f"[Worker-{self.worker_id}] 已关闭")
        except Exception as e:
            logger.error(f"[Worker-{self.worker_id}] 关闭失败: {e}")


async def query_single_phone(worker, phone, df, excel_file, row_idx, lock):
    """
    查询单个手机号的异步任务，并将结果写入 Excel
    :param worker: 浏览器工作器
    :param phone: 手机号
    :param df: DataFrame 对象
    :param excel_file: Excel 文件路径
    :param row_idx: 行索引
    :param lock: 异步锁
    """
    result = await worker.query_phone(phone)

    # 更新 DataFrame
    df.iloc[row_idx, 1] = result

    # 写入 Excel（需要重新写入整个文件）
    async with lock:
        df.to_excel(excel_file, index=False)
        logger.info(f"手机号: {phone}, 结果: {result}， ✅ 已写入行 {row_idx + 2}")

    return phone, result


async def batch_query_phones_async(phone_list, excel_file, pool_size=10):
    """
    使用异步方式批量查询手机号
    :param phone_list: 手机号列表
    :param excel_file: Excel 文件路径
    :param pool_size: 并发浏览器数量
    :return: 查询结果字典
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"开始初始化 {pool_size} 个浏览器实例...")
    logger.info(f"{'=' * 60}\n")

    playwright = await async_api.async_playwright().start()
    workers = []

    # 创建多个浏览器
    for i in range(pool_size):
        worker = PhoneQueryWorker(playwright, i + 1)
        await worker.initialize()
        workers.append(worker)

    logger.info(f"\n✅ 浏览器初始化完成！共 {len(workers)} 个浏览器\n")
    logger.info(f"开始批量查询 {len(phone_list)} 个手机号...\n")

    start_time = time.time()
    completed = 0
    total = len(phone_list)

    # 读取 Excel 文件（假设第一列是手机号，第二列是结果）
    df = pd.read_excel(excel_file)

    # 确保有第二列（结果列）
    if len(df.columns) < 2:
        df['结果'] = ''
    elif len(df.columns) == 2:
        pass  # 已有两列

    # 创建异步锁，用于同步写入 Excel
    lock = asyncio.Lock()

    try:
        # 创建任务列表
        tasks = []
        for idx, phone in enumerate(phone_list):
            worker = workers[idx % pool_size]  # 循环分配给不同的 worker
            task = asyncio.create_task(
                query_single_phone(worker, phone, df, excel_file, idx, lock)
            )
            tasks.append(task)

        # 等待所有任务完成
        for idx, task in enumerate(asyncio.as_completed(tasks), 1):
            phone, count = await task
            completed += 1
            progress = (completed / total) * 100
            status = "✅" if count is not None else "❌"
            logger.info(f"[{progress:.1f}%] {status} 手机号: {phone}, 结果: {count}")

        elapsed = time.time() - start_time
        logger.info(f"\n{'=' * 60}")
        logger.info(f"⏱️  查询完成！总耗时: {elapsed:.2f} 秒")
        logger.info(f"{'=' * 60}")

    finally:
        # 关闭所有浏览器
        logger.info(f"\n{'=' * 60}")
        logger.info("正在关闭所有浏览器...")
        logger.info(f"{'=' * 60}\n")

        for worker in workers:
            await worker.close()

        await playwright.stop()
        logger.info("✅ 所有浏览器已关闭")

    # return results
    return True


def batch_query_phones(phone_list, excel_file, pool_size=10):
    """同步包装函数"""
    return asyncio.run(batch_query_phones_async(phone_list, excel_file, pool_size))


if __name__ == '__main__':
    # Excel 文件路径
    excel_file = get_config_value('login', 'file')  # 请修改为实际文件路径
    thread = int(get_config_value('login', 'thread'))

    # 检查文件是否存在
    if not Path(excel_file).exists():
        logger.error(f"Excel 文件不存在：{excel_file}")
        logger.info("请先创建 Excel 文件，第一列为手机号")
        exit()

    # 读取 Excel 文件获取手机号列表
    df = pd.read_excel(excel_file)

    # 获取第一列（手机号列）的所有数据
    phone_numbers = df.iloc[:, 0].tolist()

    logger.info(f"从 Excel 文件读取到 {len(phone_numbers)} 个手机号")
    logger.info(f"手机号列表：{phone_numbers[:5]}...")  # 打印前 5 个

    # 执行批量查询
    results = batch_query_phones(
        phone_list=phone_numbers,
        excel_file=excel_file,
        pool_size=thread # 5个浏览器
    )

    # # 打印结果汇总
    # print("\n" + "=" * 60)
    # print("=== 查询结果汇总 ===")
    # print("=" * 60)
    # for phone, count in results.items():
    #     print(f"{phone}: {count}")
    #
    # logger.info(f"\n结果已保存到：{excel_file}")
