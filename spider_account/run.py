# coding='utf-8'
import sys
import os
from platform import platform
from pygments.lexers.webassembly import keywords

if getattr(sys, 'frozen', False):
    bundleDir = sys._MEIPASS
    baseDir = os.path.dirname(sys.executable)
else:
    bundleDir = os.path.dirname(os.path.abspath(__file__))
    baseDir = bundleDir

sys.path.insert(0, bundleDir)


from newPlayWright import PlayWright, logger, get_config_value
import time
import pandas
from openpyxl.styles import Font, Alignment, PatternFill
import openpyxl
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')
config_file = os.path.join(os.path.dirname(__file__), 'config.ini')
dataDir = os.path.join(os.path.dirname(__file__), '数据')
os.makedirs(dataDir, exist_ok=True)

class XHS(object):

    @classmethod
    def xhsLogin(cls, account_id):
        """登录小红书"""
        logger.info('开始登录小红书....')
        url = 'https://ark.xiaohongshu.com/app-system/home'
        ele = '(//a[text()="学习中心"])[1]'
        key = f'login.xhs_cookie_{account_id}'
        idx = (account_id - 1) % 10 + 1
        sub_account = f'(//span[text()="子账号"])[{idx}]/../div/div[1]'
        loginStatus = PlayWright.login(url, ele, key, extra=sub_account, file=config_file)
        if loginStatus:
            shopName = PlayWright.get_text('//div[@class="avatar-wrapper"]/div')
            logger.info(f'✅️ 【店铺：{shopName}】小红书登录成功....')
            return shopName
        else:
            logger.error(f'❌️ 小红书登录失败')
            return False

    @classmethod
    def fundsSearch(cls, startTime, endTime):
        """访问账号资金明细页面，进行搜索"""
        PlayWright.goto('https://ark.xiaohongshu.com/app-merchant/third-settle/account')
        time.sleep(8)

        # 循环关闭弹窗
        know_ele = '(//span[text()="知道了" or text()="跳过"])[last()]'
        for roll in range(10):
            if PlayWright.get_count(know_ele):
                PlayWright.click(know_ele)
                time.sleep(1)

        PlayWright.slow_input('//input[@placeholder="开始时间"]', startTime)
        PlayWright.slow_input('//input[@placeholder="结束时间"]', endTime)
        PlayWright.click('//span[text()="查询"]')

    @classmethod
    def fundsHtmlSave(cls,fileName):
        """账号资金明细-页面导出"""
        try:
            # 直接导出
            with PlayWright.page.expect_download(timeout=15000) as download_info:
                PlayWright.click('//span[text()="导出"]')
                pass  # 等待下载触发
            download = download_info.value
            # 获取文件名并保存
            download.save_as(fileName)
            return True
        except Exception as e:
            logger.error(f'❌️ {fileName}-页面导出-临时下载异常：{e}')
            return False

    @classmethod
    def ApiSave(cls, fileName):
        """api导出"""
        try:
            PlayWright.click('//span[text()="消息"]')
            PlayWright.click('(//span[text()="店铺"])[last()]')

            errorInfo = f'❌️ {fileName}-api导出失败-未获取到文件链接'

            # 第一行时间是否存在
            firstRowTimeEle = '(//div[@class="list-item-wrapper"])[1]//div[@class="date-wrap unread"]/span'
            if not PlayWright.get_count(firstRowTimeEle):
                logger.info(errorInfo)
                return False

            # 第一行时间是否符合条件
            firstRowTime = PlayWright.get_text(firstRowTimeEle)
            if firstRowTime not in ('1分钟前', '刚刚'):
                logger.info(errorInfo)
                return False

            # 第一行链接元素是否存在
            firstRowLinkEle = '(//div[@class="list-item-wrapper"])[1]//a'
            if not PlayWright.get_count(firstRowLinkEle):
                logger.info(errorInfo)
                return False

            # 第一行链接元素href是否存在
            href = PlayWright.get_attribute(firstRowLinkEle, 'href')
            with open(fileName, mode='wb') as f:
                f.write(PlayWright.get(href).content)

            # 关闭消息弹窗
            PlayWright.click('//div[@class="ark-message-title-wrap"]/span[2]')
            return True
        except Exception as e:
            logger.error(f'❌️ {fileName}-api导出-临时下载异常：{e}')
            return False

    @classmethod
    def fundsDataDeal(cls, shopName, fileName):
        """汇总账号资金详细数据"""
        try:
            # 读取Excel文件
            df = pandas.read_excel(fileName)

            # 将数值列转换为数字类型（处理可能的文本格式数字）
            df['收入（元）'] = pandas.to_numeric(df['收入（元）'], errors='coerce').fillna(0)
            df['支出（元）'] = pandas.to_numeric(df['支出（元）'].replace('-', '0'), errors='coerce').fillna(0)

            # 提取日期
            df['日期'] = pandas.to_datetime(df['创建时间']).dt.date

            # 分离提现和非提现数据
            df_withdraw = df[df['交易类型描述'].str.contains('提现', na=False)]
            df_normal = df[~df['交易类型描述'].str.contains('提现', na=False)]

            logger.info(f'总数据量: {len(df)}, 提现数据: {len(df_withdraw)}, 非提现数据: {len(df_normal)}')

            # 汇总非提现的收入和支出
            df_normal_summary = df_normal.groupby('日期').agg({
                '收入（元）': 'sum',
                '支出（元）': 'sum'
            }).reset_index()
            df_normal_summary.columns = ['日期', '日收入', '日支出']

            # 汇总提现数据（提现金额在支出列）
            df_withdraw_summary = df_withdraw.groupby('日期').agg({
                '支出（元）': 'sum'
            }).reset_index()
            df_withdraw_summary.columns = ['日期', '日提现金额']

            # 合并两个汇总表
            df_summary = pandas.merge(df_normal_summary, df_withdraw_summary, on='日期', how='outer')

            # 填充空值为0
            df_summary = df_summary.fillna(0)

            # 计算日净收入（收入 - 支出 - 提现）
            df_summary['日净收入'] = df_summary['日收入'] - df_summary['日支出']

            # 按日期排序
            df_summary = df_summary.sort_values('日期', ascending=True).reset_index(drop=True)

            # 汇总数据
            total_row = pandas.DataFrame({
                '日期': ['所有汇总'],
                '日收入': [df_summary['日收入'].sum()],
                '日支出': [df_summary['日支出'].sum()],
                '日提现金额': [df_summary['日提现金额'].sum()],
                '日净收入': [df_summary['日净收入'].sum()]
            })
            df_summary = pandas.concat([df_summary, total_row], ignore_index=True)

            # 使用 ExcelWriter 追加到现有文件，保留原有的 Sheet1
            with pandas.ExcelWriter(fileName, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                sheet_name = '汇总数据'
                # 先删除可能已存在的同名 Sheet
                if sheet_name in writer.book.sheetnames:
                    del writer.book[sheet_name]

                # 写入数据
                df_summary.to_excel(writer, sheet_name=sheet_name, index=False)

                # 获取工作表对象并设置样式
                ws = writer.sheets[sheet_name]
                header_font = Font(bold=True, color='FFFFFF', size=11)
                header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
                header_alignment = Alignment(horizontal='center', vertical='center')

                # 遍历第一行所有单元格设置样式
                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment

                # 自动调整列宽
                for column in ws.columns:
                    max_length = 0
                    col_letter = column[0].column_letter
                    for cell in column:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))

                    ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

                # 消除 "Workbook contains no default style" 警告
                workbook = writer.book
                if not workbook.style_names:
                    default_font = Font(name='Calibri', size=11, bold=False, italic=False)
                    default_style = openpyxl.styles.NamedStyle(name='Normal', font=default_font)
                    workbook.add_named_style(default_style)

            logger.info(f'数据汇总完成，共汇总{len(df_summary)}天的数据，已保存到: {fileName}')

            # 打印汇总统计
            logger.info(f'总收入: {df_summary["日收入"].sum()/2:.2f}，总支出: {df_summary["日支出"].sum()/2:.2f} '
                        f'总提现: {df_summary["日提现金额"].sum()/2:.2f}，总净收入: {df_summary["日净收入"].sum()/2:.2f}\n')
            return df_summary

        except Exception as e:
            logger.error(f'{shopName}数据处理失败: {e}\n')
            return None

    @classmethod
    def fundsSingleRun(cls, account_id):
        """账户资金明细-单个店铺运行"""
        title = f'========================开始爬取小红书第{account_id}个店铺账号资金详情======================='
        logger.info(title)

        # 结束时间为昨天，开始时间为结束时间的当月第一天
        endTime = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        startTime = endTime[:-2] + '01'

        shopName = cls.xhsLogin(account_id)
        if not shopName:
            logger.error(f'小红书第{account_id}个店铺登录异常')
            return False

        cls.fundsSearch(startTime, endTime)

        fileName = f'小红书-{shopName}店铺{endTime}账户资金明细.xlsx'
        fileName = os.path.join(dataDir, fileName)

        saveStatus = False
        for roll in range(1, 6):
            logger.info(f'开始第{roll}次尝试导出明细')
            # 页面导出
            saveStatus = cls.fundsHtmlSave(fileName)
            if saveStatus:
                break
            # api导出
            saveStatus = cls.ApiSave(fileName)
            if saveStatus:
                break

        text = f'✅️ {shopName}明细数据下载成功：{fileName}' if saveStatus else f'❌️ {shopName}明细数据下载失败'
        logger.info(text)
        if saveStatus:
            cls.fundsDataDeal(shopName, fileName)
        PlayWright.clear_cookie()
        return True if saveStatus else False

    @classmethod
    def fundsRun(cls, startId, endId):
        """统筹运行账号资金明细"""
        for account_id in range(startId, endId):
            try:
                cls.fundsSingleRun(account_id)
            except Exception as e:
                logger.error(f'第{account_id}个店铺查询【账号资金明细】操作流程失败：{e}')

    @classmethod
    def salesSearch(cls, startTime, endTime):
        """访问销量明细页面，进行搜索"""
        PlayWright.goto('https://ark.xiaohongshu.com/app-order/order/query')
        time.sleep(8)

        # 循环关闭弹窗
        know_ele = '(//span[text()="知道了" or text()="跳过"])[last()]'
        for roll in range(10):
            if PlayWright.get_count(know_ele):
                PlayWright.click(know_ele)
                time.sleep(1)

        PlayWright.slow_input('//div[@class="d-daterangepicker-content"]/div[1]/input', startTime)
        PlayWright.slow_input('//div[@class="d-daterangepicker-content"]/div[3]/input', endTime)
        PlayWright.click('//span[text()="查询"]')

    @classmethod
    def salesHtmlSave(cls, fileName):
        try:
            # 直接导出
            with PlayWright.page.expect_download(timeout=15000) as download_info:
                PlayWright.click('//span[text()="全部导出"]')
                PlayWright.click('//span[text()="确定"]')

                pass  # 等待下载触发
            download = download_info.value
            # 获取文件名并保存
            download.save_as(fileName)
            return True
        except Exception as e:
            logger.error(f'❌️ {fileName}-页面导出-临时下载异常：{e}')
            return False

    @classmethod
    def salesSingleRun(cls, account_id):
        """销量明细-单个店铺运行"""
        title = f'========================开始爬取小红书第{account_id}个店铺销量详情======================='
        logger.info(title)

        # 结束时间为昨天，开始时间为结束时间的当月第一天
        endDate = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        endTime = endDate + ' 23:59:59'
        startTime = endDate[:-2] + '01 00:00:00'

        shopName = cls.xhsLogin(account_id)
        if not shopName:
            logger.error(f'小红书第{account_id}个店铺登录异常')
            return False

        cls.salesSearch(startTime, endTime)

        fileName = f'小红书-{shopName}店铺{endDate}销量明细.xlsx'
        fileName = os.path.join(dataDir, fileName)

        saveStatus = False
        for roll in range(1, 6):
            logger.info(f'开始第{roll}次尝试导出明细')
            # 页面导出
            saveStatus = cls.salesHtmlSave(fileName)
            if saveStatus:
                break
            # api导出
            saveStatus = cls.ApiSave(fileName)
            if saveStatus:
                break

        text = f'✅️ {shopName}明细数据下载成功：{fileName}' if saveStatus else f'❌️ {shopName}明细数据下载失败'
        logger.info(text)
        # if saveStatus:
        #     cls.fundsDataDeal(shopName, fileName)
        PlayWright.clear_cookie()
        return True if saveStatus else False

    @classmethod
    def salesRun(cls, startId, endId):
        """统筹运行销量明细"""
        for account_id in range(startId, endId):
            try:
                cls.salesSingleRun(account_id)
            except Exception as e:
                logger.error(f'第{account_id}个店铺查询【销量明细】操作流程失败：{e}')


if __name__ == '__main__':
    keywordsDict = {
        '1': 'xhs_shop_count',
    }
    while True:
        platform = input('请输入操作平台（1.小红书）：')
        step = input('请输入操作步骤（1.查看账号资金明细，2.查询销量明细）：')
        startId = input('请输入查询店铺序号（0默认查询全部，序号+：可查询多个）：')

        shopCount = get_config_value('login', keywordsDict[platform], file=config_file)

        if startId == '0':
            startId = 1
            endId = int(shopCount) + 1
        elif ':' in startId or '：' in startId:
            startId = startId.replace('：', '').replace(':', '')
            startId = int(startId)
            endId = int(shopCount) + 1
        else:
            startId = int(startId)
            endId = startId + 1
        if step == '1' and platform == '1':
            XHS.fundsRun(startId, endId)
        elif step == '2' and platform == '1':
            XHS.salesRun(startId, endId)




