# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from spider_1 import main

if __name__ == '__main__':
    main('file9')
