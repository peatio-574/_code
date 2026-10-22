# coding='utf-8'
"""从系统宋体生成只含数字与连字符的字体子集（约 10KB）。

打包时若缺少 simsun_num.ttf，打包脚本会调用本文件自动生成，
避免把 17MB 的完整宋体塞进 exe；PDF 里只用到 0-9 和 “-”。
"""
import sys
from pathlib import Path

from fontTools import subset as fs
from fontTools.ttLib import TTFont

SOURCE = Path(r'C:\Windows\Fonts\simsun.ttc')
TARGET = Path(__file__).resolve().parent / 'simsun_num.ttf'
UNICODES = [0x0020, 0x002D] + list(range(0x30, 0x3A))


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f'找不到系统宋体：{source}')

    font = TTFont(str(source), fontNumber=0)
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
    try:
        target = build()
    except Exception as exc:
        print(f'生成字体子集失败：{exc}', file=sys.stderr)
        return 1
    print(f'已生成字体子集：{target.name}（{target.stat().st_size / 1024:.1f} KB）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
