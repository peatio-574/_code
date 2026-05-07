# -*- coding: utf-8 -*-
def check():
    import os
    dir1 = r'D:\tmp\51\视觉硬件技术-硬件开发'

    for i in os.listdir(dir1):
        files = os.listdir(os.path.join(dir1, i))
        if 'index.html' not in files:
            print(f'{i}爬取异常')
    info = [i.split('_', 1)[1] for i in os.listdir(dir1)]
    for i in info:
        count = info.count(i)
        if count > 1:
            print(f'{i}重复')

if __name__ == '__main__':
    check()