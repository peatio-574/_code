
import os
import shutil
for i in os.listdir('d:/_code/spider_xhs/数据'):
    if os.path.isdir(os.path.join('d:/_code/spider_xhs/数据', i)):
        if not os.listdir(os.path.join('d:/_code/spider_xhs/数据', i, 'images')):
            shutil.rmtree(os.path.join('d:/_code/spider_xhs/数据', i))

