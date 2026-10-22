# coding='utf-8'
"""生成只含数字与连字符的字体子集（约 10KB），供 PDF 贴图时书写编号。

模板正文已改为黑体，因此这里默认从「黑体 simhei.ttf」取子集，
与模板里「作品编号（NO）：」的字形保持一致。
避免把 9MB 的黑体完整塞进 exe——PDF 里只用到 0-9、"-" 和空格。
"""
import sys
from pathlib import Path

from fontTools import subset as fs
from fontTools.ttLib import TTFont

BASE_DIR = Path(__file__).resolve().parent

# 默认：黑体 -> simhei_num.ttf
SOURCE = Path(r'C:\Windows\Fonts\simhei.ttf')
TARGET = BASE_DIR / 'simhei_num.ttf'

UNICODES = [0x0020, 0x002D] + list(range(0x30, 0x3A))


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f'找不到系统黑体：{source}')

    # ttf 直接打开；ttc 需要指定字体序号
    kwargs = {'fontNumber': 0} if source.suffix.lower() == '.ttc' else {}
    font = TTFont(str(source), **kwargs)

    options = fs.Options()
    options.name_IDs = ['*']
    options.name_legacy = True
    options.name_languages = ['*']
    options.notdef_outline = True
    options.recalc_bounds = True
    options.layout_features = []
    options.glyph_names = False
    options.drop_tables = set(options.drop_tables) | {'DSIG', 'FFTM', 'EBDT', 'EBLC', 'EBSC'}

    subsetter = fs.Subsetter(options=options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    font.save(str(target))
    font.close()
    return target


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else TARGET
    try:
        out = build(source, target)
    except Exception as exc:
        print(f'生成字体子集失败：{exc}', file=sys.stderr)
        return 1
    print(f'已生成字体子集：{out.name}（{out.stat().st_size / 1024:.1f} KB）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
