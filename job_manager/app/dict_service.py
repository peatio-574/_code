"""数据字典读取服务。

字典项 = 键(key, 数字) + 值(value, 枚举文本)。
岗位等业务字段直接存储枚举文本(value)，本模块仅用于为表单/筛选下拉提供“启用中”的选项。
"""
from .models import DictType, DictItem


def _items(code, only_active=False):
    dtype = DictType.query.filter_by(code=code, is_deleted=False).first()
    if not dtype:
        return []
    query = DictItem.query.filter_by(type_id=dtype.id, is_deleted=False)
    if only_active:
        query = query.filter_by(is_active=True)
    return query.order_by(DictItem.key.asc(), DictItem.id.asc()).all()


def options(code):
    """启用中的字典项，用于表单/筛选下拉（禁用项不出现）。"""
    return [{'key': it.key, 'value': it.value} for it in _items(code, only_active=True)]
