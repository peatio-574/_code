# -*- coding: utf-8 -*-
"""图片验证码：简单的加减乘除算术题"""
import base64
import hashlib
import hmac
import io
import json
import os
import random
import time

from PIL import Image, ImageDraw, ImageFont

try:
    from flask import current_app
except Exception:  # 允许脱离 Flask 环境单独测试
    current_app = None

TTL = 300          # 验证码有效期（秒）
_SIG_LEN = 12      # 签名长度（base64url 12 字符）

# 项目内置字体目录（推荐把中文字体放这里，部署与发行版无关）
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLED_FONT_DIR = os.path.join(_BASE_DIR, 'static', 'fonts')

_FONT_CANDIDATES = [
    # 1) 项目内置（优先级最高，服务器上放一个中文字体即可）
    os.path.join(_BUNDLED_FONT_DIR, 'wqy-zenhei.ttc'),
    os.path.join(_BUNDLED_FONT_DIR, 'wqy-microhei.ttc'),
    os.path.join(_BUNDLED_FONT_DIR, 'NotoSansCJKsc-Regular.otf'),
    os.path.join(_BUNDLED_FONT_DIR, 'NotoSansSC-Regular.otf'),
    os.path.join(_BUNDLED_FONT_DIR, 'SourceHanSansCN-Regular.otf'),
    os.path.join(_BUNDLED_FONT_DIR, 'msyhbd.ttc'),
    # 2) Linux 系统常见中文字体
    '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    # 3) Windows 字体
    r'C:\Windows\Fonts\msyhbd.ttc',      # 微软雅黑（支持中文）
    r'C:\Windows\Fonts\simhei.ttf',      # 黑体
    r'C:\Windows\Fonts\simsun.ttc',      # 宋体
    r'C:\Windows\Fonts\arialbd.ttf',
    r'C:\Windows\Fonts\arial.ttf',
    # 4) 兜底（不支持中文，仅避免崩溃）
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]

_font_cache = {}
_cjk_font_path = None            # 解析出的“支持中文”的字体路径（缓存）
_cjk_font_scanned = False        # 是否已扫描过

# 自动扫描字体的目录（系统里若已有中文字体，会被自动采用，无需配置）
_FONT_SEARCH_DIRS = [
    _BUNDLED_FONT_DIR,
    '/usr/share/fonts',
    '/usr/local/share/fonts',
    '~/.fonts',
    '~/.local/share/fonts',
    r'C:\Windows\Fonts',
]

_GLYPH_PROBE = ('一', '二', '加', '五', '证')


def _font_supports_cjk(font):
    """粗略判断字体是否包含中文字形（用几个常见字探测）"""
    try:
        for ch in _GLYPH_PROBE:
            mask = font.getmask(ch)
            if mask.getbbox() is None:   # 空掩码 = 没有该字形
                return False
        return True
    except Exception:
        return False


def _resolve_cjk_font_path():
    """返回一个支持中文的字体路径：先看内置/常见候选，再扫描系统字体目录。"""
    global _cjk_font_path, _cjk_font_scanned
    if _cjk_font_scanned:
        return _cjk_font_path
    # 1) 已知候选路径优先
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                if _font_supports_cjk(ImageFont.truetype(path, 24)):
                    _cjk_font_path = path
                    _cjk_font_scanned = True
                    return path
            except Exception:
                continue
    # 2) 扫描字体目录，找任意一个支持中文的字体
    for d in _FONT_SEARCH_DIRS:
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for name in files:
                if not name.lower().endswith(('.ttf', '.ttc', '.otf')):
                    continue
                p = os.path.join(root, name)
                try:
                    if _font_supports_cjk(ImageFont.truetype(p, 24)):
                        _cjk_font_path = p
                        _cjk_font_scanned = True
                        return p
                except Exception:
                    continue
    _cjk_font_scanned = True
    _cjk_font_path = None
    return None


def _load_font(size):
    """加载字体并缓存，避免每次生成验证码都读盘"""
    if size in _font_cache:
        return _font_cache[size]
    font = None
    path = _resolve_cjk_font_path()
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        # 退回默认字体（不保证中文，但避免崩溃）
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _make_expression():
    """生成算术表达式与答案：全部为阿拉伯数字，如 “3 + 5 = ?”（一位数运算）"""
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
    text = '%d %s %d = ?' % (a, op, b)
    return text, answer


def _secret():
    """签名密钥：取应用 SECRET_KEY（无上下文时用固定兜底值，仅用于本地测试）"""
    try:
        return (current_app.config.get('SECRET_KEY') or 'captcha-secret').encode('utf-8')
    except Exception:
        return b'captcha-secret'


def _b64e(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64d(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sign(payload):
    digest = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return _b64e(digest)[:_SIG_LEN]


def _decode(key):
    """校验并解析 key；返回负载 dict 或 None（签名不符/过期）。"""
    try:
        if not key or len(key) <= _SIG_LEN:
            return None
        sig, payload = key[:_SIG_LEN], key[_SIG_LEN:]
        raw = _b64d(payload)
        if not hmac.compare_digest(sig, _sign(raw)):
            return None
        body = json.loads(raw.decode('utf-8'))
        if int(body.get('e', 0)) < time.time():
            return None
        return body
    except Exception:
        return None


def create_captcha():
    """创建验证码，返回 (key, text, answer)。
    key 为“签名 + base64(JSON)”的无状态令牌，答案编码在 key 内，
    因此多进程/多 worker 下也能正确校验（不依赖进程内存）。"""
    text, answer = _make_expression()
    body = {'t': text, 'a': answer, 'e': int(time.time()) + TTL,
            'n': os.urandom(6).hex()}
    raw = json.dumps(body, separators=(',', ':')).encode('utf-8')
    key = _sign(raw) + _b64e(raw)
    return key, text, answer


def verify_captcha(key, value):
    """校验验证码（无状态，带签名与过期时间）"""
    body = _decode(key)
    if not body:
        return False
    if value is None or str(value).strip() == '':
        return False
    try:
        return int(str(value).strip()) == int(body['a'])
    except (TypeError, ValueError):
        return False


def get_captcha_text(key):
    body = _decode(key)
    return body['t'] if body else None


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

    # 干扰线（随机颜色）
    for _ in range(random.randint(3, 5)):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)),
            width=1
        )

    # 文字：逐字符随机颜色（深色系，保证白底可读）
    font = _load_font(24)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) / 2 - bbox[0]
    y = (height - th) / 2 - bbox[1]
    for ch in text:
        draw.text((x, y), ch, font=font, fill=(random.randint(0, 130),
                                                random.randint(0, 130),
                                                random.randint(0, 130)))
        x += draw.textlength(ch, font=font)

    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def captcha_data_uri(key):
    text = get_captcha_text(key)
    if text is None:
        return ''
    return 'data:image/png;base64,' + base64.b64encode(render_png(text)).decode('ascii')
