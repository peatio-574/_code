
from fontTools.ttLib import TTFont
class FontMapper:
    """字体映射分析器"""

    def __init__(self, font_path):
        self.font = TTFont(font_path)
        self.cmap = self.font.getBestCmap()
        self.mapping = {}

    def analyze(self):
        """完整分析字体映射"""
        print("=" * 60)
        print("字体映射分析报告")
        print("=" * 60)

        # 1. 显示所有编码
        print("\n1. 字体中的所有编码:")
        for code in sorted(self.cmap.keys()):
            char = chr(code)
            glyph = self.cmap[code]
            print(f"   {hex(code):6} -> '{char}' -> {glyph}")

        # 2. 尝试通过字形名称推断
        print("\n2. 字形名称分析:")
        glyph_name_counts = {}
        for name in self.cmap.values():
            # 提取数字部分
            import re
            numbers = re.findall(r'\d+', name)
            if numbers:
                glyph_name_counts[name] = numbers

        for name, nums in glyph_name_counts.items():
            print(f"   {name}: 包含数字 {nums}")

        # 3. 建议的映射建立方法
        print("\n3. 建立映射的建议:")
        print("   方法A: 收集更多已知编码-真实值对")
        print("   方法B: 查看网页源代码中的JavaScript映射")
        print("   方法C: 观察字形名称的编号规律")

        return self.cmap

    def build_mapping_from_examples(self, examples):
        """通过示例构建映射表"""
        mapping = {}
        for encoded_text, real_text in examples:
            for enc_char, real_char in zip(encoded_text, real_text):
                code = ord(enc_char)
                mapping[code] = real_char
        self.mapping = mapping
        return mapping

    def decode(self, text):
        """解码文本"""
        result = []
        for char in text:
            code = ord(char)
            if code in self.mapping:
                result.append(self.mapping[code])
            else:
                result.append(char)
        return ''.join(result)


# 使用示例
if __name__ == '__main__':
    mapper = FontMapper('./font.otf')

    # 分析字体
    mapper.analyze()

    # 使用已知示例构建映射
    examples = [
        ('ĥĨģģĢģģ', '2500.00'),
        # 你需要收集更多这样的示例
    ]

    mapping = mapper.build_mapping_from_examples(examples)

    # 测试解码
    test_text = 'æîèèéèè'
    decoded = mapper.decode(test_text)
    print(f"\n测试解码: {test_text} -> {decoded}")