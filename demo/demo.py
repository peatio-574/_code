import requests
import pandas as pd
from datetime import datetime, timedelta

# ---------- 1. 获取某周期最后一根已结束K线的收盘价 ----------
def get_last_closed_kline_close(stock_code, klt):
    """
    klt: 60/120/101(日)/102(周)/103(月)
    返回：该周期「已结束」的最后一根收盘价
    """
    secid = f"1.{stock_code}" if stock_code.startswith(("60", "68")) else f"0.{stock_code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,
        "fqt": 0,
        "beg": "0",
        "end": "20990101",
        "lmt": "2000"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return None
        # 倒数第1根可能是“未完成的当前K线”，取倒数第2根作为“已结束最后一根”
        if len(klines) >= 2:
            last_closed = klines[-2]
        else:
            last_closed = klines[-1]
        return float(last_closed.split(",")[2])
    except Exception as e:
        print("接口错误:", e)
        return None

# ---------- 2. 通过日线取季/半年/年最后一天收盘价 ----------
def get_quarter_halfyear_year_close(stock_code):
    secid = f"1.{stock_code}" if stock_code.startswith(("60", "68")) else f"0.{stock_code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 0,
        "beg": "0",
        "end": "20990101",
        "lmt": "5000"
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return None, None, None

    rows = []
    for line in klines:
        parts = line.split(",")
        dt = pd.to_datetime(parts[0])
        close = float(parts[2])
        rows.append({"date": dt, "close": close})

    df = pd.DataFrame(rows)
    df.set_index("date", inplace=True)

    # 去“已结束”的最后一个季/半年/年
    q_close = df.resample("QE").last().iloc[-2]["close"] if len(df.resample("QE"))>=2 else None
    hy_close = df.resample("6ME").last().iloc[-2]["close"] if len(df.resample("6ME"))>=2 else None
    y_close = df.resample("YE").last().iloc[-2]["close"] if len(df.resample("YE"))>=2 else None

    return q_close, hy_close, y_close

# ---------- 3. 主程序 ----------
if __name__ == "__main__":
    stock = "600111"
    print(f"===== {stock} 各周期「已结束」最后一根收盘价 =====")

    res_60m  = get_last_closed_kline_close(stock, 60)
    res_120m = get_last_closed_kline_close(stock, 120)
    res_day  = get_last_closed_kline_close(stock, 101)
    res_week = get_last_closed_kline_close(stock, 102)
    res_month= get_last_closed_kline_close(stock, 103)

    res_q, res_hy, res_y = get_quarter_halfyear_year_close(stock)

    print(f"60分钟（最后已完成）: {res_60m}")
    print(f"120分钟（最后已完成）: {res_120m}")
    print(f"日线（昨日收盘）: {res_day}")
    print(f"周线（上周收盘）: {res_week}")
    print(f"月线（上月收盘）: {res_month}")
    print(f"季线（上季收盘）: {res_q}")
    print(f"半年线（上半年收盘）: {res_hy}")
    print(f"年线（去年收盘）: {res_y}")