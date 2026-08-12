# -*- coding: utf-8 -*-
"""
使用newPlayWright爬取动态页面 + AI提取标题和正文（保留格式）
流式写入，支持代理，每条间隔30秒（仅成功时等待）
使用方法: python spider.py
"""

import sys
import os
import csv
import re
import time
import random
import json
from datetime import datetime
from urllib.parse import urlparse

# 导入newPlayWright
from newPlayWright import PlayWrightClass, SpecialPlayWright

# 设置CSV字段大小限制
csv.field_size_limit(50 * 1024 * 1024)


class DynamicPageCrawler:
    """使用newPlayWright爬取动态页面 + AI提取标题和正文（保留格式）"""

    def __init__(self, input_file, output_file=None, use_special=False, proxy=None, api_key=None, delay=30):
        self.input_file = input_file
        self.output_file = output_file or self._generate_output_filename(input_file)
        self.use_special = use_special
        self.proxy = proxy
        self.api_key = api_key
        self.delay = delay

        self.browser = None
        self.total = 0
        self.success_count = 0
        self.fail_count = 0
        self.skipped_count = 0

        self.writer = None
        self.output_headers = None
        self.input_headers = None

    def _generate_output_filename(self, input_file):
        base, ext = os.path.splitext(input_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base}_result_{timestamp}{ext}"

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

    def _wait_for_news_content(self, timeout=20):
        """等待新闻正文内容加载"""
        print("  等待新闻内容加载...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = self.browser.page.evaluate("""
                    () => {
                        const selectors = [
                            'article p',
                            '.content p',
                            '.press-content p',
                            '.ec-content p',
                            'main p',
                            '.news-content p',
                            '.post-content p',
                            '.entry-content p',
                            '.article-content p',
                            '.body-content p'
                        ];
                        let maxLength = 0;
                        for (let sel of selectors) {
                            const elements = document.querySelectorAll(sel);
                            let text = '';
                            elements.forEach(el => {
                                text += el.innerText || '';
                            });
                            if (text.trim().length > maxLength) {
                                maxLength = text.trim().length;
                            }
                        }
                        return { loaded: maxLength > 500, length: maxLength };
                    }
                """)

                if result.get('loaded', False):
                    print(f"  新闻内容已加载，长度: {result.get('length', 0)}")
                    return True

                print(f"  等待内容加载... 当前正文长度: {result.get('length', 0)}")
                time.sleep(2)

            except Exception as e:
                print(f"  检查内容时出错: {e}")
                time.sleep(2)

        print("  等待新闻内容超时")
        return False

    def _check_error_page(self):
        """检测是否为错误页面"""
        try:
            title = self.browser.page.evaluate("document.title || ''")
            title_lower = title.lower()

            error_keywords = ['404', '403', '500', 'not found', 'forbidden', 'access denied',
                              'page not found', 'error', 'server error']
            for keyword in error_keywords:
                if keyword in title_lower:
                    return True, f"页面标题包含{keyword.upper()}"

            body_text = self.browser.page.evaluate("document.body ? document.body.innerText : ''")
            if len(body_text) < 2000:
                body_lower = body_text.lower()
                for keyword in error_keywords:
                    if keyword in body_lower:
                        return True, f"页面内容包含{keyword.upper()}"

            return False, None

        except Exception as e:
            print(f"  检测错误页面时异常: {e}")
            return False, None

    def _get_page_html(self):
        """获取完整的页面HTML（渲染后）"""
        try:
            return self.browser.page.content()
        except Exception as e:
            print(f"  获取HTML失败: {e}")
            return ""

    def _extract_with_ai(self, html_content, url):
        """
        调用DeepSeek API判断页面类型并提取标题和正文
        返回: (title, content, page_type, is_article)
        """
        if not self.api_key:
            print("  未配置API Key，使用备用提取方式")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True

        try:
            import requests

            # 清理HTML但保留结构标记
            text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

            # 将常见的块级标签替换为换行符，保留段落结构
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

            # 移除剩余的HTML标签
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-z]+;', ' ', text)

            # 清理多余的空白行，但保留段落结构
            text = re.sub(r'\n{4,}', '\n\n\n', text)
            text = text.strip()

            # 如果内容过长，截断
            max_length = 25000
            if len(text) > max_length:
                text = text[:max_length] + "\n...(内容已截断)"

            if len(text) < 50:
                return "无标题", "无正文内容", "empty", False

            prompt = f"""
请分析以下网页内容，判断它是否为文章/新闻页面，并提取标题和正文。

【第一步：判断页面类型】
请判断这个页面是属于以下哪一类：
1. "article" - 文章/新闻页面（有明确的标题和正文内容）
2. "consultation" - 咨询/公告/通知页面（如政府公开咨询、招标公告等）
3. "directory" - 目录/列表页面（如搜索结果列表、分类目录等）
4. "other" - 其他类型（如错误页面、登录页、首页等）

【第二步：如果是文章页面，请提取标题和正文】
1. 【标题】提取页面最核心、最准确的标题：
   - 完整、准确，不能截断
   - 通常是h1标签的内容或页面主标题
   - 不要包含网站名称、栏目名称等冗余信息

2. 【正文】提取文章的核心内容：
   - 排除导航、页眉、页脚、广告、版权声明、cookie提示等无关信息
   - 保留段落、列表、层次结构
   - 如果页面没有正文内容，返回"无正文内容"

【判断规则】
- 如果页面标题包含"Consulta Pública"、"Edital"、"Chamada Pública"等关键词，判断为"consultation"
- 如果页面主要显示列表、目录、搜索结果，判断为"directory"
- 如果页面没有h1标题，或只有少量文字，判断为"other"
- 只有包含完整文章结构（h1标题 + 多个段落 + 长篇内容）的页面才判断为"article"

URL: {url}

页面内容：
{text}

请按以下JSON格式返回结果：
{{
    "page_type": "article/consultation/directory/other",
    "title": "提取的标题（仅当page_type为article时有效）",
    "content": "提取的正文内容（仅当page_type为article时有效）"
}}
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
                    print(f"  页面类型: {page_type}, 是否文章: {is_article}")

                    return title, content, page_type, is_article

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
                    return title, content, page_type, is_article

            else:
                print(f"  API调用失败: {response.status_code}")
                title, content = self._extract_fallback(html_content)
                return title, content, "unknown", True

        except ImportError:
            print("  未安装requests库，使用备用提取方式")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True
        except Exception as e:
            print(f"  AI提取失败: {e}")
            title, content = self._extract_fallback(html_content)
            return title, content, "unknown", True

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

            return title, text

        except Exception as e:
            print(f"  备用提取失败: {e}")
            return "", ""

    def _should_wait(self, error_reason):
        """判断是否需要等待"""
        # 成功时等待
        if error_reason == "SUCCESS":
            return True
        # PDF链接跳过，不等待
        if "PDF" in error_reason:
            return False
        # 非文章页面，不等待
        if "非文章页面" in error_reason:
            return False
        # 无正文内容，不等待
        if "无正文内容" in error_reason:
            return False
        # 错误页面，不等待
        if "403" in error_reason or "404" in error_reason or "错误页面" in error_reason:
            return False
        # 其他失败情况，不等待
        if "失败" in error_reason or "异常" in error_reason:
            return False
        # 默认不等待
        return False

    def _wait_between_requests(self, idx, total, should_wait=True):
        """在请求之间等待"""
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

    def process_url(self, url):
        """处理单个URL"""
        if not url or not url.strip():
            return "", "NA", "URL为空"

        url = url.strip()

        if self._is_pdf_link(url):
            return "", "NA", "PDF链接，跳过爬取"

        try:
            print(f"  访问页面...")
            success = self.browser.goto(url, timeout=30 * 1000, proxy=self.proxy)

            if not success:
                return "无标题", "NA", "页面加载失败"

            print("  页面响应成功")

            self._wait_for_news_content(timeout=30)
            time.sleep(2)

            is_error, error_reason = self._check_error_page()
            if is_error:
                return "无标题", "NA", error_reason

            html_content = self._get_page_html()
            if not html_content or len(html_content) < 500:
                return "无标题", "无正文内容", "页面HTML内容过短"

            print(f"  HTML长度: {len(html_content)}")

            title, content, page_type, is_article = self._extract_with_ai(html_content, url)

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

    def process_csv(self):
        """处理CSV文件"""
        print("=" * 70)
        print("动态页面爬虫 (newPlayWright + AI 判断页面类型并提取)")
        print("=" * 70)
        print(f"输入文件: {self.input_file}")
        print(f"输出文件: {self.output_file}")
        if self.proxy:
            print(f"代理配置: {self.proxy.get('server', '无')}")
        if self.api_key:
            print("AI提取: 已启用 (DeepSeek API)")
            print("  - AI判断页面类型(article/consultation/directory/other)")
            print("  - 仅文章页面提取标题和正文")
            print("  - 正文保留格式（段落、列表、层次结构）")
        else:
            print("AI提取: 未启用 (使用备用提取方式)")
        print(f"请求间隔: {self.delay} 秒（仅成功时等待）")
        print("=" * 70)

        try:
            if self.use_special:
                self.browser = SpecialPlayWright()
                print("使用SpecialPlayWright（指纹浏览器）")
            else:
                self.browser = PlayWrightClass()
                print("使用普通PlayWright浏览器")

            self.browser.start_borwser(proxy=self.proxy)
            print("浏览器启动成功\n")

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        try:
            with open(self.input_file, 'r', encoding='utf-8') as infile, \
                    open(self.output_file, 'w', encoding='utf-8', newline='') as outfile:

                reader = csv.reader(infile)
                self.writer = csv.writer(outfile)

                try:
                    self.input_headers = next(reader)
                except StopIteration:
                    print("CSV文件为空")
                    return False

                if len(self.input_headers) <= 8:
                    print(f"错误: CSV文件列数不足，需要至少9列，实际{len(self.input_headers)}列")
                    return False

                self.output_headers = self.input_headers.copy()
                self.output_headers.append('title')
                self.output_headers.append('content')
                self.output_headers.append('error_reason')
                self.writer.writerow(self.output_headers)

                self.total = 0
                infile.seek(0)
                next(infile)
                for _ in infile:
                    self.total += 1
                infile.seek(0)
                next(infile)

                print(f"共有 {self.total} 条记录需要处理\n")
                print(f"注意: 仅成功提取的页面会等待{self.delay}秒，跳过的页面不等待\n")

                for idx, row in enumerate(reader, 1):
                    while len(row) < len(self.input_headers):
                        row.append('')

                    url = row[8] if len(row) > 8 else ''

                    print(f"\n[{idx}/{self.total}] 处理URL: {url[:80]}..." if url else f"[{idx}/{self.total}] URL为空")
                    print("-" * 60)

                    if not url or not url.strip():
                        row.append('无标题')
                        row.append('NA')
                        row.append('URL为空')
                        self.fail_count += 1
                        self._write_row(row)
                        self._wait_between_requests(idx, self.total, should_wait=False)
                        continue

                    title, content, error_reason = self.process_url(url)

                    row.append(title)
                    row.append(content)
                    row.append(error_reason)

                    self._write_row(row)
                    outfile.flush()

                    if error_reason == "SUCCESS":
                        self.success_count += 1
                        print(f"  ✓ 成功 (标题: {title[:50] if title else '无'}, 内容: {len(content)} 字符)")
                        preview = content[:200].replace('\n', ' ')
                        print(f"  预览: {preview}...")
                    elif "PDF" in error_reason:
                        self.skipped_count += 1
                        print(f"  ⏭ 跳过 (PDF链接)")
                    elif "非文章页面" in error_reason:
                        self.fail_count += 1
                        print(f"  ⚠ {error_reason}")
                    elif "无正文内容" in error_reason:
                        self.fail_count += 1
                        print(f"  ⚠ {error_reason}")
                    elif "403" in error_reason or "404" in error_reason or "错误页面" in error_reason:
                        self.fail_count += 1
                        print(f"  ⚠ 错误页面: {error_reason}")
                    else:
                        self.fail_count += 1
                        print(f"  ✗ 失败: {error_reason}")

                    # 判断是否需要等待
                    should_wait = (error_reason == "SUCCESS")
                    self._wait_between_requests(idx, self.total, should_wait=should_wait)

        except KeyboardInterrupt:
            print("\n\n用户中断，已保存已处理的数据")
        except Exception as e:
            print(f"处理过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                self.browser.close()
                print("浏览器已关闭")
            except:
                pass

        print("\n" + "=" * 60)
        print(f"处理完成!")
        print(f"总链接数: {self.total}")
        print(f"成功爬取: {self.success_count}")
        print(f"跳过(PDF): {self.skipped_count}")
        print(f"失败数量: {self.fail_count}")
        if self.total > 0:
            print(f"成功率: {(self.success_count + self.skipped_count) / self.total * 100:.1f}%")
        print(f"结果已保存到: {self.output_file}")
        print("=" * 60)

        return True

    def _write_row(self, row):
        if self.writer:
            self.writer.writerow(row)


def main():
    input_file = "./test.csv"
    output_file = None

    use_special = False

    proxy = {
        'server': 'http://127.0.0.1:7892'
    }

    API_KEY = "sk-c05a4aede23648a59a57990db317389c"

    DELAY_SECONDS = 30

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