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


def _chunks(text):
    """把字符串按「连续汉字 / 连续非汉字」切成段。

    两点都要照顾到：
      * 非汉字要整块保留：pypinyin 的 errors 回调是**逐字**调用的，
        直接返回 list(x) 会把 '张Alice' 拆成 'Zhang A L I C E'；
      * 连续汉字也要整块保留：拆开会让词组词典失效，
        '成都' 会从 'Cheng Du' 变成 'Cheng Dou'。
    """
    chunks = []
    buf = []
    last_is_cjk = None
    for ch in text:
        is_cjk = bool(_CJK_RE.match(ch))
        if last_is_cjk is None or is_cjk == last_is_cjk:
            buf.append(ch)
        else:
            chunks.append(''.join(buf))
            buf = [ch]
        last_is_cjk = is_cjk
    if buf:
        chunks.append(''.join(buf))
    return chunks


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

    out = []
    try:
        # 分段处理：汉字走拼音（整段送去以命中词组），非汉字整块保留
        for chunk in _chunks(name):
            if _CJK_RE.match(chunk[0]):
                out.extend(lazy_pinyin(chunk, style=Style.NORMAL))
            else:
                piece = chunk.strip()
                if piece:
                    out.append(piece[:1].upper() + piece[1:])
    except Exception:
        return ''

    syllables = [_syllable(p) for p in out]
    return _SPACE_RE.sub(' ', ' '.join(s for s in syllables if s)).strip()


def pinyin_of(reg):
    """取一条报名的拼音：优先用库里存的，没有就现算（兼容历史数据）。"""
    stored = (getattr(reg, 'name_pinyin', '') or '').strip()
    if stored:
        return stored
    return to_pinyin(getattr(reg, 'name', ''))
