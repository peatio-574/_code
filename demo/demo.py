# -*- coding: utf-8 -*-
import sys

import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import requests

def add_page():
    url = 'http://bd-hgla.bdeastmoney.net/bd-hgla-manage/appPageConfig/add'
    for i in range(6, 100):
        params = {
            "productName": "天天基金",
            "pageName": f"新页面{i}",
            "pageNameEn": f"newpage{i}",
            "typeOid": 56
        }
        headers = {
            'content-type': 'application/json;charset=UTF-8',
            'cookie': 'Authorization=Token:7c8445d3-c9e2-4cde-b8f4-2a816f071121; st_si=39831367604773; st_asi=delete; st_pvi=76837210229259; st_sp=2025-10-30%2015%3A48%3A57; st_inirUrl=; st_sn=74; st_psi=20260511151117265-1888350886-9300920823',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.post(url, headers=headers, data=json.dumps(params)).content.decode('utf-8')
        print(response)
        # break

def add_column():
    url = 'http://bd-hgla.bdeastmoney.net/bd-hgla-manage/appFieldInfo'
    headers = {
        'content-type': 'application/json;charset=UTF-8',
        'cookie': 'Authorization=Token:7c8445d3-c9e2-4cde-b8f4-2a816f071121; st_si=39831367604773; st_asi=delete; st_pvi=76837210229259; st_sp=2025-10-30%2015%3A48%3A57; st_inirUrl=; st_sn=74; st_psi=20260511151117265-1888350886-9300920823',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    for i in range(9, 100):
        params = {
        "inputName": f"column{i}",
        "fieldChName": f"字段{i}",
        "fieldType": "字符串",
        "businessDesc": f"字段{i}业务说明",
        "firststaff": "",
        "laststaff": "",
        "caseDesc": f"字段{i}案例说明",
        "enumObj": "",
        "enumInfoList": [
            {
                "des": "成都",
                "fieldEnumMean": "成都",
                "fieldEnumName": "成都"
            },
            {
                "des": "重庆",
                "fieldEnumMean": "重庆",
                "fieldEnumName": "重庆"
            },
            {
                "des": "北京",
                "fieldEnumMean": "北京",
                "fieldEnumName": "北京"
            }
        ],
        "isStd": "1",
        "typeOid": 56,
        "regexPattern": "",
        "productScope": 1,
        "isEnum": 1,
        "isRegex": 0
    }

        resp = requests.post(url, headers=headers, data=json.dumps(params)).content.decode('utf-8')
        print(resp)


def add_alert():
    url = 'http://bd-hgla.bdeastmoney.net/bd-hgla-manage/api/monitor/warn/send'
    headers = {
        'content-type': 'application/json;charset=UTF-8',
        # 'cookie': 'Authorization=Token:7c8445d3-c9e2-4cde-b8f4-2a816f071121; st_si=39831367604773; st_asi=delete; st_pvi=76837210229259; st_sp=2025-10-30%2015%3A48%3A57; st_inirUrl=; st_sn=74; st_psi=20260511151117265-1888350886-9300920823',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    params = [
    {
        "monitorTime": "2026-05-12 14:07:00",  # 时间
        "monitorType": "alert",  # 告警类型
        "buriedCode": "xnsj20230924185336-ys",  # 埋点code
        "reportMode": "app",  # 上报类型
        "buriedType": "page",  # 埋点类型
        "errorType": "event_type_error",  # 异常类型
        "caseData": "{\"app_eventkey\": \"ghr.test.001\", \"app_eventparameter\": {\"key1\": \"value1\", \"key2\": \"value2\"}}}"
    },
    {
        "monitorTime": "2026-05-12 14:07:01",
        "monitorType": "alert",
        "buriedCode": "dfcfwsy_sp_cjdd12_bgl",
        "reportMode": "app",
        "buriedType": "event_active",
        "errorType": "field_key_error",
        "caseData": "{\"app_eventparameter\": {\"INFOCODE\": \"123456\", \"INFOCODETYPE\": \"ZX\"}}}"
    }
]
