# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


import requests

url = 'https://sns-video-v6.xhscdn.com/stream/79/110/259/01ea0c31013de52e010370039e3fa205b9_259.mp4?sign=08201fbede481cb7db14df3fb14b0c1d&t=6a30625d'
with open('./test.mp4', 'wb') as f:
    info = requests.get(url).content
    # print(info)
    f.write(info)

# url = 'http://bd-hgla.bdeastmoney.net/bd-hgla-manage/appFieldInfo'
# headers = {
#     'Content-Type': 'application/json;charset=UTF-8',
#     'cookie': 'Authorization=Token:ac4aea8d-1732-4847-a9e6-0ec3fd474002; st_si=99000168782761; st_asi=delete; st_pvi=76837210229259; st_sp=2025-10-30%2015%3A48%3A57; st_inirUrl=http%3A%2F%2Fbd-hgla.bdeastmoney.net%2F; st_sn=130; st_psi=20260612153752326-1888350886-9628875278',
#     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36'
# }
# for i in range(1, 500):
#     params = {
#     "inputName": f"auto{i}",
#     "fieldChName": f"自动{i}",
#     "fieldType": "字符串",
#     "businessDesc": f"自动{i}",
#     "firststaff": "",
#     "laststaff": "",
#     "caseDesc": "",
#     "enumObj": "",
#     "enumInfoList": [
#         {
#             "des": "",
#             "fieldEnumMean": "测试",
#             "fieldEnumName": "测试"
#         },
#         {
#             "des": "",
#             "fieldEnumMean": "哈哈",
#             "fieldEnumName": "哈哈"
#         },
#         {
#             "des": "",
#             "fieldEnumMean": "嘿嘿",
#             "fieldEnumName": "嘿嘿"
#         }
#     ],
#     "isStd": "1",
#     "typeOid": 59,
#     "regexPattern": "",
#     "productScope": 1,
#     "isEnum": 0,
#     "isRegex": 0
# }
#     info = requests.post(url, json=params, headers=headers).json()
#     print(info)