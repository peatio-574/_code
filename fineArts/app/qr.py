# -*- coding: utf-8 -*-
"""证书二维码生成。

生成带「中间 logo + 底部链接文字」的二维码 PNG（参照 mskj.caa.edu.cn 样式）。
使用高纠错等级 H，保证中心叠加 logo 后仍可被正常扫描。
"""
import io
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H

# 备选字体（Linux 生产 / Windows 本地），均未命中时回退 Pillow 默认位图字体
FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/google-noto/NotoSans-Regular.ttf',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc',
    'C:/Windows/Fonts/arial.ttf',
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simsun.ttc',
]


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _paste_logo(qr_img, logo_path, logo_ratio):
    """把 logo 贴到二维码正中央，下面垫一块白色圆角底，避免遮挡定位点。"""
    if not logo_path or not os.path.exists(logo_path):
        return
    try:
        width, height = qr_img.size
        target = max(8, int(min(width, height) * logo_ratio))
        logo = Image.open(logo_path).convert('RGBA')
        logo = logo.resize((target, target), Image.LANCZOS)

        pad = max(2, target // 8)
        bg_size = (target + pad * 2, target + pad * 2)
        bg = Image.new('RGBA', bg_size, (255, 255, 255, 255))
        mask = Image.new('L', bg_size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, bg_size[0] - 1, bg_size[1] - 1], radius=pad, fill=255)

        bg_pos = ((width - bg_size[0]) // 2, (height - bg_size[1]) // 2)
        qr_img.paste(bg, bg_pos, mask)
        qr_img.paste(logo, ((width - target) // 2, (height - target) // 2), logo)
    except Exception:
        # logo 处理失败不影响二维码主体
        pass


def generate_qr_png(url, logo_path=None, caption=None, box_size=10, border=3,
                    logo_ratio=0.12, caption_color=(110, 110, 110)):
    """生成二维码 PNG，返回 BytesIO。

    url      : 扫码后跳转的地址（写入二维码内容）
    logo_path: 中心 logo 图片路径，可为 None
    caption  : 二维码下方文字（如官网链接），可为 None
    """
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')

    _paste_logo(qr_img, logo_path, logo_ratio)

    if not caption:
        buf = io.BytesIO()
        qr_img.save(buf, format='PNG')
        buf.seek(0)
        return buf

    width, height = qr_img.size
    # 底部链接文案：尽量占满宽度（自动收缩以避免超出）
    margin = max(4, width // 60)
    size = max(24, width // 11)
    font = _load_font(size)
    probe = ImageDraw.Draw(qr_img)
    bbox = probe.textbbox((0, 0), caption, font=font)
    while bbox[2] - bbox[0] > width - 2 * margin and size > 12:
        size -= 2
        font = _load_font(size)
        bbox = probe.textbbox((0, 0), caption, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    gap = max(10, height // 40)

    canvas = Image.new('RGB', (width, height + text_h + gap * 2), 'white')
    canvas.paste(qr_img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(((width - text_w) // 2 - bbox[0], height + gap - bbox[1]),
              caption, fill=caption_color, font=font)

    buf = io.BytesIO()
    canvas.save(buf, format='PNG')
    buf.seek(0)
    return buf
