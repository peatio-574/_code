# -*- coding: utf-8 -*-
"""
Fetch daily US stock / ETF / index data 2016-01-01 ~ 2025-12-31 from Yahoo Finance.
Yahoo is reached through a local HTTP proxy (set PROXY below).
Output: one CSV per ticker, English headers Date,Open,High,Low,Close,Volume,Adj Close
"""
import os
import csv
import time
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
START = "2016-01-01"
END = "2025-12-31"
PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7892")

TICKERS = ["NEE", "SO", "DUK", "AEP", "EXC", "VST", "CEG", "D", "CWEN", "FE",
           "XLU", "^GSPC"]

HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(HEADERS)
SESSION.proxies = {"http": PROXY, "https": PROXY}

P1 = int(dt.datetime(2016, 1, 1).timestamp())
P2 = int(dt.datetime(2026, 1, 1).timestamp())


def fetch(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + requests.utils.quote(symbol))
    for attempt in range(8):
        try:
            r = SESSION.get(url, params={"period1": P1, "period2": P2,
                                         "interval": "1d", "events": "div,split"},
                            timeout=60)
            j = r.json()["chart"]["result"][0]
            ts = j["timestamp"]
            q = j["indicators"]["quote"][0]
            adj = j["indicators"]["adjclose"][0]["adjclose"]
            rows = []
            for k, t in enumerate(ts):
                d = dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
                if not (START <= d <= END):
                    continue
                o, h, l, c = q["open"][k], q["high"][k], q["low"][k], q["close"][k]
                if c is None:
                    continue
                v = q["volume"][k]
                a = adj[k]
                rows.append([
                    d,
                    "" if o is None else "%.4f" % o,
                    "" if h is None else "%.4f" % h,
                    "" if l is None else "%.4f" % l,
                    "%.4f" % c,
                    "" if v is None else str(int(v)),
                    "" if a is None else "%.4f" % a,
                ])
            return rows
        except Exception as exc:
            print("      retry %d/8 (%s)" % (attempt + 1, exc))
            time.sleep(3 + attempt * 2)
    return None


def write(name, rows):
    path = os.path.join(BASE, name + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Adj Close"])
        w.writerows(rows)
    return path, len(rows)


def main():
    print("proxy:", PROXY)
    for t in TICKERS:
        print("[%s]" % t)
        rows = fetch(t)
        if not rows:
            print("   !! no data"); continue
        name = t.lstrip("^")
        p, n = write(name, rows)
        print("   %s rows=%d %s ~ %s" % (os.path.basename(p), n, rows[0][0], rows[-1][0]))
        time.sleep(1)


if __name__ == "__main__":
    main()
