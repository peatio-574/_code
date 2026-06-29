#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析 vt.tiktok.com 短链，并输出：
1. 原始最终链接 final_url
2. H5 清洗链接 h5_clean_url: https://www.tiktok.com/view/product/{product_id}
3. PC/PDP 候选链接 desktop_url: https://www.tiktok.com/shop/pdp/x/{product_id}
4. 带标题 slug 的 SEO/PDP 候选链接 seo_desktop_url

依赖：pip install requests
用法：python resolve_tiktok_desktop_link.py "https://vt.tiktok.com/ZS96JJBamJm3g-CoTlG/"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

import requests

REDIRECT_STATUS = {301, 302, 303, 307, 308}


class ResolveError(RuntimeError):
    pass


@dataclass
class ResolveResult:
    input_url: str
    final_url: str
    link_type: str
    h5_clean_url: Optional[str]
    desktop_url: Optional[str]
    seo_desktop_url: Optional[str]
    product_id: Optional[str]
    video_id: Optional[str]
    unique_id: Optional[str]
    user_id: Optional[str]
    title: Optional[str]
    image: Optional[str]
    redirect_chain: List[str]


def normalize_input_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("url 不能为空")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def slugify_title(title: str, max_len: int = 100) -> str:
    """把商品标题转成 TikTok PDP URL 里常见的英文 slug。"""
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "x"
    return text[:max_len].strip("-") or "x"


def build_desktop_product_urls(product_id: str, title: Optional[str] = None) -> Dict[str, str]:
    # 稳定候选：很多 TikTok Shop 抓取器/搜索结果都接受 /shop/pdp/x/{product_id}
    desktop_url = f"https://www.tiktok.com/shop/pdp/x/{product_id}"

    # 更像真实 SEO 页面的候选：/shop/pdp/{slug}/{product_id}
    slug = slugify_title(title) if title else "x"
    seo_desktop_url = f"https://www.tiktok.com/shop/pdp/{slug}/{product_id}"

    return {
        "desktop_url": desktop_url,
        "seo_desktop_url": seo_desktop_url,
    }


def parse_og_info(query: Dict[str, List[str]]) -> Dict[str, Optional[str]]:
    raw = query.get("og_info", [None])[0]
    if not raw:
        return {"title": None, "image": None}
    try:
        obj = json.loads(unquote(raw))
        return {"title": obj.get("title"), "image": obj.get("image")}
    except Exception:
        return {"title": None, "image": None}


def analyze_tiktok_url(url: str) -> Dict[str, Optional[str]]:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    # 视频：/@username/video/video_id
    video_match = re.search(r"/@([^/]+)/video/(\d+)", path)
    if video_match:
        username = video_match.group(1)
        video_id = video_match.group(2)
        h5_clean_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        return {
            "link_type": "video",
            "h5_clean_url": h5_clean_url,
            "desktop_url": h5_clean_url,
            "seo_desktop_url": h5_clean_url,
            "video_id": video_id,
            "product_id": None,
            "unique_id": username,
            "user_id": query.get("user_id", [None])[0],
            "title": None,
            "image": None,
        }

    # H5 商品页：/view/product/product_id
    product_match = re.search(r"/view/product/(\d+)", path)
    if product_match:
        product_id = product_match.group(1)
        h5_clean_url = f"https://www.tiktok.com/view/product/{product_id}"
        og = parse_og_info(query)
        title = og.get("title")
        desktop_urls = build_desktop_product_urls(product_id, title)
        return {
            "link_type": "product",
            "h5_clean_url": h5_clean_url,
            "desktop_url": desktop_urls["desktop_url"],
            "seo_desktop_url": desktop_urls["seo_desktop_url"],
            "video_id": None,
            "product_id": product_id,
            "unique_id": query.get("unique_id", [None])[0],
            "user_id": query.get("user_id", [None])[0],
            "title": title,
            "image": og.get("image"),
        }

    # 已经是 PDP 商品页：/shop/pdp/.../product_id
    pdp_match = re.search(r"/shop/pdp/(?:.+/)?(\d+)$", path)
    if pdp_match:
        product_id = pdp_match.group(1)
        desktop_urls = build_desktop_product_urls(product_id)
        return {
            "link_type": "product",
            "h5_clean_url": f"https://www.tiktok.com/view/product/{product_id}",
            "desktop_url": desktop_urls["desktop_url"],
            "seo_desktop_url": urlunparse(("https", "www.tiktok.com", path, "", "", "")),
            "video_id": None,
            "product_id": product_id,
            "unique_id": query.get("unique_id", [None])[0],
            "user_id": query.get("user_id", [None])[0],
            "title": None,
            "image": None,
        }

    return {
        "link_type": "unknown",
        "h5_clean_url": None,
        "desktop_url": None,
        "seo_desktop_url": None,
        "video_id": None,
        "product_id": None,
        "unique_id": query.get("unique_id", [None])[0],
        "user_id": query.get("user_id", [None])[0],
        "title": None,
        "image": None,
    }


def resolve_tiktok_link(short_url: str, *, timeout: int = 20, max_redirects: int = 10, proxies: Optional[dict] = None) -> ResolveResult:
    url = normalize_input_url(short_url)
    input_url = url
    chain = [url]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Connection": "close",
    })

    for _ in range(max_redirects):
        try:
            resp = session.get(url, allow_redirects=False, timeout=timeout, proxies=proxies)
        except requests.RequestException as e:
            raise ResolveError(f"请求失败：{e}") from e

        if resp.status_code in REDIRECT_STATUS:
            location = resp.headers.get("Location")
            if not location:
                raise ResolveError(f"状态码 {resp.status_code} 但没有 Location 响应头")
            url = urljoin(url, location)
            chain.append(url)
            info = analyze_tiktok_url(url)
            if info["link_type"] in {"video", "product"}:
                return ResolveResult(input_url, url, info["link_type"], info["h5_clean_url"], info["desktop_url"], info["seo_desktop_url"], info["product_id"], info["video_id"], info["unique_id"], info["user_id"], info["title"], info["image"], chain)
            continue

        final_url = resp.url
        info = analyze_tiktok_url(final_url)
        return ResolveResult(input_url, final_url, info["link_type"], info["h5_clean_url"], info["desktop_url"], info["seo_desktop_url"], info["product_id"], info["video_id"], info["unique_id"], info["user_id"], info["title"], info["image"], chain)

    raise ResolveError(f"超过最大跳转次数：{max_redirects}")


def main() -> None:
    # parser = argparse.ArgumentParser(description="解析 TikTok 短链，并生成 PC/PDP 商品链接候选")
    # parser.add_argument("url")
    # parser.add_argument("--timeout", type=int, default=20)
    # parser.add_argument("--max-redirects", type=int, default=10)
    # parser.add_argument("--proxy", default=None, help="例如 http://127.0.0.1:7890")
    # args = parser.parse_args()
    #
    # proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    proxies = {
        "http": "http://127.0.0.1:7892",
        "https": "http://127.0.0.1:7892",
    }
    try:
        result = resolve_tiktok_link("https://vt.tiktok.com/ZS968TeqFXnxm-3oBwh", proxies=proxies)
        # result = resolve_tiktok_link(args.url, timeout=args.timeout, max_redirects=args.max_redirects, proxies=proxies)
    except Exception as e:
        print(f"解析失败：{e}", file=sys.stderr)
        sys.exit(1)

    print("输入短链:", result.input_url)
    print("链接类型:", result.link_type)
    print("最终链接:", result.final_url)
    print("H5清洗链接:", result.h5_clean_url or "无")
    print("PC/PDP候选链接:", result.desktop_url or "无")
    print("SEO/PDP候选链接:", result.seo_desktop_url or "无")
    if result.product_id:
        print("product_id:", result.product_id)
    if result.video_id:
        print("video_id:", result.video_id)
    if result.unique_id:
        print("unique_id:", result.unique_id)
    if result.user_id:
        print("user_id:", result.user_id)
    if result.title:
        print("商品标题:", result.title)
    if result.image:
        print("商品图片:", result.image)
    print("跳转链:")
    for i, item in enumerate(result.redirect_chain):
        print(f"  {i}. {item}")


if __name__ == "__main__":
    main()
