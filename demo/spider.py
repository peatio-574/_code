# -*- coding: utf-8 -*-
"""
使用newPlayWright爬取动态页面 + AI提取标题和正文（保留格式）
支持断点续爬：已有正常标题和正文的跳过
边处理边写入test.csv文件（每处理一条立即写入）
使用方法: python spider.py
"""

import sys
import os
import csv
import re
import time
import random
import json
import shutil
from datetime import datetime
from urllib.parse import urlparse

# 导入newPlayWright
from newPlayWright import PlayWrightClass, SpecialPlayWright

# 设置CSV字段大小限制
csv.field_size_limit(50 * 1024 * 1024)


class DynamicPageCrawler:
    """使用newPlayWright爬取动态页面 + AI提取标题和正文（保留格式）"""

    def __init__(self, input_file, output_file=None, use_special=False, proxy=None, api_key=None, delay=10):
        self.input_file = input_file
        self.output_file = output_file or input_file
        self.use_special = use_special
        self.proxy = proxy
        self.api_key = api_key
        self.delay = delay

        self.PlayWright = None
        self.total = 0
        self.success_count = 0
        self.fail_count = 0
        self.skipped_count = 0
        self.already_done_count = 0

        # 列索引
        self.title_idx = -1
        self.content_idx = -1
        self.error_idx = -1
        self.url_idx = 8  # learnMore列在第9列（索引8）

        # 临时文件
        self.temp_file = self.input_file + ".tmp"

    def _is_pdf_link(self, url):
        """判断是否为PDF链接"""
        if not url:
            return True
        url_lower = url.lower()
        if url_lower.endswith('.pdf') or '.pdf?' in url_lower or '.pdf#' in url_lower:
            return True
        parsed = urlparse(url)
        if parsed.path.lower().endswith('.pdf'):
            return True
        return False

    def _has_valid_content(self, row):
        """检查行是否已有有效的标题和正文"""
        if self.title_idx < 0 or self.content_idx < 0 or self.error_idx < 0:
            return False, "", ""

        if self.title_idx >= len(row) or self.content_idx >= len(row):
            return False, "", ""

        title = row[self.title_idx].strip() if row[self.title_idx] else ""
        content = row[self.content_idx].strip() if row[self.content_idx] else ""
        error_reason = row[self.error_idx].strip() if len(row) > self.error_idx else ""

        has_valid = (
                title and
                title != "无标题" and
                content and
                content != "NA" and
                content != "无正文内容" and
                len(content) > 50 and
                error_reason == "SUCCESS"
        )

        return has_valid, title, content

    def _check_page_has_content(self):
        """检查页面是否有实质内容"""
        try:
            body_text = self.PlayWright.page.evaluate("document.body ? document.body.innerText : ''")
            body_length = len(body_text.strip()) if body_text else 0
            print(f"  页面正文长度: {body_length}")

            if body_length < 100:
                return False, body_length
            return True, body_length
        except Exception as e:
            print(f"  检查页面内容时异常: {e}")
            return False, 0

    def _check_error_page(self):
        """检测是否为错误页面"""
        try:
            title = self.PlayWright.page.evaluate("document.title || ''")
            title_lower = title.lower()

            error_keywords = ['404', '403', '500', 'not found', 'forbidden', 'access denied',
                              'page not found', 'error', 'server error']
            for keyword in error_keywords:
                if keyword in title_lower:
                    return True, f"页面标题包含{keyword.upper()}"

            body_text = self.PlayWright.page.evaluate("document.body ? document.body.innerText : ''")
            if len(body_text) < 2000:
                body_lower = body_text.lower()
                for keyword in error_keywords:
                    if keyword in body_lower:
                        return True, f"页面内容包含{keyword.upper()}"

            return False, None

        except Exception as e:
            print(f"  检测错误页面时异常: {e}")
            return False, None

    def _check_pdf_content_page(self):
        """检测页面是否为PDF内容形式"""
        try:
            has_content, body_length = self._check_page_has_content()
            if not has_content:
                return False, "页面无内容"

            # 检查页面标题
            title = self.PlayWright.page.evaluate("document.title || ''")
            title_lower = title.lower()
            pdf_title_keywords = ['pdf', 'adobe acrobat', 'adobe reader', 'pdf viewer', 'pdf document']
            for keyword in pdf_title_keywords:
                if keyword in title_lower:
                    return True, f"页面标题包含'{keyword}'"

            # 检查HTML中的PDF查看器
            html_content = self.PlayWright.page.content()
            html_lower = html_content.lower()

            pdf_html_keywords = [
                'pdf-viewer', 'pdfviewer',
                'application/pdf', 'pdf.js',
                'pdf-embed', 'pdf_embed',
                'class="pdf"', 'id="pdf"'
            ]

            for keyword in pdf_html_keywords:
                if keyword in html_lower:
                    return True, f"HTML包含PDF查看器关键词'{keyword}'"

            # 检查iframe/embed指向PDF
            iframe_check = self.PlayWright.page.evaluate("""
                () => {
                    const iframes = document.querySelectorAll('iframe, embed, object');
                    for (let el of iframes) {
                        const src = el.src || el.data || '';
                        if (src && src.toLowerCase().includes('.pdf')) {
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if iframe_check:
                return True, "页面包含指向PDF的iframe/embed标签"

            return False, None

        except Exception as e:
            print(f"  检测PDF内容页面时异常: {e}")
            return False, None

    def _get_page_html(self):
        """获取完整的页面HTML"""
        try:
            return self.PlayWright.page.content()
        except Exception as e:
            print(f"  获取HTML失败: {e}")
            return ""

    def _extract_with_ai(self, html_content, url):
        """调用DeepSeek API判断页面类型并提取标题和正文"""
        if not self.api_key:
            print("  未配置API Key，使用备用提取方式")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True, False

        try:
            import requests

            # 清理HTML但保留结构标记
            text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

            text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</h1>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</h2>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</h3>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</h4>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<li>', '  • ', text, flags=re.IGNORECASE)
            text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</ul>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</ol>', '\n', text, flags=re.IGNORECASE)

            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-z]+;', ' ', text)
            text = re.sub(r'\n{4,}', '\n\n\n', text)
            text = text.strip()

            max_length = 25000
            if len(text) > max_length:
                text = text[:max_length] + "\n...(内容已截断)"

            if len(text) < 50:
                return "无标题", "无正文内容", "empty", False, False

            prompt = f"""
请分析以下网页内容，判断它是否为文章/新闻/官方文件页面，并提取标题和正文。

【第一步：判断页面类型】
1. "article" - 文章/新闻/官方文件页面（有明确的标题和正文内容）
2. "consultation" - 咨询/公告/通知页面
3. "directory" - 目录/列表页面
4. "pdf_content" - PDF内容页面
5. "other" - 其他类型

【判断规则】
- 有明确标题（h1或页面标题），正文有完整段落结构，长度超过500字符 → article
- 行政命令、联邦公报、政策文件 → article
- 包含"Consulta Pública"、"Edital"、"Notice"等关键词 → consultation
- 主要是列表/目录 → directory
- 没有实质内容，只有导航/Cookie/版权 → other

URL: {url}

页面内容：
{text}

请按以下JSON格式返回结果：
{{"page_type": "article/consultation/directory/pdf_content/other", "title": "标题", "content": "正文"}}
"""

            api_url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system",
                     "content": "你是一个专业的网页分析助手。请准确判断页面类型，如果是文章页面则提取标题和正文保留格式。请始终以JSON格式返回结果。"},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "max_tokens": 4000,
                "temperature": 0.1
            }

            print("  调用AI分析页面类型并提取内容...")
            proxies = None
            if self.proxy:
                proxy_server = self.proxy.get('server', '')
                proxies = {'http': proxy_server, 'https': proxy_server}

            response = requests.post(api_url, headers=headers, json=data, proxies=proxies, timeout=90)

            if response.status_code == 200:
                result = response.json()
                response_text = result['choices'][0]['message']['content'].strip()

                try:
                    json_match = re.search(r'\{[^{}]*"page_type"[^{}]*"title"[^{}]*"content"[^{}]*\}', response_text,
                                           re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                    else:
                        parsed = json.loads(response_text)

                    page_type = parsed.get('page_type', 'other').strip().lower()
                    title = parsed.get('title', '').strip()
                    content = parsed.get('content', '').strip()

                    if title == "无标题":
                        title = ""
                    if content == "无正文内容":
                        content = ""

                    if content:
                        content = re.sub(r'\n{4,}', '\n\n\n', content)

                    is_article = (page_type == 'article')
                    is_pdf = (page_type == 'pdf_content')
                    print(f"  页面类型: {page_type}, 是否文章: {is_article}, 是否PDF内容: {is_pdf}")

                    return title, content, page_type, is_article, is_pdf

                except json.JSONDecodeError:
                    print("  JSON解析失败，尝试正则提取...")
                    type_match = re.search(r'"page_type"\s*:\s*"([^"]*)"', response_text)
                    title_match = re.search(r'"title"\s*:\s*"([^"]*)"', response_text)
                    content_match = re.search(r'"content"\s*:\s*"([^"]*)"', response_text)

                    page_type = type_match.group(1) if type_match else 'other'
                    title = title_match.group(1) if title_match else ""
                    content = content_match.group(1) if content_match else ""

                    if title == "无标题":
                        title = ""
                    if content == "无正文内容":
                        content = ""

                    is_article = (page_type == 'article')
                    is_pdf = (page_type == 'pdf_content')
                    return title, content, page_type, is_article, is_pdf

            else:
                print(f"  API调用失败: {response.status_code}")
                title, content = self._extract_fallback(html_content)
                return title, content, "unknown", True, False

        except ImportError:
            print("  未安装requests库，使用备用提取方式")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True, False
        except Exception as e:
            print(f"  AI提取失败: {e}")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True, False

    def _extract_fallback(self, html_content):
        """备用提取方式"""
        try:
            text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<li>', '  • ', text, flags=re.IGNORECASE)
            text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-z]+;', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()

            title = ""
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.DOTALL | re.IGNORECASE)
            if title_match:
                title = re.sub(r'\s+', ' ', title_match.group(1)).strip()

            if not title:
                h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html_content, re.DOTALL | re.IGNORECASE)
                if h1_match:
                    title = re.sub(r'<[^>]+>', ' ', h1_match.group(1)).strip()

            return title, text

        except Exception as e:
            print(f"  备用提取失败: {e}")
            return "", ""

    def process_url(self, url):
        """处理单个URL，返回(title, content, error_reason)"""
        if not url or not url.strip():
            return "无标题", "NA", "URL为空"

        url = url.strip()

        if self._is_pdf_link(url):
            return "无标题", "NA", "PDF链接，跳过爬取"

        try:
            print(f"  访问页面...")
            success = self.PlayWright.goto(url, timeout=30 * 1000, proxy=self.proxy)

            if not success:
                return "无标题", "NA", "页面加载失败"

            print("  页面响应成功")

            # 等待2秒让页面基本渲染
            time.sleep(2)

            # 先检测错误页面
            is_error, error_reason = self._check_error_page()
            if is_error:
                return "无标题", "NA", error_reason

            # 检查页面是否有内容
            has_content, body_length = self._check_page_has_content()
            if not has_content:
                print(f"  页面无实质内容(长度:{body_length})，跳过后续处理")
                return "无标题", "无正文内容", "页面无正文内容(内容过短)"

            # 检测PDF内容页面
            is_pdf_content, pdf_reason = self._check_pdf_content_page()
            if is_pdf_content:
                print(f"  检测到PDF内容页面: {pdf_reason}")
                return "无标题", "NA", "PDF内容页面"

            html_content = self._get_page_html()
            if not html_content or len(html_content) < 500:
                return "无标题", "无正文内容", "页面HTML内容过短"

            print(f"  HTML长度: {len(html_content)}")

            title, content, page_type, is_article, is_pdf = self._extract_with_ai(html_content, url)

            if is_pdf:
                print(f"  AI识别为PDF内容页面，跳过")
                return "无标题", "NA", "PDF内容页面"

            if not is_article:
                print(f"  页面类型为'{page_type}'，非文章页面，跳过")
                return "无标题", "无正文内容", f"非文章页面(类型:{page_type})"

            if not title:
                title = "无标题"

            print(f"  最终标题: {title[:50] if title else '无'}")
            print(f"  最终内容长度: {len(content) if content else 0}")

            if not content or len(content) < 50:
                return title, "无正文内容", "正文内容过短"

            if len(content) > 50000:
                content = content[:50000] + "...(内容过长，已截断)"

            return title, content, "SUCCESS"

        except Exception as e:
            error_msg = str(e)
            if 'timeout' in error_msg.lower():
                return "无标题", "NA", "访问超时"
            elif 'net::' in error_msg:
                return "无标题", "NA", f"网络错误: {error_msg[:50]}"
            else:
                return "无标题", "NA", f"访问异常: {error_msg[:100]}"

    def _wait_between_requests(self, idx, total, should_wait=True):
        if idx >= total:
            return
        if not should_wait:
            print("  ⏭ 跳过等待（非成功页面）")
            return
        print(f"\n⏳ 等待 {self.delay} 秒后继续下一条...")

        for remaining in range(self.delay, 0, -1):
            print(f"\r⏳ 等待 {remaining} 秒后继续...", end="")
            time.sleep(1)
        print("\r" + " " * 40 + "\r", end="")

    def _flush_rows_to_file(self, rows):
        """将所有行写入文件（在中断或完成时调用）"""
        try:
            with open(self.temp_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.input_headers)
                writer.writerows(rows)
            return True
        except Exception as e:
            print(f"  写入文件失败: {e}")
            return False

    def process_csv(self):
        """处理CSV文件（边处理边写入，每处理一条立即保存）"""
        print("=" * 70)
        print("动态页面爬虫 (newPlayWright + AI 判断页面类型并提取)")
        print("=" * 70)
        print(f"输入文件: {self.input_file}")
        print(f"输出文件: {self.output_file} (边处理边写入)")
        if self.proxy:
            print(f"代理配置: {self.proxy.get('server', '无')}")
        if self.api_key:
            print("AI提取: 已启用 (DeepSeek API)")
            print("  - AI判断页面类型(article/consultation/directory/pdf_content/other)")
            print("  - PDF内容页面自动跳过")
            print("  - 仅文章页面提取标题和正文")
            print("  - 正文保留格式（段落、列表、层次结构）")
            print("  - 已有有效标题和正文的记录自动跳过（断点续爬）")
            print("  - 每处理一条立即写入文件")
        else:
            print("AI提取: 未启用 (使用备用提取方式)")
        print(f"请求间隔: {self.delay} 秒（仅成功时等待）")
        print("=" * 70)

        # 检查文件是否存在
        file_exists = os.path.exists(self.input_file)

        if not file_exists:
            print("文件不存在，将创建新文件并写入表头")
            headers = [
                'title', 'description', 'status', 'year', 'jurisdiction',
                'source', 'datePromulgated', 'yearEnded', 'learnMore',
                'learnMoreLanguage', 'dateModified', 'countries', 'states',
                'technologies', 'tags', 'policyType'
            ]
            with open(self.input_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            print("已创建新文件并写入表头")
            self.input_headers = headers
            rows = []
        else:
            # 读取所有数据
            try:
                with open(self.input_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    self.input_headers = next(reader)
                    rows = list(reader)
                print(f"已读取现有文件，共 {len(rows)} 条记录")
            except Exception as e:
                print(f"读取现有文件失败: {e}")
                return False

        # 检查新增列是否存在
        self.has_title_col = 'title' in self.input_headers
        self.has_content_col = 'content' in self.input_headers
        self.has_error_col = 'error_reason' in self.input_headers

        # 确定索引
        self.title_idx = self.input_headers.index('title') if self.has_title_col else -1
        self.content_idx = self.input_headers.index('content') if self.has_content_col else -1
        self.error_idx = self.input_headers.index('error_reason') if self.has_error_col else -1

        # 如果新增列不存在，需要添加表头
        need_add_columns = not self.has_title_col or not self.has_content_col or not self.has_error_col

        if need_add_columns:
            print("检测到新增列不存在，正在添加表头...")

            # 构建新表头
            new_headers = self.input_headers.copy()
            if not self.has_title_col:
                self.title_idx = len(new_headers)
                new_headers.append('title')
            if not self.has_content_col:
                self.content_idx = len(new_headers)
                new_headers.append('content')
            if not self.has_error_col:
                self.error_idx = len(new_headers)
                new_headers.append('error_reason')

            # 更新现有行，添加空列
            new_rows = []
            for row in rows:
                while len(row) < len(new_headers):
                    row.append('')
                new_rows.append(row)

            # 更新表头和行
            self.input_headers = new_headers
            rows = new_rows
            self.has_title_col = True
            self.has_content_col = True
            self.has_error_col = True
            print("表头添加完成")

            # 立即写入更新后的表头
            self._flush_rows_to_file(rows)

        # 构建需要处理的记录列表
        pending_items = []  # 存储 (原始行索引, row)
        for idx, row in enumerate(rows):
            # 确保行有足够的列
            while len(row) < len(self.input_headers):
                row.append('')

            # 获取URL
            url = row[self.url_idx] if len(row) > self.url_idx else ''

            # 检查是否已有有效数据
            if url and url.strip():
                has_valid, _, _ = self._has_valid_content(row)
                if has_valid:
                    self.already_done_count += 1
                    continue

            pending_items.append((idx, row))

        self.total = len(rows)  # 总行数（包含已跳过的）
        pending_total = len(pending_items)
        print(f"\n共有 {self.total} 条记录，其中 {self.already_done_count} 条已有有效数据跳过")
        print(f"需要处理 {pending_total} 条记录\n")

        if pending_total == 0:
            print("所有记录已处理完成，无需操作")
            return True

        # 启动浏览器
        try:
            if self.use_special:
                self.PlayWright = SpecialPlayWright()
                print("使用SpecialPlayWright（指纹浏览器）")
            else:
                self.PlayWright = PlayWrightClass()
                print("使用普通PlayWright浏览器")

            self.PlayWright.start_borwser(proxy=self.proxy)
            print("浏览器启动成功\n")

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        try:
            for idx_in_pending, (row_idx, row) in enumerate(pending_items, 1):
                # 确保行有足够的列
                while len(row) < len(self.input_headers):
                    row.append('')

                # 获取URL
                url = row[self.url_idx] if len(row) > self.url_idx else ''

                # 打印实际行号（从1开始）
                actual_row_num = row_idx + 1
                print(
                    f"\n[{actual_row_num}/{self.total}] 处理URL: {url[:80]}..." if url else f"[{actual_row_num}/{self.total}] URL为空")
                print("-" * 60)

                if not url or not url.strip():
                    # URL为空
                    while len(row) < len(self.input_headers):
                        row.append('')
                    row[self.title_idx] = '无标题'
                    row[self.content_idx] = 'NA'
                    row[self.error_idx] = 'URL为空'
                    self.fail_count += 1

                    # 立即写入文件
                    self._flush_rows_to_file(rows)
                    print(f"  ⚠ URL为空，已保存")

                    self._wait_between_requests(idx_in_pending, pending_total, should_wait=False)
                    continue

                # 处理URL
                title, content, error_reason = self.process_url(url)

                # 确保行有足够的列
                while len(row) < len(self.input_headers):
                    row.append('')

                # 填充数据到对应行
                row[self.title_idx] = title
                row[self.content_idx] = content
                row[self.error_idx] = error_reason

                # 立即写入文件
                self._flush_rows_to_file(rows)

                # 打印结果
                if error_reason == "SUCCESS":
                    self.success_count += 1
                    print(f"  ✓ 成功 (标题: {title[:50] if title else '无'}, 内容: {len(content)} 字符)")
                    print(f"  📝 已保存")
                    preview = content[:200].replace('\n', ' ')
                    print(f"  预览: {preview}...")
                elif "PDF" in error_reason:
                    self.skipped_count += 1
                    print(f"  ⏭ 跳过 (PDF) - 已保存")
                elif "非文章页面" in error_reason:
                    self.fail_count += 1
                    print(f"  ⚠ {error_reason} - 已保存")
                elif "无正文内容" in error_reason:
                    self.fail_count += 1
                    print(f"  ⚠ {error_reason} - 已保存")
                elif "403" in error_reason or "404" in error_reason or "错误页面" in error_reason:
                    self.fail_count += 1
                    print(f"  ⚠ 错误页面: {error_reason} - 已保存")
                else:
                    self.fail_count += 1
                    print(f"  ✗ 失败: {error_reason} - 已保存")

                should_wait = (error_reason == "SUCCESS")
                self._wait_between_requests(idx_in_pending, pending_total, should_wait=should_wait)

        except KeyboardInterrupt:
            print("\n\n用户中断，正在保存已处理的数据...")
            self._flush_rows_to_file(rows)
            print("数据已保存")
        except Exception as e:
            print(f"处理过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            self._flush_rows_to_file(rows)
            print("已保存已处理的数据")
        finally:
            try:
                self.PlayWright.close()
                print("浏览器已关闭")
            except:
                pass

        # 最终保存
        self._flush_rows_to_file(rows)

        # 用临时文件替换原文件
        try:
            if os.path.exists(self.temp_file):
                shutil.move(self.temp_file, self.input_file)
                print(f"\n数据已保存到: {self.input_file}")
        except Exception as e:
            print(f"保存文件失败: {e}")
            return False

        print("\n" + "=" * 60)
        print(f"处理完成!")
        print(f"总记录数: {self.total}")
        print(f"已有数据跳过: {self.already_done_count}")
        print(f"本次处理: {pending_total}")
        print(f"  - 成功爬取: {self.success_count}")
        print(f"  - 跳过(PDF): {self.skipped_count}")
        print(f"  - 失败数量: {self.fail_count}")
        if pending_total > 0:
            print(f"  有效率: {(self.success_count + self.skipped_count) / pending_total * 100:.1f}%")
        print(f"结果已保存到: {self.input_file}")
        print("=" * 60)

        return True


def main():
    input_file = "./test.csv"
    output_file = None

    use_special = False

    proxy = {
        'server': 'http://127.0.0.1:7892'
    }

    # 统一API Key
    API_KEY = "sk-c05a4aede23648a59a57990db317389c"

    DELAY_SECONDS = 10

    crawler = DynamicPageCrawler(
        input_file=input_file,
        output_file=output_file,
        use_special=use_special,
        proxy=proxy,
        api_key=API_KEY,
        delay=DELAY_SECONDS
    )

    success = crawler.process_csv()

    if success:
        print("处理完成！")
    else:
        print("处理失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()