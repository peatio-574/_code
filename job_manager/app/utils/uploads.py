# -*- coding: utf-8 -*-
"""文件上传工具：头像等文件的保存/删除。

头像统一保存到 UPLOAD_FOLDER/avatars/ 下，数据库里存 URL 路径
（形如 /uploads/avatars/xxxxxxxx.png），由应用通过 /uploads/<path> 提供访问。
"""
import os
import uuid

from flask import current_app

# 允许的头像扩展名
ALLOWED_AVATAR_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}

# 头像 URL 前缀与磁盘子目录
AVATAR_URL_PREFIX = '/uploads/avatars/'
AVATAR_SUBDIR = 'avatars'


def save_avatar(file_storage, old_path=''):
    """保存上传的头像文件。

    参数：
      file_storage: werkzeug 的 FileStorage（request.files.get('avatar')）
      old_path: 旧头像 URL（保存成功后删除旧文件，避免堆积）
    返回：新的头像 URL 路径（如 /uploads/avatars/xxx.png）；无有效文件返回 None。
    非法格式抛 ValueError。
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = file_storage.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_AVATAR_EXTS:
        raise ValueError('头像仅支持 png / jpg / jpeg / gif / webp / bmp 格式')

    upload_dir = current_app.config.get('UPLOAD_FOLDER')
    avatar_dir = os.path.join(upload_dir, AVATAR_SUBDIR)
    os.makedirs(avatar_dir, exist_ok=True)

    stored_name = f'{uuid.uuid4().hex}.{ext}'
    file_storage.save(os.path.join(avatar_dir, stored_name))

    # 删除旧头像（仅限本站上传的）
    delete_avatar(old_path)

    return AVATAR_URL_PREFIX + stored_name


def delete_avatar(path):
    """删除本站上传的头像文件；外部 URL 或空值忽略。"""
    if not path or not path.startswith('/uploads/'):
        return
    try:
        upload_dir = current_app.config.get('UPLOAD_FOLDER')
        rel = path[len('/uploads/'):].replace('\\', '/')
        full = os.path.join(upload_dir, *rel.split('/'))
        if os.path.isfile(full):
            os.remove(full)
    except Exception:
        pass
