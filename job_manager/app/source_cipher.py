# -*- coding: utf-8 -*-
"""来源字段加解密

约定：
  * 数据库里 ``dict_items.value``（来源字典）与 ``jobs.source`` 存**密文**
  * ``dict_items.label`` 存**明文**，供字典管理页展示与人工识别
  * 岗位管理页的「来源」列按需求直接显示密文

当前加密方案：纯 Base64（UTF-8 编码后 Base64）
    国聘        -> 5Zu96IGY
    智联招聘    -> 5pm66IGU5oub6IGY
    BOSS直聘    -> Qk9TU+ebtOiBmA==

兼容旧格式：早期 spiderJobs 生成的「XOR + Base64」密文
    MT86N4Lp/ofj6w -> BOSS直聘
读取时会自动识别并解码，写回时统一转成纯 Base64。
旧格式密钥可用环境变量 SOURCE_LEGACY_KEY 覆盖。
"""
import base64
import os

# 来源字段在 dict_types.code 里的编码
SOURCE_DICT_CODE = 'source'

# 旧版 XOR+Base64 的密钥（仅用于读取历史数据）
LEGACY_KEY = os.environ.get('SOURCE_LEGACY_KEY', 'spiderJobs-2026')


def encode(text):
    """明文 -> 密文（纯 Base64）。空值返回空串。"""
    text = str(text or '')
    if not text:
        return ''
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def _b64_decode(value):
    """Base64 解码，失败返回 None。"""
    try:
        padded = value + '=' * (-len(value) % 4)
        return base64.b64decode(padded, validate=True)
    except (ValueError, TypeError):
        return None


def _readable(text):
    """判断解码结果是否像正常文本（中文/英文/常见符号），排除乱码。"""
    if not text:
        return False
    return text.isprintable() and text.strip() == text


def _legacy_xor(raw, key):
    """按字节与密钥循环异或（对称）。"""
    k = key.encode('utf-8')
    if not k:
        return raw
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))


def decode(value):
    """密文 -> 明文。

    依次尝试：
      1. 纯 Base64（当前方案）
      2. XOR + Base64（早期 spiderJobs 方案）
    都不像密文、或解出来不是可读文本时，原样返回（兼容历史明文数据）。
    """
    value = str(value or '')
    if not value:
        return ''

    raw = _b64_decode(value)
    if raw is None:
        return value

    # 1) 纯 Base64
    try:
        text = raw.decode('utf-8')
        if _readable(text):
            return text
    except UnicodeDecodeError:
        pass

    # 2) 旧版 XOR + Base64
    try:
        text = _legacy_xor(raw, LEGACY_KEY).decode('utf-8')
        if _readable(text):
            return text
    except (UnicodeDecodeError, ValueError):
        pass

    return value


def is_cipher(value):
    """判断一个值是否是可识别的密文（新/旧格式都算）。"""
    value = str(value or '')
    if not value:
        return False
    return decode(value) != value


def dict_map(include_inactive=True):
    """来源字典的 {明文: 密文} 映射，密文统一为纯 Base64。

    include_inactive=True 时包含已禁用项 —— 导入历史数据时仍应能匹配到，
    否则同一个平台会因为字典被禁用而变成两种密文。

    兼容存量数据：value 或 label 可能还是旧格式密文/明文，
    这里统一解出明文，再按当前方案重新编码。
    """
    from .models import DictItem, DictType

    dtype = DictType.query.filter_by(code=SOURCE_DICT_CODE, is_deleted=False).first()
    if not dtype:
        return {}

    query = DictItem.query.filter_by(type_id=dtype.id, is_deleted=False)
    if not include_inactive:
        query = query.filter_by(is_active=True)

    result = {}
    for it in query.order_by(DictItem.key.asc(), DictItem.id.asc()).all():
        plain = _item_plain(it)
        if plain:
            result.setdefault(plain, encode(plain))
    return result


def _item_plain(item):
    """取字典项的明文名。

    存量数据里 label 可能被写成了密文，所以要判断：
    value 能解出明文就用它，否则用 label（label 也可能是密文）。
    """
    value = str(item.value or '').strip()
    if value:
        plain = decode(value)
        if plain != value:            # value 是密文，解出了明文
            return plain
    label = str(item.label or '').strip()
    if label:
        plain = decode(label)
        return plain or label
    return value


def item_cipher(item):
    """字典项的规范密文（统一成当前纯 Base64 方案）。

    存量数据可能是旧格式密文或明文，这里统一归一化，
    保证下拉框提交的值、以及写入 jobs.source 的值格式一致。
    """
    plain = _item_plain(item)
    return encode(plain) if plain else ''


def item_plain(item):
    """取字典项的明文名（公开版，供路由使用）。"""
    return _item_plain(item)


def find_by_plain(type_id, plain, exclude_id=0):
    """在指定字典里按「明文」查找枚举项，找不到返回 None。

    不能用 value 直接比对：库里可能同时存在旧格式密文，
    必须按解出的明文比较，否则旧数据会被判成不重复而插入重复项。
    """
    from .models import DictItem

    target = str(plain or '').strip().casefold()
    if not target:
        return None
    rows = DictItem.query.filter_by(type_id=type_id, is_deleted=False).all()
    for it in rows:
        if exclude_id and it.id == exclude_id:
            continue
        other = _item_plain(it)
        if other and other.strip().casefold() == target:
            return it
    return None


def normalize(value):
    """把任意来源值（明文 / 旧格式密文）统一成当前方案的纯 Base64。

    与 resolve 的区别：不做字典匹配、不写库，纯格式归一化。
    用于展示（编辑页下拉、列表）与保存前的兜底。
    """
    raw = str(value or '').strip()
    if not raw:
        return ''
    return encode(decode(raw))


def resolve(value, add_missing=False):
    """把任意输入统一成密文（表单提交走这里）。"""
    cipher, _matched = resolve_with_map(value, dict_map(), add_missing=add_missing)
    return cipher


def resolve_with_map(value, cmap, add_missing=False):
    """同 resolve，但复用外部传入的字典映射（批量导入时避免逐行查库）。

    返回 (密文, 是否命中字典)。
    """
    raw = str(value or '').strip()
    if not raw:
        return '', True

    # 1) 明文精确命中字典
    if raw in cmap:
        return cmap[raw], True

    # 2) 忽略大小写/空格的容错命中
    target = raw.casefold()
    for plain, cipher in cmap.items():
        if plain.casefold() == target:
            return cipher, True

    # 3) 本身已是密文（新或旧格式）：解码成明文，再统一成当前方案
    if is_cipher(raw):
        plain = decode(raw)
        if plain in cmap:
            return cmap[plain], True
        return encode(plain), True

    # 4) 字典里没有的明文：编码兜底
    cipher = encode(raw)
    if add_missing:
        _add_dict_item(raw, cipher)
    return cipher, False


def _add_dict_item(plain, cipher):
    """把未匹配的明文补进来源字典（仅在 add_missing=True 时调用）。"""
    from .models import db, DictItem, DictType

    dtype = DictType.query.filter_by(code=SOURCE_DICT_CODE, is_deleted=False).first()
    if not dtype:
        return
    if DictItem.query.filter_by(type_id=dtype.id, value=cipher,
                                is_deleted=False).first():
        return
    max_key = db.session.query(db.func.max(DictItem.key)).filter(
        DictItem.type_id == dtype.id,
        DictItem.is_deleted == False).scalar() or 0
    db.session.add(DictItem(
        type_id=dtype.id, key=max_key + 1, label=plain, value=cipher,
        sort_order=max_key + 1, is_active=True,
    ))
