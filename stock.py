# coding='utf-8'
import sys
import os

if getattr(sys, 'frozen', False):
    bundleDir = sys._MEIPASS
    baseDir = os.path.dirname(sys.executable)
else:
    bundleDir = os.path.dirname(os.path.abspath(__file__))
    baseDir = bundleDir

sys.path.insert(0, bundleDir)

import re
import requests


def getData(stockCode):
    url = f'https://fund.eastmoney.com/{stockCode}.html?spm=xjbsy'
    result = requests.get(url).content.decode('utf-8')
    dataOne = re.findall('<span class="ui-font-large ui-color-red ui-num">(.*?)<', result)[0]
    dataTwo = re.findall('<span class="ui-font-middle ui-color-red ui-num">(.*?)<', result)[0]
    return [dataOne, dataTwo]

def getOld(string):
    oldInfoOne = re.findall('class=\"bold\">(.*?)<',string)
    oldInfoTwo = re.findall('class=\"tar bold\">(.*?)<',string)
    oldInfoTwo = [oldInfoTwo[3].split('/')[0].strip(), oldInfoTwo[5], oldInfoTwo[6].split('/')[0].strip(), oldInfoTwo[8]]
    date = re.findall('>日期：(.*?)<',string)[0]
    return [date, oldInfoOne, oldInfoTwo]


if __name__ == '__main__':
    stockCodes = ['002183', '004863', '018655']

    string = """
    "result": "<table class=\"balancetable\" style=\"width: 100%\"><thead><tr><th class=\"tac\">基金简称</th><th class=\"tal\"><span class=\"order\">每万份收益</span>（7日年化）</th><th class=\"tar\">可用&nbsp;/&nbsp;可取&nbsp;/&nbsp;总份额（份）</th><th class=\"tar\">未付收益（元）</th><th class=\"tac\">累计收益（元）</th><th class=\"tac\">操作</th></tr></thead><tbody data-c=\"3\"><tr class='even'><td class='tal'><a href=\"http://fund.eastmoney.com/002183.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">广发天天红货币B</a><br/><span class=\"gray\">002183</span></td><td class=\"tal\"><span class=\"bold\">0.3147</span>（<span class=\"bold\">1.1560%</span>）<br/><span class=\"gray\">日期：08-20</span></td><td class=\"tar bold\">0.04 / 0.04 / 0.04</td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">0.04</td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=002183\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=002183#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=002183'>一键互转</a></td></tr><tr><td class='tal'><a href=\"http://fund.eastmoney.com/004863.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">泰康现金管家货币C</a><br/><span class=\"gray\">004863</span></td><td class=\"tal\"><span class=\"bold\">0.4018</span>（<span class=\"bold\">1.2110%</span>）<br/><span class=\"gray\">日期：08-20</span></td><td class=\"tar bold\">50390.36 / 0.00 / 50390.36</td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">2143.65</td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=004863\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=004863#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=004863'>一键互转</a></td></tr><tr class='even'><td class='tal'><a href=\"http://fund.eastmoney.com/018655.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">光大保德信耀钱包货币C</a><br/><span class=\"gray\">018655</span></td><td class=\"tal\"><span class=\"bold\">0.3431</span>（<span class=\"bold\">1.5840%</span>）<br/><span class=\"gray\">日期：08-20</span></td><td class=\"tar bold\">44611.43  / 0.00 / 44611.43 </td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">611.43 </td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=018655\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=018655#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=018655'>一键互转</a></td></tr>",
    """

    oldInfo = getOld(string)
    newInfo = []
    for stockCode in stockCodes:
        newInfo += getData(stockCode)
    print(f'旧日期：{oldInfo[0]}')
    print(f'旧利率：{oldInfo[1]}')
    print(f'旧金额：{oldInfo[2]}')
    print(f'新利率：{newInfo}')




