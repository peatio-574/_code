# -*- coding: utf-8 -*-
"""
AI 简历识别服务
================
功能：
  - 解析 xlsx / pdf / docx / txt 简历内容
  - 若 AI（文档/大模型）不支持某类型文件，可先做“文档转换”再解析（convert_document）
  - 调用外部大模型（OpenAI 兼容协议，可配置）进行简历分析：打分 + 修改建议
  - 未配置 AI 时使用内置启发式分析（离线兜底），保证功能可完整演示
  - 基于简历分析总结出精准筛选条件，并进行岗位筛选（screen_jobs）
"""
import io
import json
import re
import subprocess
import shutil
import tempfile
import os
import importlib
import logging
from urllib import request as urlrequest

import openpyxl

logger = logging.getLogger(__name__)


# 缺少解析依赖时的友好提示
_HELP_INSTALL = {
    'pdfplumber': '缺少 PDF 解析组件 pdfplumber，请运行：pip install pdfplumber',
    'docx': '缺少 Word 解析组件 python-docx，请运行：pip install python-docx',
}


def _require(module_name, extractor):
    """惰性导入解析组件；缺失时给出可执行的安装指引，而不是抛裸 ImportError。"""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        msg = _HELP_INSTALL.get(module_name, f'缺少解析组件 {module_name}')
        raise ValueError(f'{msg}（用于解析 {extractor}）')

# 简历中常见的关键词库（用于离线启发式分析）
EDU_KEYWORDS = ['博士', '硕士', '研究生', '本科', '大专', '高职', '高中', '初中']
CITY_KEYWORDS = ['北京', '上海', '广州', '深圳', '天津', '重庆', '杭州', '南京', '苏州',
                 '成都', '武汉', '西安', '长沙', '郑州', '青岛', '济南', '合肥', '福州',
                 '厦门', '东莞', '佛山', '珠海', '中山', '惠州', '宁波', '无锡', '昆明']
SKILL_KEYWORDS = ['Java', 'Python', 'Go', 'C++', '前端', 'Vue', 'React', 'Android', 'iOS',
                  '数据库', 'MySQL', 'Redis', 'Kafka', 'Linux', 'Docker', 'K8s', '大数据',
                  '算法', '测试', '运维', '产品', '运营', '设计', 'UI', 'HR', '销售']


# ==================== 1. 文档解析 ====================

def _extract_xlsx(data: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip() != '']
            if cells:
                lines.append(' | '.join(cells))
    return '\n'.join(lines)


def _extract_docx(data: bytes) -> str:
    docx = _require('docx', 'Word 文档')
    d = docx.Document(io.BytesIO(data))
    parts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    for tbl in d.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(' | '.join(cells))
    if not parts:
        raise ValueError('Word 文档中没有可识别的文本内容')
    return '\n'.join(parts)


def _extract_pdf(data: bytes) -> str:
    pdfplumber = _require('pdfplumber', 'PDF 文档')
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ''
            if txt:
                parts.append(txt)
    joined = '\n'.join(parts).strip()
    if not joined:
        raise ValueError('PDF 没有可直接提取的文本（可能是纯扫描件，需要 OCR）')
    return joined


def _ocr_pdf(data: bytes) -> str:
    """转换方法：将无文字层的 PDF（扫描件）通过 OCR 转为文本。
    依赖：pdf2image(+poppler) 或 PyMuPDF(fitz) 渲染页面 + pytesseract(+tesseract) 识别。
    未安装对应组件时，给出可执行的处理指引。
    """
    from flask import current_app
    enabled = current_app.config.get('AI_OCR_ENABLED', True)
    if not enabled:
        raise ValueError('PDF 为扫描件且已关闭 OCR，请使用带文字层的 PDF 或先做 OCR 转换')

    images = None
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(data)
    except ImportError:
        try:
            import fitz
            doc = fitz.open(stream=data, filetype='pdf')
            images = []
            for i, page in enumerate(doc):
                pm = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                images.append(pm)
            doc.close()
        except ImportError:
            images = None

    if images is None:
        raise ValueError('PDF 是扫描件，且本机缺少 OCR 组件。'
                         '请安装 poppler + tesseract（pdf2image）或安装 pytesseract 后重试；'
                         '或先将 PDF 另存为“带文字层”的文档再上传。')

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ValueError('PDF 是扫描件，但缺少 OCR 识别库（pytesseract + tesseract）。'
                         '请安装后重试，或将 PDF 转为带文字层的文档再上传。')

    parts = []
    for im in images:
        if not isinstance(im, Image.Image):
            im = Image.frombytes('RGB', (im.width, im.height), im.samples)
        txt = pytesseract.image_to_string(im, lang='chi_sim+eng')
        if txt and txt.strip():
            parts.append(txt.strip())
    joined = '\n'.join(parts).strip()
    if not joined:
        raise ValueError('扫描件 OCR 未识别到文本，请提供更清晰的扫描版简历')
    return joined


def _extract_txt(data: bytes) -> str:
    return data.decode('utf-8', errors='ignore').strip()


def convert_document(filename: str, tmp_path: str):
    """文档转换方法：当某类型文件无法解析时，尝试转换后再解析。
    - .doc(旧版Word) / 扫描件：若本机安装 LibreOffice(soffice)，转为 pdf 再解析。
    - 返回转换后的文件路径；无法转换则抛出 ValueError。
    """
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        logger.warning('【文档转换】未安装 LibreOffice，无法转换文件「%s」', filename)
        raise ValueError('该文件格式暂不支持直接解析，且本机未安装 LibreOffice 无法转换。'
                         '请将文件另存为 .pdf 或 .docx 后重试。')
    logger.info('【文档转换】使用 LibreOffice 将「%s」转换为 PDF', filename)
    out_dir = tempfile.mkdtemp()
    subprocess.run([soffice, '--headless', '--convert-to', 'pdf',
                    '--outdir', out_dir, tmp_path], check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = os.path.splitext(os.path.basename(tmp_path))[0]
    converted = os.path.join(out_dir, base + '.pdf')
    if not os.path.isfile(converted):
        raise ValueError('文档转换失败，请手动将文件转换后再试。')
    return converted


def extract_resume_text(filename: str, data: bytes):
    """解析并返回简历文本。不支持的格式先尝试转换，仍失败则抛出 ValueError。"""
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else '').lower()
    original_ext = ext
    logger.info('【文档解析】开始解析简历「%s」，格式：.%s，大小：%.2f MB', filename,
                original_ext or '未知', len(data) / 1024 / 1024)
    if ext in ('xlsx', 'xls'):
        return _extract_xlsx(data)
    if ext == 'docx':
        return _extract_docx(data)
    if ext == 'pdf':
        try:
            return _extract_pdf(data)
        except ValueError:
            # 无文字层 → 走“文档转换”：OCR 识别扫描件
            logger.info('【文档解析】PDF 无文字层，使用 OCR 识别扫描件「%s」', filename)
            return _ocr_pdf(data)
    if ext == 'txt':
        return _extract_txt(data)

    # 其他格式（如 .doc、扫描件等）：走“文档转换”流程
    logger.warning('【文档解析】文件「%s」不支持直接解析，尝试文档转换', filename)
    with tempfile.NamedTemporaryFile(suffix='.' + original_ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        converted = convert_document(filename, tmp_path)
        with open(converted, 'rb') as f:
            return _extract_pdf(f.read())
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ==================== 2. 表格中的信息正则/启发式提取 ====================

def _detect_education(text: str) -> str:
    for kw in EDU_KEYWORDS:
        if kw in text:
            return kw
    return ''


def _detect_city(text: str) -> str:
    for kw in CITY_KEYWORDS:
        if kw in text:
            return kw
    return ''


def _detect_skills(text: str) -> list:
    found = [kw for kw in SKILL_KEYWORDS if kw.lower() in text.lower()]
    return found


def _detect_salary(text: str) -> str:
    m = re.search(r'(?:期望|薪资|要求).{0,6}?(\d{3,5})\s*[-~—到至]\s*(\d{3,5})\s*k', text)
    if m:
        return f"{m.group(1)}k-{m.group(2)}k"
    return ''


def _detect_job_intent(text: str) -> str:
    m = re.search(r'(?:求职意向|应聘岗位|意向岗位|目标岗位)[:：]?\s*([^\n，,。；;]{2,20})', text)
    if m:
        return m.group(1).strip()
    # 从技能里挑选最像岗位的
    for kw in SKILL_KEYWORDS:
        if kw in text:
            return kw
    return ''


_NAME_LABELS = ('姓名', '本人', '求职者', '候选人', '应聘者', '求职人', '应聘人')
_NAME_BAD_WORDS = ('简历', '个人简历', '基本信息', '个人信息', '联系方式', '求职意向',
                   '求职', '应聘', '自我介绍', '教育经历', '工作经历', '项目经历',
                   '专业技能', '证书', '自我评价', '姓名', '性别', '年龄', '学历',
                   '毕业院校', '专业', '籍贯', '现居', '电话', '手机', '邮箱', '地址')


def _is_field_word(name: str) -> bool:
    return name in _NAME_BAD_WORDS or name.startswith(('教育', '工作', '项目', '技能', '自我'))


def _detect_name(text: str) -> str:
    # 1) 带“姓名/本人/候选人...”等标记，且名称不是字段名
    m = re.search(r'(?:姓名|本人|求职者|候选人|应聘者|求职人|应聘人)\s*[:：]?\s*([\u4e00-\u9fa5·]{2,4})', text)
    if m:
        cand = m.group(1)
        if not _is_field_word(cand):
            return cand
    # 2) 首行/文件开头 独立出现的 2-4 字中文人名
    head = text.strip()[:500]
    for line in head.splitlines():
        line = line.strip()
        if not line:
            continue
        # 去掉常见前缀后，首个独立的中文人名
        m2 = re.match(r'^[\u4e00-\u9fa5·]{2,4}$', line)
        if m2 and not _is_field_word(m2.group(0)):
            return m2.group(0)
    # 3) 正文中“姓名/个人资料/基本信息”附近的人名
    m3 = re.search(r'(?:个人资料|基本信息|个人信息)[^\n]{0,6}?([\u4e00-\u9fa5]{2,4})(?=\s|$|[，,。；;:：])', text)
    if m3 and not _is_field_word(m3.group(1)):
        return m3.group(1)
    return ''


def _detect_experience(text: str) -> int:
    m = re.search(r'(\d+)\s*(?:年|个?月)', text)
    if not m:
        return 0
    return int(m.group(1))


def _fmt_experience(years: int) -> str:
    """将年数映射为岗位经验要求所用的区间格式。"""
    if years <= 0:
        return ''
    if years < 1:
        return '应届生'
    elif years <= 3:
        return '1-3年'
    elif years <= 5:
        return '3-5年'
    elif years <= 10:
        return '5-10年'
    return '10年以上'


def _detect_major(text: str) -> str:
    m = re.search(r'(?:专业|所学专业)[:：]?\s*([^\n，,。；;]{2,30})', text)
    if m:
        return m.group(1).strip()
    return ''


def extract_candidate_name(text: str) -> str:
    """从简历文本中尽力提取候选人姓名（用于识别记录展示）。"""
    return _detect_name(text or '')


# ==================== 3. AI 调用（可配置） ====================

def _call_ai(system_prompt: str, user_content: str):
    from flask import current_app
    # 读 .env/config 配置；为空则不用外部 AI，回落到内置启发式分析
    api_key = current_app.config.get('AI_API_KEY')
    if not api_key:
        logger.info('【AI】未配置 AI_API_KEY，本次回落本地启发式分析')
        return None
    base_url = current_app.config.get('AI_BASE_URL', '').rstrip('/')
    model = current_app.config.get('AI_MODEL', '')
    url = base_url + '/chat/completions'
    logger.info('【AI】开始调用大模型分析（模型：%s，接口：%s，文本长度：%d）',
                model or '(未配置)', url, len(user_content))
    payload = {
        'model': model,
        'temperature': 0.3,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_content},
        ],
    }
    # 兼容部分不含 json_mode 的端点，JSON 通过 prompt 约束
    req = urlrequest.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
    }, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.warning('【AI】大模型接口调用异常：%s，将回落本地启发式分析', e)
        return None
    content = data['choices'][0]['message']['content'].strip()
    # 尝试剥离 ```json ... ```
    content = re.sub(r'^```(json)?', '', content).rstrip('`').strip()
    try:
        logger.info('【AI】大模型分析成功')
        return json.loads(content)
    except Exception as e:
        logger.warning('【AI】大模型返回内容不是合法 JSON：%s', e)
        return None


def _call_ai_image(system_prompt: str, user_text: str, data_url: str):
    """多模态（图像）请求：把简历图片以 base64 data URL 传给支持视觉的模型。"""
    from flask import current_app
    api_key = current_app.config.get('AI_API_KEY')
    if not api_key:
        logger.info('【AI】未配置 AI_API_KEY，图片识别将回落 OCR/本地分析')
        return None
    base_url = current_app.config.get('AI_BASE_URL', '').rstrip('/')
    model = current_app.config.get('AI_MODEL', '')
    url = base_url + '/chat/completions'
    logger.info('【AI】调用多模态大模型识别图片（模型：%s，接口：%s，图片约 %d 字符）',
                model or '(未配置)', url, len(data_url))
    payload = {
        'model': model,
        'temperature': 0.3,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': user_text},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ]},
        ],
    }
    req = urlrequest.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
    }, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.warning('【AI】多模态接口调用异常：%s，将回落 OCR 识别', e)
        return None
    content = data['choices'][0]['message']['content'].strip()
    content = re.sub(r'^```(json)?', '', content).rstrip('`').strip()
    try:
        logger.info('【AI】多模态识别成功')
        return json.loads(content)
    except Exception as e:
        logger.warning('【AI】多模态返回内容不是合法 JSON：%s', e)
        return None


IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'bmp', 'webp'}


def _image_to_data_url(data: bytes) -> str:
    """压缩并转成 base64 data URL，控制图片体积避免请求过大。"""
    import base64, io
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert('RGB')
    w, h = img.size
    max_dim = 1500
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return 'data:image/jpeg;base64,' + b64


def _ocr_image(data: bytes) -> str:
    """本地 OCR 兜底：用 tesseract 识别图片中的文字，未安装则抛错。"""
    import io
    from PIL import Image
    import pytesseract
    img = Image.open(io.BytesIO(data))
    return (pytesseract.image_to_string(img, lang='chi_sim+eng') or '').strip()


def analyze_resume_image(data: bytes, filename: str, target_job: str = '') -> dict:
    """识别图片形式的简历：优先调用多模态大模型直接看图；失败则 OCR 转文本再分析。"""
    from flask import current_app
    logger.info('【图片识别】开始识别简历图片「%s」，大小：%.2f MB', filename, len(data) / 1024 / 1024)
    data_url = _image_to_data_url(data)
    user_text = '这是一张候选人简历图片，请基于图片内容进行分析。' + \
        (f'该候选人意向/应聘岗位：{target_job}。' if target_job else '')
    try:
        if current_app.config.get('AI_API_KEY'):
            result = _call_ai_image(_AI_SYSTEM_PROMPT, user_text, data_url)
            if result and isinstance(result, dict):
                return _normalize_result(result, target_job)
    except Exception as e:
        logger.warning('【图片识别】多模态接口调用异常：%s，尝试 OCR', e)
    # 兜底：OCR → 文本 → 常规分析
    try:
        text = _ocr_image(data)
        if text and text.strip():
            logger.info('【图片识别】OCR 转写成功，文本长度：%d，继续常规分析', len(text))
            return analyze_resume(text, target_job)
    except Exception as e:
        logger.warning('【图片识别】OCR 识别失败：%s', e)
    logger.warning('【图片识别】图片「%s」未能成功识别', filename)
    raise ValueError('无法识别该图片：请上传更清晰的简历截图/照片，或改用 xlsx / pdf / word 简历')


_AI_SYSTEM_PROMPT = (
    '你是一位资深 HR 与职业规划顾问。请阅读用户提供的简历文本，'
    '输出严格的 JSON（不要其它文字），字段如下：\n'
    '{"score": 0-100 整数, "level": "优"|"良"|"中"|"待提升", '
    '"candidate_name": "候选人姓名，从简历中提取，没有则空串", '
    '"strengths": ["优势短语..."], "suggestions": ["可落地的修改建议..."], '
    '"screening": {"keyword": "岗位关键词", "province": "省份", "city": "城市", '
    '"education": "学历", "age": "年龄要求,如30岁以下/应届生,无则空串", '
    '"experience": "工作经验年限要求,如应届生/1-3年/3-5年,无则空串", '
    '"major": "专业要求,无则空串", "remark": "筛选说明"}}。\n'
    'screening 用于岗位筛选：keyword 取简历中明确的求职意向/技能关键词，'
    'age 推断候选人可接受的年龄范围，experience 推断期望的工作年限，'
    'major 提取专业要求；不明确的字段传空字符串"".\n'
    '"suggestions" 为 3-5 条具体、可落地的简历优化建议，要求：\n'
    '1) 避免“建议补充与岗位相关的技能/经历”这类笼统表述，直接指出简历当前缺失或薄弱之处；\n'
    '2) 结合目标岗位 JD 要求，说明应埋入哪些具体关键词：技术栈/工具、业务能力、项目落地细节、可量化产出指标；\n'
    '3) 涉及“补充技能/经历关键词”时，写出【旧写法(笼统) → 新写法(埋入关键词)】的具体改法示例，用 ❌/✅ 标注，'
    '例如 ❌“负责网站项目开发” ✅“负责企业官网 Web 系统搭建，完成腾讯云 ECS 配置、域名 DNS 解析、安全组策略；'
    '主导 ICP 备案、公安网安备案落地；基于 Nginx 反向代理实现前后端端口转发，保障系统稳定上线”；\n'
    '4) 每条建议独立成句，具体到可照着改，避免空话。'
)


# ==================== 4. 备用启发式分析（无 AI Key 时） ====================

def _mock_analyze(text: str, target_job: str = '') -> dict:
    skills = _detect_skills(text)
    edu = _detect_education(text)
    city = _detect_city(text)
    intent = _detect_job_intent(text) or target_job
    name = _detect_name(text)
    exp = _detect_experience(text)
    if target_job and target_job != intent:
        intent = target_job

    score = 60
    strengths = []
    suggestions = []
    if edu:
        score += 8
        strengths.append(f'学历：{edu}')
    if exp and exp >= 3:
        score += 12
        strengths.append(f'拥有约 {exp} 年相关经验')
    elif exp and exp >= 1:
        score += 6
        strengths.append(f'具备约 {exp} 年相关经验')
    if len(skills) >= 4:
        score += 12
        strengths.append(f'技能面较广：{"、".join(skills[:6])}')
    elif skills:
        score += 5
        strengths.append(f'掌握：{"、".join(skills)}')
    if city:
        strengths.append(f'意向城市：{city}')
    if name:
        strengths.append(f'信息较完整（已识别姓名：{name}）')
    if intent:
        strengths.append(f'有明确求职意向：{intent}')

    if len(skills) < 3 or (target_job and not any(k.lower() in text.lower() for k in target_job.split())):
        suggestions.append(
            f'建议在简历中进一步补充与「{target_job or "目标岗位"}」高度相关的专业技能关键词、项目落地细节关键词。'
            '结合目标岗位 JD 要求，把业务能力、工具栈、项目产出指标拆解嵌入经历段落，避免笼统描述，'
            '提升简历与招聘岗位的关键词匹配度，便于系统筛选及 HR 快速抓取核心竞争力。'
            '示例：❌“负责网站项目开发，完成域名解析与服务器部署”'
            ' → ✅“负责企业官网 Web 系统搭建，完成腾讯云 ECS 服务器配置、域名 DNS 解析、安全组策略配置；'
            '主导 ICP 备案、公安网安备案全流程落地；基于 Nginx 实现反向代理，完成前后端服务端口转发，保障业务系统稳定上线”。'
        )
    if not edu:
        suggestions.append('补充最高学历（院校/专业/学位），便于岗位学历门槛的自动筛选')
    if not intent:
        suggestions.append('在简历开头明确“求职意向/目标岗位”，并写明意向城市、期望薪资，方便做岗位匹配')
    if exp < 1:
        suggestions.append('补齐实习/项目经历的关键时间轴，每段用“做过 + 用什么 + 结果/指标”呈现，体现量化产出')
    if not _detect_salary(text):
        suggestions.append('补充期望薪资区间，便于薪酬匹配与后续沟通')
    if target_job:
        suggestions.append(f'结合意向岗位「{target_job}」，在简历顶部放置“技能关键词 + 目标岗位”一句话定位，突出与岗位核心要求相符的技能与项目成果')
    if not suggestions:
        suggestions.append('简历结构较完整，可结合目标岗位 JD 再微调关键词，增加量化成果与业务落地细节')

    score = max(30, min(95, score))
    if score >= 88:
        level = '优'
    elif score >= 75:
        level = '良'
    elif score >= 60:
        level = '中'
    else:
        level = '待提升'

    screening = {
        'keyword': intent or (skills[0] if skills else ''),
        'province': '',
        'city': city,
        'education': edu,
        'age': '',
        'experience': _fmt_experience(exp),
        'major': _detect_major(text),
        'remark': f'基于“{intent or skills[0] if (intent or skills) else "综合"}”等意向关键词筛选',
    }
    return {'score': score, 'level': level, 'candidate_name': name,
            'strengths': strengths, 'suggestions': suggestions,
            'screening': screening, 'ai': False}


def _normalize_result(result: dict, target_job: str = '') -> dict:
    """把大模型返回的 JSON 规范化为前端/记录统一结构。"""
    scr = result.get('screening') or {}
    keyword = (scr.get('keyword', '') or '').strip() or target_job
    return {
        'score': max(0, min(100, int(result.get('score', 60)))),
        'level': result.get('level', '') or '中',
        'candidate_name': (result.get('candidate_name') or '').strip(),
        'strengths': result.get('strengths') or [],
        'suggestions': result.get('suggestions') or [],
        'screening': {
            'keyword': keyword,
            'province': scr.get('province', ''),
            'city': scr.get('city', ''),
            'education': scr.get('education', ''),
            'age': scr.get('age', ''),
            'experience': scr.get('experience', ''),
            'major': scr.get('major', ''),
            'remark': scr.get('remark', '由 AI 分析生成'),
        },
        'ai': True,
    }


def analyze_resume(text: str, target_job: str = '') -> dict:
    """优先调用外部 AI；失败或未配置时回落本地启发式分析。
    target_job：用户填写的意向岗位（选填），用于让 AI 围绕该岗位给出针对性优化建议。"""
    logger.info('【简历分析】开始分析，文本长度：%d，目标岗位：%s', len(text or ''), target_job or '(未填写)')
    user_content = text[:12000]
    if target_job:
        user_content = (f'该候选人意向/应聘岗位：{target_job}\n'
                        f'——请围绕“{target_job}”提出针对性可落地的简历优化建议。\n'
                        f'--------------------------------\n' + user_content)
    try:
        result = _call_ai(_AI_SYSTEM_PROMPT, user_content)
        if result and isinstance(result, dict):
            ok = _normalize_result(result, target_job)
            logger.info('【简历分析】AI 分析成功，评分：%s，等级：%s', ok.get('score'), ok.get('level'))
            return ok
    except Exception as e:
        logger.warning('【简历分析】AI 分析异常：%s，将回落本地启发式', e)
    fallback = _mock_analyze(text, target_job)
    logger.info('【简历分析】完成（本地启发式），评分：%s，等级：%s', fallback.get('score'), fallback.get('level'))
    return fallback


# ==================== 5. 岗位筛选 ====================

def screen_jobs(screening: dict, limit: int = 50):
    """基于简历分析出的筛选条件，返回匹配度排序的岗位列表。"""
    from ..models import Job, db

    query = Job.query.filter_by(is_deleted=False)
    keyword = (screening.get('keyword') or '').strip()
    province = (screening.get('province') or '').strip()
    city = (screening.get('city') or '').strip()
    education = (screening.get('education') or '').strip()
    experience = (screening.get('experience') or '').strip()
    major = (screening.get('major') or '').strip()

    if keyword:
        ors = [Job.job_name.contains(keyword), Job.company_name.contains(keyword),
               Job.job_category.contains(keyword), Job.major_req.contains(keyword)]
        query = query.filter(db.or_(*ors))
    if province:
        query = query.filter(db.or_(Job.province == province, Job.province.like(province + '%')))
    if city:
        query = query.filter(db.or_(Job.city == city, Job.city.like(city + '%')))
    if education:
        if education == '不限':
            query = query.filter(db.or_(Job.education_req == '', Job.education_req == None, Job.education_req == '不限'))
        else:
            query = query.filter(Job.education_req == education)
    if experience and experience != '不限':
        _exp = experience.replace('年', '').strip()
        if _exp in ('应届生', '1年以内'):
            query = query.filter(db.or_(
                Job.experience_req.in_(['应届生', '1年以内']),
                Job.experience_req.in_(['', None]),
            ))
        elif _exp in ('1-3', '3-5'):
            query = query.filter(db.or_(
                Job.experience_req == experience,
                Job.experience_req == '',
                Job.experience_req == None,
                Job.experience_req == '不限',
            ))
    if major:
        query = query.filter(db.or_(Job.major_req.contains(major), Job.major_req == ''))

    jobs = query.limit(limit).all()

    def match_score(job):
        s = 50
        text = f"{job.job_name}{job.job_category}{job.company_name}{job.major_req}{job.work_location}"
        if keyword and keyword.lower() in text.lower():
            s += 30
        else:
            s -= 10
        if city and (city in text or city == job.city):
            s += 10
        if education and (education in (job.education_req or '')):
            s += 10
        if experience and (experience in (job.experience_req or '')):
            s += 10
        if major and (major in (job.major_req or '')):
            s += 5
        return s

    result = []
    for job in jobs:
        result.append({
            'id': job.id,
            'job_name': job.job_name,
            'company_name': job.company_name,
            'company_type': job.company_type,
            'recruit_type': job.recruit_type or '',
            'salary_range': job.salary_range,
            'education_req': job.education_req or '不限',
            'location': f"{job.province}-{job.city}",
            'score': match_score(job),
        })
    result.sort(key=lambda x: x['score'], reverse=True)
    return result
