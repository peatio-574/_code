# -*- coding: utf-8 -*-
"""
Daily US stock / ETF / index data, 2016-01-01 ~ 2025-12-31.
One CSV per ticker, English headers: Date,Open,High,Low,Close,Volume,Adj Close

Price convention = Yahoo: Open/High/Low/Close are split-adjusted,
Volume is split-adjusted, Adj Close is split+dividend adjusted.

Sources
-------
* stockanalysis.com  : split-adjusted OHLCV + adjusted close (10Y window)
* Tencent gtimg      : raw OHLCV (full history) + forward-adjusted close (qfq)
* indexes.nasdaqomx.com : Nasdaq US Electricity Large Mid Cap Index NQUSB651010LM
                          (official Nasdaq GIW; High/Low/Close, no volume)
"""
import os
import csv
import time
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
START, END = "2016-01-01", "2025-12-31"
OLDEST = "2015-01-01"
PAGE = 640

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA})

TX_RAW = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={s},day,{a},{b},{n}"
TX_QFQ = "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param={s},day,{a},{b},{n},qfq"
SA = "https://stockanalysis.com/api/symbol/s/{s}/history?range=10Y&period=Daily"

STOCKS = [("NEE", "usNEE.N"), ("SO", "usSO.N"), ("DUK", "usDUK.N"),
          ("AEP", "usAEP.OQ"), ("EXC", "usEXC.OQ"), ("VST", "usVST.N"),
          ("CEG", "usCEG.OQ"), ("D", "usD.N"), ("CWEN", "usCWEN.N"),
          ("FE", "usFE.N"), ("XLU", "usXLU.AM")]


def get(url, headers=None, tries=6, timeout=30):
    for i in range(tries):
        try:
            r = S.get(url, headers=headers, timeout=timeout)
            return r
        except Exception as e:
            print("      retry %d/%d %s" % (i + 1, tries, type(e).__name__))
            time.sleep(3 + i * 2)
    return None


def stockanalysis(sym):
    r = get(SA.format(s=sym), tries=8, timeout=45)
    if not r or r.status_code != 200:
        return {}
    return {x["t"]: x for x in r.json().get("data", [])}


def tx_history(sym, mode):
    url_t = TX_RAW if mode == "raw" else TX_QFQ
    out, end, prev = {}, END, None
    for _ in range(30):
        r = get(url_t.format(s=sym, a=OLDEST, b=end, n=PAGE),
                headers={"Referer": "https://gu.qq.com/"}, tries=4)
        if not r:
            break
        try:
            j = r.json()
        except Exception:
            break
        if j.get("code") != 0:
            break
        d = j.get("data", {}).get(sym, {})
        rows = d.get("day") or d.get("qfqday")
        if not rows:
            break
        for row in rows:
            out[row[0]] = row
        earliest = min(x[0] for x in rows)
        if earliest == prev or earliest <= "2015-12-31":
            break
        prev = earliest
        end = (dt.date.fromisoformat(earliest) - dt.timedelta(days=1)).isoformat()
        time.sleep(0.4)
    return out


def f(x, nd=4):
    return "" if x is None else ("%.*f" % (nd, x))


def build_stock(name, sym):
    sa = stockanalysis(name)
    raw = tx_history(sym, "raw")
    time.sleep(0.4)
    qfq = tx_history(sym, "qfq")

    common = sorted(set(sa) & set(raw))
    factor = 1.0
    if common:
        d0 = common[0]
        rc = float(raw[d0][2])
        sc = sa[d0]["c"]
        if sc:
            factor = rc / sc
    print("      split factor = %.4f" % factor)

    rows = []
    for date in sorted(set(sa) | set(raw) | set(qfq)):
        if not (START <= date <= END):
            continue
        if date in sa:
            x = sa[date]
            rows.append([date, f(x.get("o")), f(x.get("h")), f(x.get("l")),
                         f(x.get("c")), str(int(x["v"])) if x.get("v") is not None else "",
                         f(x.get("a"))])
        elif date in raw:
            r = raw[date]
            o, c, h, low, v = (float(r[1]), float(r[2]), float(r[3]),
                               float(r[4]), float(r[5]))
            adj = float(qfq[date][2]) if date in qfq else c / factor
            rows.append([date, f(o / factor), f(h / factor), f(low / factor),
                         f(c / factor), str(int(v * factor)), f(adj)])
    return rows


def build_gspc(name, sym):
    qfq = tx_history(sym, "qfq")
    rows = []
    for date in sorted(qfq):
        if not (START <= date <= END):
            continue
        r = qfq[date]
        rows.append([date, f(float(r[1])), f(float(r[3])), f(float(r[4])),
                     f(float(r[2])), str(int(float(r[5]))), f(float(r[2]))])
    return rows


def build_nqusb(name, sym):
    """Official Nasdaq index history (JSON). 'Open' in the payload is the
    previous close, so it is left blank; volume is not published for indices."""
    r = S.post("https://indexes.nasdaqomx.com/Index/HistoryChartData",
               data={"id": sym, "startDate": START, "endDate": END},
               headers={"X-Requested-With": "XMLHttpRequest",
                        "Referer": "https://indexes.nasdaqomx.com/Index/History/" + sym},
               timeout=60)
    r.raise_for_status()
    rows = []
    for x in r.json():
        d = dt.datetime.utcfromtimestamp(x["x"] / 1000).strftime("%Y-%m-%d")
        if not (START <= d <= END):
            continue
        c = x["y"]
        h, l = x.get("High"), x.get("Low")
        rows.append([d, "", f(h), f(l), f(c), "", f(c)])
    return rows


def write(name, rows):
    path = os.path.join(BASE, name + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Adj Close"])
        w.writerows(rows)
    return path, len(rows)


def main():
    print("->", BASE)
    for name, sym in STOCKS:
        print("[%s]" % name)
        try:
            rows = build_stock(name, sym)
            p, n = write(name, rows)
            print("   %s rows=%d %s ~ %s" % (os.path.basename(p), n,
                                             rows[0][0], rows[-1][0]))
        except Exception as e:
            print("   !! %s: %s" % (name, e))
        time.sleep(1)

    print("[GSPC]")
    rows = build_gspc("GSPC", "usINX")
    p, n = write("GSPC", rows)
    print("   %s rows=%d %s ~ %s" % (os.path.basename(p), n, rows[0][0], rows[-1][0]))

    print("[NQUSB651010LM]")
    try:
        rows = build_nqusb("NQUSB651010LM", "NQUSB651010LM")
        p, n = write("NQUSB651010LM", rows)
        print("   %s rows=%d %s ~ %s" % (os.path.basename(p), n, rows[0][0], rows[-1][0]))
    except Exception as e:
        print("   !! %s" % e)


if __name__ == "__main__":
    main()
