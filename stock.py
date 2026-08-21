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


def replaceData(string, newAmounts=None, newDate=None):
    stockCodes = ['002183', '004863', '018655']
    skipCodes = ['002183']

    newAmounts = newAmounts or {}
    result = string
    positions = {'份额': 0, '未付收益': 1, '累计收益': 2}
    result = re.sub('>日期：.*?<', f'>日期：{newDate}<', result)
    for row in re.findall(r'<tr.*?</tr>', result, re.S):
        code = next((c for c in stockCodes if f'<span class="gray">{c}</span>' in row), None)
        if code is None:
            continue
        newWan, newRate = getData(code)
        newRate = newRate.rstrip('%')
        newRow = re.sub(
            r'<span class="bold">([^<]+)</span>（<span class="bold">([^<]+)</span>）',
            f'<span class="bold">{newWan}</span>（<span class="bold">{newRate}%</span>）',
            row)

        if code not in skipCodes:
            cells = re.findall(r'<td class="tar bold">([^<]+)</td>', newRow)
            for key, newVal in (newAmounts.get(code) or {}).items():
                idx = positions[key]
                oldCell = f'<td class="tar bold">{cells[idx]}</td>'
                newRow = newRow.replace(oldCell, f'<td class="tar bold">{newVal}</td>')
        result = result.replace(row, newRow)
    return result


def escapeString(string):
    match = re.search(r': "(.*)"\s*,?\s*$', string, re.S)
    if match:
        start, end = match.start(1), match.end(1)
        return string[:start] + string[start:end].replace('"', '\\"') + string[end:]
    return string.replace('"', '\\"')


if __name__ == '__main__':
    string = """
    "result": "<table class=\"balancetable\" style=\"width: 100%\"><thead><tr><th class=\"tac\">基金简称</th><th class=\"tal\"><span class=\"order\">每万份收益</span>（7日年化）</th><th class=\"tar\">可用&nbsp;/&nbsp;可取&nbsp;/&nbsp;总份额（份）</th><th class=\"tar\">未付收益（元）</th><th class=\"tac\">累计收益（元）</th><th class=\"tac\">操作</th></tr></thead><tbody data-c=\"3\"><tr class='even'><td class='tal'><a href=\"http://fund.eastmoney.com/002183.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">广发天天红货币B</a><br/><span class=\"gray\">002183</span></td><td class=\"tal\"><span class=\"bold\">0.3151</span>（<span class=\"bold\">1.1560%</span>）<br/><span class=\"gray\">日期：08-21</span></td><td class=\"tar bold\">0.04 / 0.04 / 0.04</td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">0.04</td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=002183\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=002183#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=002183'>一键互转</a></td></tr><tr><td class='tal'><a href=\"http://fund.eastmoney.com/004863.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">泰康现金管家货币C</a><br/><span class=\"gray\">004863</span></td><td class=\"tal\"><span class=\"bold\">0.3217</span>（<span class=\"bold\">1.2130%</span>）<br/><span class=\"gray\">日期：08-21</span></td><td class=\"tar bold\">41036.08 / 0.00 / 41036.08</td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">2158.90</td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=004863\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=004863#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=004863'>一键互转</a></td></tr><tr class='even'><td class='tal'><a href=\"http://fund.eastmoney.com/018655.html?spm=xjbsy\" class=\"lk\" target=\"_blank\">光大保德信耀钱包货币C</a><br/><span class=\"gray\">018655</span></td><td class=\"tal\"><span class=\"bold\">0.3383</span>（<span class=\"bold\">1.6290%</span>）<br/><span class=\"gray\">日期：08-21</span></td><td class=\"tar bold\">54000.00 / 0.00 / 54000.00</td><td class=\"tar bold\">0.00</td><td class=\"tar bold\">630.47</td><td class='cz'><a class=\"lk\" href=\"/xjb/recharge?code=018655\" title=\"T日15：00前充值，T+1日即享货币基金收益。\">充值</a>|<a class=\"lk\" href=\"/xjb/withdrawcash?code=018655#cq\" title=\"T日15：00前取现，资金T+1后到账，无限额。\">取现</a>|<a class='lk' title=\"T日15：00前互转，T+1日确认，投资不间断\" href='/xjb/transfer?code=018655'>一键互转</a></td></tr>",
    """
    newDate = '08-21'

    first = '41036.08'
    firstAnd = float(first) - 38877.18
    firstAnd = f"{firstAnd:.2f}"

    second = '54000.00'
    secondAnd = float(second) - 53369.53
    secondAnd = f"{secondAnd:.2f}"

    newAmounts = {
        '004863': {'份额': f'{first} / 0.00 / {first}', '累计收益': f'{firstAnd}'},
        '018655': {'份额': f'{second} / 0.00 / {second}', '累计收益': f'{secondAnd}'},
    }

    oldInfo = getOld(string)
    print(f'旧日期：{oldInfo[0]}')
    print(f'旧利率：{oldInfo[1]}')
    print(f'旧金额：{oldInfo[2]}')

    newString = replaceData(string, newAmounts, newDate)
    newInfo = getOld(newString)
    print(f'新日期：{newInfo[0]}')
    print(f'新利率：{newInfo[1]}')
    print(f'新金额：{newInfo[2]}')
    print('替换后string如下：')
    print(escapeString(newString))




