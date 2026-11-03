# -*- coding: utf-8 -*-
"""姓名转拼音。

报名表只收集中文姓名，但导出给考级机构的名单需要拼音列。
这里统一在服务端生成，格式与本项目证书数据一致：
    王沐凡 -> Wang Mu Fan
    吕欣盈 -> Lyu Xin Ying

ü 按中国护照/身份证的写法转成 yu（吕 -> Lyu），不用 lv。
pypinyin 缺失时返回空串，不能让报名流程因此失败。
"""
import re

#: 拼音之间用单个空格分隔，多空格/首尾空格统一压掉
_SPACE_RE = re.compile(r'\s+')

#: 姓名里不是汉字的字符（如英文名、间隔号）原样保留为一段
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _syllable(text):
    """单个音节规整：ü(lv/nv) -> yu，首字母大写。"""
    s = text.strip()
    if not s:
        return ''
    # pypinyin 用 v 表示 ü：lv -> lyu, nv -> nyu, lve -> lyue
    s = s.replace('v', 'yu')
    return s[:1].upper() + s[1:]


def to_pinyin(name):
    """中文姓名 -> 空格分隔的拼音，如 'Wang Mu Fan'。失败时返回空串。"""
    name = (name or '').strip()
    if not name:
        return ''
    try:
        from pypinyin import Style, lazy_pinyin
    except Exception:
        # 依赖没装：不阻断报名，只是导出时这一列为空
        return ''

    try:
        # 非汉字（英文名、‧等）原样输出，保证不会整段丢失
        parts = lazy_pinyin(name, style=Style.NORMAL, errors=lambda x: list(x))
    except Exception:
        return ''

    syllables = [_syllable(p) for p in parts]
    out = _SPACE_RE.sub(' ', ' '.join(s for s in syllables if s)).strip()
    return out


def pinyin_of(reg):
    """取一条报名的拼音：优先用库里存的，没有就现算（兼容历史数据）。"""
    stored = (getattr(reg, 'name_pinyin', '') or '').strip()
    if stored:
        return stored
    return to_pinyin(getattr(reg, 'name', ''))
