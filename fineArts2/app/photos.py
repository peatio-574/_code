# -*- coding: utf-8 -*-
"""报名照片：校验、压缩存储、导出命名

设计要点：
  * 上传后统一压缩（长边 ≤1600px，JPEG 质量 82），手机原图 5MB -> 约 200KB
  * 存储文件名用随机串，不保留原始文件名（避免路径穿越 / 中文乱码 / 重名）
  * 照片只存文件名，绝不放 static 目录，访问必须走带登录校验的路由
"""
import os
import re
import uuid

from flask import current_app
from PIL import Image, ImageOps

# 压缩参数
MAX_SIDE = 1440          # 长边最大像素（1440 足够看清证件照/作品细节）
JPEG_QUALITY = 80        # 压缩质量（视觉无明显损失，体积约为原图 8%~10%）
THUMB_SIDE = 400         # 缩略图长边（列表用，减少后台带宽）

ALLOWED_FORMATS = {'JPEG', 'PNG', 'BMP', 'WEBP', 'MPO'}
SAVED_EXT = '.jpg'       # 一律转存为 JPEG

# 文件名非法字符（Windows / Linux 通用）
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def upload_dir():
    path = current_app.config['SIGNUP_UPLOAD_DIR']
    os.makedirs(path, exist_ok=True)
    return path


def thumb_dir():
    path = os.path.join(upload_dir(), 'thumb')
    os.makedirs(path, exist_ok=True)
    return path


def photo_path(filename):
    """原图路径。"""
    return os.path.join(upload_dir(), os.path.basename(filename or ''))


def thumb_path(filename):
    """缩略图路径。"""
    return os.path.join(thumb_dir(), os.path.basename(filename or ''))


def default_photo_path():
    """无照片时使用的占位图（放在 static/img 下，可直接静态访问）。"""
    return os.path.join(current_app.static_folder, 'img', 'no-photo.jpg')


def _flatten(img):
    """统一转成 RGB：透明背景填白，避免 PNG 转 JPEG 变黑底。"""
    if img.mode in ('RGBA', 'LA') or (
            img.mode == 'P' and 'transparency' in img.info):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != 'RGB':
        return img.convert('RGB')
    return img


def _resize(img, max_side):
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                      Image.LANCZOS)


def save_signup_photo(file_storage):
    """校验并保存上传的照片。

    返回 (文件名, 错误信息)。成功时错误信息为 None。
    """
    if file_storage is None or not (file_storage.filename or '').strip():
        return None, '请上传报名照片'

    max_size = current_app.config.get('MAX_PHOTO_SIZE', 8 * 1024 * 1024)
    # 文件大小：Flask 已按 MAX_CONTENT_LENGTH 拦截整包，这里再按单文件校验
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        return None, '照片文件为空'
    if size > max_size:
        return None, '照片不能超过 %d MB' % (max_size // 1024 // 1024)

    # 真正解码一次，可过滤掉「改了扩展名」的假图片
    try:
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img.load()
    except Exception:
        return None, '照片格式无法识别，请上传 jpg / png 图片'

    if (img.format or '').upper() not in ALLOWED_FORMATS:
        return None, '只支持 jpg / png / bmp / webp 格式'

    # 手机照片常带 EXIF 旋转信息，先摆正再压缩
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    try:
        img = _flatten(img)

        filename = uuid.uuid4().hex + SAVED_EXT

        # 原图（供详情 / 导出使用）
        big = _resize(img, MAX_SIDE)
        big.save(photo_path(filename), 'JPEG', quality=JPEG_QUALITY,
                 optimize=True, progressive=True)

        # 缩略图（列表用，体积约 20~40KB）
        small = _resize(img, THUMB_SIDE)
        small.save(thumb_path(filename), 'JPEG', quality=80, optimize=True)
    except Exception as exc:
        return None, '照片保存失败：%s' % exc

    return filename, None


def delete_photo_files(filename):
    """删除某条报名对应的原图与缩略图（忽略不存在）。"""
    if not filename:
        return
    for path in (photo_path(filename), thumb_path(filename)):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def _clean(text, fallback='未填'):
    text = str(text or '').strip()
    text = _ILLEGAL.sub('', text)
    text = text.strip(' .')
    return text or fallback


def export_basename(reg):
    """导出文件名（不含扩展名）：姓名_身份证号_科目_级别

    非法字符会被剔除；字段为空时用「未填」占位，保证格式固定。
    """
    parts = [
        _clean(reg.name, '未知姓名'),
        _clean(reg.id_card, '无身份证号'),
        _clean(reg.subject, '未填科目'),
        _clean(reg.level, '未填级别'),
    ]
    name = '_'.join(parts)
    # 防止极端情况下文件名过长（Windows 单段上限 255 字节）
    if len(name.encode('utf-8')) > 180:
        name = name.encode('utf-8')[:180].decode('utf-8', 'ignore')
    return name
