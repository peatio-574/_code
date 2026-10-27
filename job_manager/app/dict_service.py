"""数据字典读取服务。

字典项 = 键(key, 数字) + 值(value, 枚举文本)。
岗位等业务字段直接存储枚举文本(value)，本模块仅用于为表单/筛选下拉提供“启用中”的选项。
"""
from .models import DictType, DictItem
from .source_cipher import SOURCE_DICT_CODE, decode


def _items(code, only_active=False):
    dtype = DictType.query.filter_by(code=code, is_deleted=False).first()
    if not dtype:
        return []
    query = DictItem.query.filter_by(type_id=dtype.id, is_deleted=False)
    if only_active:
        query = query.filter_by(is_active=True)
    return query.order_by(DictItem.key.asc(), DictItem.id.asc()).all()


def options(code):
    """启用中的字典项，用于表单/筛选下拉（禁用项不出现）。

    label 恒为明文；value 为入库值（来源字典即密文）。
    """
    items = _items(code, only_active=True)
    if code == SOURCE_DICT_CODE:
        return [{'key': it.key, 'value': it.value,
                 'label': decode(it.value)} for it in items]
    return [{'key': it.key, 'value': it.value, 'label': it.value}
            for it in items]
