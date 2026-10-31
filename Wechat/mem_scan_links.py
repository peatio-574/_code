# -*- coding: utf-8 -*-
"""从 PC 微信客户端进程内存里提取公众号文章链接（仅 Windows）。
"""

import ctypes
import re
import sys


from ctypes import wintypes
import json
import os

if sys.platform != 'win32':
    raise RuntimeError(
        '本模块通过 Windows API 读取进程内存，只能在 Windows 上运行；'
        '当前平台：%s' % sys.platform)


# ══════════════════════════════════════════════════════════════════
# Windows 结构体声明（相当于 C 的 struct，不是业务对象）
# ══════════════════════════════════════════════════════════════════
# VirtualQueryEx / Process32FirstW 会把内核数据直接写进你提供的这块内存，
# 所以字段顺序、类型、大小必须和 Windows SDK 完全一致。
# 传 dict 或 tuple 会被直接拒绝（TypeError）。

class _MemoryInfo(ctypes.Structure):
    """一块内存区域的描述（对应 MEMORY_BASIC_INFORMATION）。
    """
    _fields_ = [
        ('BaseAddress', ctypes.c_void_p),
        ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', wintypes.DWORD),
        ('RegionSize', ctypes.c_size_t),
        ('State', wintypes.DWORD),
        ('Protect', wintypes.DWORD),
        ('Type', wintypes.DWORD),
    ]


class _ProcessEntry(ctypes.Structure):
    """进程列表里的一条记录（对应 PROCESSENTRY32W）。"""
    _fields_ = [
        ('dwSize', wintypes.DWORD),        # 调用前必须先填 sizeof(本结构体)
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),  # ← 进程 ID
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),  # ← 进程名
    ]


class WechatMemReader:


    def __init__(self):
        self.exes = ('Weixin.exe', 'WeChatAppEx.exe')  # 要扫的进程
        self.chunk = int(8 * 1024 * 1024)   # 每次读多少字节，默认 8MB
        self.overlap = int(8 * 1024)  # 相邻块重叠字节数，默认 8KB（防链接跨块被切断）
        self.max_addr = 0x7FFFFFFFFFFF     # x64 用户态地址上界

        # Windows API 常量
        self.VM_READ = 0x0010              # 允许读进程内存
        self.QUERY_INFO = 0x0400           # 允许查内存布局
        self.SNAP_PROC = 0x00000002        # 快照内容：进程列表
        self.MEM_COMMIT = 0x1000           # 内存已提交（有数据）
        self.PAGE_GUARD = 0x100            # 守护页，读它会让微信崩溃！

        # 算可读的保护位：0x02 只读 / 0x04 读写 / 0x20 可执行读 / 0x40 可执行读写
        self.readable = frozenset((0x02, 0x04, 0x20, 0x40))
        # 内核句柄 + 读缓冲（缓冲懒创建）
        self.k32 = ctypes.windll.kernel32
        self._declare_api()
        self._buffer = None


    def _declare_api(self):
        """声明 API 签名。
        必须写：ctypes 默认把返回值当 32 位整数，而句柄在 x64 上是
        8 字节指针。不声明会被截断，句柄无效 —— 表现为
        「OpenProcess 看着成功了，但一读内存就失败」。
        """
        k = self.k32
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     ctypes.POINTER(_MemoryInfo),
                                     ctypes.c_size_t]
        k.VirtualQueryEx.restype = ctypes.c_size_t
        k.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE,
                                      ctypes.POINTER(_ProcessEntry)]
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = [wintypes.HANDLE,
                                     ctypes.POINTER(_ProcessEntry)]
        k.Process32NextW.restype = wintypes.BOOL


    def scan_process(self):
        """扫描微信进程"""
        procs = []
        for exe in self.exes:
            snap = self.k32.CreateToolhelp32Snapshot(self.SNAP_PROC, 0)
            if not snap or snap == wintypes.HANDLE(-1).value:
                continue
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)  # 必须先填大小
            try:
                ok = self.k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower() == exe.lower():
                        procs.append((exe, entry.th32ProcessID))
                    ok = self.k32.Process32NextW(snap, ctypes.byref(entry))
            finally:
                self.k32.CloseHandle(snap)

        if not procs:
            print(f'没找到微信进程（{self.exes}），请先打开微信客户端')
            return []
        print(f'共{len(procs)}个微信进程：')
        return procs


    def scan_memory(self, procs, biz):
        """扫描内存"""
        info = []

        for exe, pid in procs:
            # 打开进程拿读权限。失败通常是权限不匹配
            # （微信以管理员运行，而本脚本不是）。
            handle = self.k32.OpenProcess(self.VM_READ | self.QUERY_INFO, False, pid)
            if not handle:
                print(f'  pid={pid} 打不开（微信若以管理员运行，本脚本也要提权）')
                continue

            if self._buffer is None:      # 懒创建，整轮扫描复用这一块
                self._buffer = ctypes.create_string_buffer(self.chunk + self.overlap)
            buf = self._buffer
            cap = len(buf)

            read_total = 0
            mbi = _MemoryInfo()
            mbi_size = ctypes.sizeof(mbi)
            addr = 0
            try:
                # 从地址 0 往后，一段一段问「这段能读吗」
                while addr < self.max_addr:
                    if not self.k32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size):
                        break # 查询失败 = 到头了

                    base = mbi.BaseAddress or 0
                    size = mbi.RegionSize or 0
                    nxt = base + size

                    # 守护页最危险：读它会让微信直接崩溃闪退。(有长度 + 已提交（有数据）+ 可读 + 不是守护页)三个条件都满足才读：
                    ok_region = bool(mbi.RegionSize and mbi.State == self.MEM_COMMIT
                        and mbi.Protect in self.readable and not (mbi.Protect & self.PAGE_GUARD))

                    if ok_region:
                        # 一段可能几百 MB，分块读；相邻块重叠 overlap 字节，
                        # 否则横跨两块边界的链接会被切成两半、谁都匹配不上。
                        off = 0
                        while off < size:
                            want = min(cap, size - off)
                            got = ctypes.c_size_t(0)
                            if self.k32.ReadProcessMemory(handle, ctypes.c_void_p(base + off), buf, want, ctypes.byref(got)) and got.value:
                                read_total += got.value
                                data = ctypes.string_at(buf, got.value)

                                # ① 短链 id    /s/ 后面 20~24 位。
                                info = self.single_proc_scan_short_link(info, data, biz)
                                # ② 完整分享链（下面统一去噪）
                                info = self.single_proc_scan_long_link(info, data, biz)
                            off += self.chunk

                    if nxt <= addr:               # 防死循环
                        break
                    addr = nxt
            finally:
                self.k32.CloseHandle(handle)
            print(f'  {exe} pid={pid}：读 {read_total/1024/1024} MB，初步累计{len(info)}条')
        return info


    def single_proc_scan_short_link(self, links, data, biz):
        # ① 短链 id    /s/ 后面 20~24 位。
        result = re.compile(rb'/s/([A-Za-z0-9_-]{20,24})(?![A-Za-z0-9_-])').finditer(data)
        for m in result:
            short_link = 'https://mp.weixin.qq.com/s/' + m.group(1).decode('ascii', 'ignore')

            # 短链：/s/ 后面直接跟 id，后面没有 ?
            rule = re.compile(r'/s/[A-Za-z0-9_-]{20,24}(?:[?#].*)?$').search(short_link)
            if rule and biz in short_link and short_link not in links:
                links.append(short_link)
        return links


    def single_proc_scan_long_link(self, links, data, biz):
        # ② 完整分享链（下面统一去噪）
        for m in re.compile(rb'mp\.weixin\.qq\.com/s\?[^"\'<>\s]{20,300}').finditer(data):
            long_link = 'https://' + m.group(0).decode('ascii', 'ignore')

            if '?' not in long_link:
                continue
            if '${' in long_link or '{{' in long_link:  # 模板变量
                continue

            m = re.compile(r'[?&]__biz=([^&#]{4,80})').search(long_link)  # 分享链接必须有合法__biz
            if not m or not m.group(1) or m.group(1).startswith('='):
                continue

            rule = re.compile(r'[?&]sn=([0-9a-fA-F]{8,})').search(long_link)  # 分享链接必须有合法sn
            if rule and biz in long_link and long_link not in links:
                links.append(long_link)
        return links


    def get_links(self, biz=''):
        """扫描微信内存，返回文章链接列表。"""
        procs = self.scan_process()
        all_links = self.scan_memory(procs, biz)
        all_links = list(set(all_links))

        print('合计 %d 条' % len(all_links))
        result = [{'url': i, 'status': False} for i in all_links]
        file_name = os.path.join(os.path.dirname(__file__), 'links.json')
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return sorted(all_links)


if __name__ == '__main__':
    WechatMemReader().get_links('MzI5NDQyMzYyMg==')
