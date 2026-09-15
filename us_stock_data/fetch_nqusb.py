# -*- coding: utf-8 -*-
"""Nasdaq US Electricity Large Mid Cap Index (NQUSB651010LM) from indexes.nasdaqomx.com."""
import csv, datetime as dt, requests

OUT = r"D:\_code\us_stock_data\NQUSB651010LM.csv"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
     "X-Requested-With": "XMLHttpRequest",
     "Referer": "https://indexes.nasdaqomx.com/Index/History/NQUSB651010LM"}

r = requests.post("https://indexes.nasdaqomx.com/Index/HistoryChartData",
                  data={"id": "NQUSB651010LM", "startDate": "2016-01-01",
                        "endDate": "2025-12-31"}, headers=H, timeout=60)
data = r.json()
rows = []
for x in data:
    d = dt.datetime.utcfromtimestamp(x["x"] / 1000).strftime("%Y-%m-%d")
    if not ("2016-01-01" <= d <= "2025-12-31"):
        continue
    close = x["y"]
    high = x.get("High")
    low = x.get("Low")
    rows.append([d, "", "" if high is None else "%.4f" % high,
                 "" if low is None else "%.4f" % low,
                 "%.4f" % close, "", "%.4f" % close])

with open(OUT, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Adj Close"])
    w.writerows(rows)

print("wrote", OUT, "rows", len(rows), rows[0][0], "~", rows[-1][0])
print(rows[0], rows[-1])
