# -*- coding: utf-8 -*-
"""图片验证码：简单的加减乘除算术题"""
import base64
import io
import os
import random
import threading
import time
import uuid

from PIL import Image, ImageDraw, ImageFont

_store = {}
_lock = threading.Lock()
TTL = 300

_FONT_CANDIDATES = [
    r'C:\Windows\Fonts\msyhbd.ttc',      # 微软雅黑（支持中文）
    r'C:\Windows\Fonts\simhei.ttf',      # 黑体
    r'C:\Windows\Fonts\simsun.ttc',      # 宋体
    r'C:\Windows\Fonts\arialbd.ttf',
    r'C:\Windows\Fonts\arial.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]

CN_DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
CN_OPS = {'+': '加', '-': '减', '×': '乘', '÷': '除'}


_font_cache = {}


def _load_font(size):
    """加载字体并缓存，避免每次生成验证码都读盘"""
    if size in _font_cache:
        return _font_cache[size]
    font = None
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _make_expression():
    """生成中文算术表达式与答案：运算符与数字均为中文，数字均为一位数"""
    op = random.choice(['+', '-', '×', '÷'])
    if op == '+':
        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
    elif op == '-':
        a = random.randint(1, 9)
        b = random.randint(1, a)
        answer = a - b
    elif op == '×':
        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a * b
    else:
        # 保证整除且操作数均为一位数
        a, b = random.choice([(4, 2), (6, 2), (8, 2), (6, 3), (9, 3), (8, 4)])
        answer = a // b
    # 运算符前面的数字用阿拉伯数字，后面的数字用中文
    text = '%d %s %s = ?' % (a, CN_OPS[op], CN_DIGITS[b])
    return text, answer


def _cleanup():
    now = time.time()
    expired = [k for k, v in _store.items() if v['expires'] < now]
    for k in expired:
        _store.pop(k, None)


def create_captcha():
    """创建验证码，返回 (key, text, answer)"""
    text, answer = _make_expression()
    key = uuid.uuid4().hex
    with _lock:
        _cleanup()
        _store[key] = {'text': text, 'answer': answer, 'expires': time.time() + TTL}
    return key, text, answer


def verify_captcha(key, value):
    """校验验证码（一次性，校验后立即失效）"""
    if not key or value is None or str(value).strip() == '':
        return False
    with _lock:
        _cleanup()
        item = _store.pop(key, None)
    if not item:
        return False
    if item['expires'] < time.time():
        return False
    try:
        return int(str(value).strip()) == int(item['answer'])
    except (TypeError, ValueError):
        return False


def get_captcha_text(key):
    with _lock:
        item = _store.get(key)
    return item['text'] if item else None


def render_png(text, width=152, height=44):
    """把表达式渲染成 PNG 字节"""
    image = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # 背景噪点
    for _ in range(random.randint(120, 200)):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=(random.randint(150, 220),
                                 random.randint(150, 220),
                                 random.randint(150, 220)))

    # 干扰线
    for _ in range(random.randint(3, 5)):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)),
            width=1
        )

    font = _load_font(24)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2 - bbox[0], (height - th) / 2 - bbox[1]),
              text, font=font, fill=(200, 1, 14))

    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def captcha_data_uri(key):
    text = get_captcha_text(key)
    if text is None:
        return ''
    return 'data:image/png;base64,' + base64.b64encode(render_png(text)).decode('ascii')
