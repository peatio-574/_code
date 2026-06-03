# -*- coding: utf-8 -*-
"""
电商平台账号管理工具
支持：淘宝、拼多多、抖店、微店、小红书
功能：登录、导出、Cookie管理、数据汇总
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import os
import configparser

from Logger import logger
from PlayWright import Playwright_, get_config_value, write_config_value
import time

# 导入各平台爬虫模块
from spider_tb import tb_login, tb_search, tb_save, tb_deal_data
from spider_pdd import pdd_login, pdd_search, pdd_save, pdd_deal_data
from spider_dd import dd_login, dd_search, dd_save, dd_deal_data
from spider_wd import wd_login, wd_search, wd_save, wd_deal_data
from spider_xhs import xhs_login, xhs_search, xhs_save, xhs_download, xhs_deal_data

config_file = os.path.join(os.path.dirname(__file__), 'config.ini')


class AccountManagerGUI:
    """账号管理 GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title("电商平台账号管理工具")
        self.root.geometry("900x700")

        # 平台配置
        self.platforms = {
            '淘宝': {'prefix': 'tb', 'count_key': 'tb_shop_count'},
            '拼多多': {'prefix': 'pdd', 'count_key': 'pdd_shop_count'},
            '抖店': {'prefix': 'dd', 'count_key': 'dd_shop_count'},
            '微店': {'prefix': 'wd', 'count_key': 'wd_shop_count'},
            '小红书': {'prefix': 'xhs', 'count_key': 'xhs_shop_count'}
        }

        self.current_platform = None
        self.current_account_id = None
        self.is_running = False

        self._setup_ui()

    def _setup_ui(self):
        """设置界面"""
        # 顶部：平台选择
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="选择平台：", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        self.platform_var = tk.StringVar()
        platform_combo = ttk.Combobox(top_frame, textvariable=self.platform_var,
                                      values=list(self.platforms.keys()), width=15, state='readonly')
        platform_combo.pack(side=tk.LEFT, padx=5)
        platform_combo.bind('<<ComboboxSelected>>', self._on_platform_change)

        ttk.Button(top_frame, text="刷新账号列表", command=self._refresh_accounts).pack(side=tk.LEFT, padx=5)

        # 中间：账号列表
        middle_frame = ttk.Frame(self.root, padding="10")
        middle_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(middle_frame, text="账号列表：", font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=5)

        # 账号列表树形控件
        columns = ('账号ID', '状态', '操作')
        self.account_tree = ttk.Treeview(middle_frame, columns=columns, show='headings', height=8)
        self.account_tree.heading('账号ID', text='账号ID')
        self.account_tree.heading('状态', text='状态')
        self.account_tree.heading('操作', text='操作')
        self.account_tree.column('账号ID', width=100, anchor='center')
        self.account_tree.column('状态', width=150, anchor='center')
        self.account_tree.column('操作', width=150, anchor='center')
        self.account_tree.pack(fill=tk.X, pady=5)

        # 账号列表右键菜单
        self.account_menu = tk.Menu(self.root, tearoff=0)
        self.account_menu.add_command(label="登录此账号", command=self._login_selected)
        self.account_menu.add_command(label="删除Cookie", command=self._delete_cookie_selected)
        self.account_tree.bind('<Button-3>', self._show_account_menu)

        # 操作按钮区
        button_frame = ttk.Frame(self.root, padding="10")
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="登录选中账号", command=self._login_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除选中账号Cookie", command=self._delete_cookie_selected).pack(side=tk.LEFT,
                                                                                                       padx=5)
        ttk.Button(button_frame, text="导出并处理数据", command=self._export_and_deal).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="数据汇总", command=self._total_data).pack(side=tk.LEFT, padx=5)

        # 底部：日志显示
        bottom_frame = ttk.Frame(self.root, padding="10")
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(bottom_frame, text="操作日志：", font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=5)
        self.log_text = scrolledtext.ScrolledText(bottom_frame, height=15, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _log(self, message):
        """输出日志"""
        self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.root.update()

    def _on_platform_change(self, event=None):
        """平台改变事件"""
        self.current_platform = self.platform_var.get()
        self._refresh_accounts()

    def _refresh_accounts(self):
        """刷新账号列表"""
        platform = self.platform_var.get()
        if not platform:
            return

        # 清空列表
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)

        config_info = get_config_value('login', self.platforms[platform]['count_key'], file=config_file)
        shop_count = int(config_info) if config_info else 0

        for account_id in range(1, shop_count + 1):
            cookie_key = f'{self.platforms[platform]["prefix"]}_cookie_{account_id}'
            has_cookie = bool(get_config_value('login', cookie_key, file=config_file))
            status = "已登录" if has_cookie else "未登录"
            self.account_tree.insert('', tk.END, values=(f'账号{account_id}', status, ''))

        self._log(f"已加载 {platform} 的 {shop_count} 个账号")

    def _show_account_menu(self, event):
        """显示右键菜单"""
        item = self.account_tree.identify_row(event.y)
        if item:
            self.account_tree.selection_set(item)
            self.account_menu.post(event.x_root, event.y_root)

    def _get_selected_account(self):
        """获取选中的账号"""
        selected = self.account_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个账号")
            return None

        item = self.account_tree.item(selected[0])
        account_id = int(item['values'][0].replace('账号', ''))
        return account_id

    def _login_selected(self):
        """登录选中的账号"""
        account_id = self._get_selected_account()
        if not account_id:
            return

        platform = self.platform_var.get()
        if not platform:
            messagebox.showwarning("提示", "请先选择平台")
            return

        self._log(f"开始登录 {platform} - 账号{account_id}")
        self.status_var.set(f"登录中...")

        # 在新线程中执行登录
        def do_login():
            try:
                if platform == '淘宝':
                    success = tb_login(account_id)
                elif platform == '拼多多':
                    success = pdd_login(account_id)
                elif platform == '抖店':
                    success = dd_login(account_id)
                elif platform == '微店':
                    success = wd_login(account_id)
                elif platform == '小红书':
                    success = xhs_login(account_id)
                else:
                    success = False

                if success:
                    self.root.after(0, lambda: self._log(f"✅ {platform} - 账号{account_id} 登录成功"))
                    self.root.after(0, lambda: self.status_var.set("登录成功"))
                else:
                    self.root.after(0, lambda: self._log(f"❌ {platform} - 账号{account_id} 登录失败"))
                    self.root.after(0, lambda: self.status_var.set("登录失败"))

                self.root.after(0, self._refresh_accounts)
            except Exception as e:
                self.root.after(0, lambda: self._log(f"❌ 登录异常：{e}"))
                self.root.after(0, lambda: self.status_var.set("登录异常"))

        threading.Thread(target=do_login, daemon=True).start()

    def _delete_cookie_selected(self):
        """删除选中账号的Cookie"""
        account_id = self._get_selected_account()
        if not account_id:
            return

        platform = self.platform_var.get()
        if not platform:
            messagebox.showwarning("提示", "请先选择平台")
            return

        # 确认删除
        if not messagebox.askyesno("确认", f"确定要删除 {platform} - 账号{account_id} 的Cookie吗？"):
            return

        # 删除Cookie
        prefix = self.platforms[platform]['prefix']
        cookie_key = f'{prefix}_cookie_{account_id}'
        api_key = f'{prefix}_cookie_{account_id}_api'

        # 读取现有配置
        Config = configparser.ConfigParser(interpolation=None)
        Config.read(config_file, encoding='utf-8')

        if 'login' in Config.sections():
            if cookie_key in Config['login']:
                del Config['login'][cookie_key]
            if api_key in Config['login']:
                del Config['login'][api_key]

            with open(config_file, mode='w', encoding='utf-8') as f:
                Config.write(f)

        self._log(f"✅ 已删除 {platform} - 账号{account_id} 的Cookie")
        self.status_var.set("Cookie已删除")
        self._refresh_accounts()

    def _export_and_deal(self):
        """导出并处理数据"""
        account_id = self._get_selected_account()
        if not account_id:
            return

        platform = self.platform_var.get()
        if not platform:
            messagebox.showwarning("提示", "请先选择平台")
            return

        if not messagebox.askyesno("确认", f"确定要导出 {platform} - 账号{account_id} 的数据吗？"):
            return

        self._log(f"开始导出 {platform} - 账号{account_id} 的数据")
        self.status_var.set("导出中...")

        def do_export():
            try:
                dirname = os.path.join(os.path.dirname(__file__), '数据')
                os.makedirs(dirname, exist_ok=True)
                end = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
                start = f"{end[:-3]}-01"

                # 登录
                if platform == '淘宝':
                    if not tb_login(account_id):
                        self.root.after(0, lambda: self._log("❌ 登录失败"))
                        return
                    shop_name = tb_search(start, end)
                    filename = f'淘宝-{shop_name}店铺{end}明细.xlsx'
                elif platform == '拼多多':
                    if not pdd_login(account_id):
                        self.root.after(0, lambda: self._log("❌ 登录失败"))
                        return
                    shop_name = pdd_search(start, end)
                    filename = f'拼多多-{shop_name}店铺{end}明细.xlsx'
                elif platform == '抖店':
                    if not dd_login(account_id):
                        self.root.after(0, lambda: self._log("❌ 登录失败"))
                        return
                    shop_name = dd_search(start, end)
                    filename = f'抖店-{shop_name}店铺{end}明细.xlsx'
                elif platform == '微店':
                    if not wd_login(account_id):
                        self.root.after(0, lambda: self._log(" 登录失败"))
                        return
                    shop_name = wd_search(start, end)
                    filename = f'微店-{shop_name}店铺{end}明细.xlsx'
                elif platform == '小红书':
                    if not xhs_login(account_id):
                        self.root.after(0, lambda: self._log("❌ 登录失败"))
                        return
                    shop_name = xhs_search(start, end)
                    filename = f'小红书-{shop_name}店铺{end}明细.xlsx'
                else:
                    self.root.after(0, lambda: self._log("❌ 不支持的平台"))
                    return

                filepath = os.path.join(dirname, filename)

                # 导出
                if platform == '淘宝':
                    time.sleep(10)
                    status = False
                    for roll in range(1, 6):
                        Playwright_.click('//span[text()="导出"]')
                        status = tb_save(filepath)
                        if status:
                            break
                elif platform == '拼多多':
                    time.sleep(10)
                    status = False
                    for roll in range(1, 6):
                        Playwright_.click('//span[text()="导出"]')
                        Playwright_.switch_to_page()
                        status = pdd_save(filepath)
                        if status:
                            break
                elif platform == '抖店':
                    status = dd_save(end, shop_name)
                elif platform == '微店':
                    # 微店需要特殊处理
                    self.root.after(0, lambda: self._log("⚠️ 微店需要手动下载，请等待预生成完成后再次点击"))
                    return
                elif platform == '小红书':
                    time.sleep(10)
                    status = False
                    for roll in range(1, 6):
                        status = xhs_save(filepath)
                        if not status:
                            status = xhs_download(filepath)
                        if status:
                            break
                else:
                    status = False

                if status:
                    self.root.after(0, lambda: self._log(f"✅ 数据导出成功：{filepath}"))

                    # 处理数据
                    if platform == '淘宝':
                        tb_deal_data(shop_name, filepath)
                    elif platform == '拼多多':
                        pdd_deal_data(shop_name, filepath)
                    elif platform == '抖店':
                        dd_deal_data(shop_name, status)
                    elif platform == '微店':
                        wd_deal_data(shop_name, filepath)
                    elif platform == '小红书':
                        xhs_deal_data(shop_name, filepath)

                    self.root.after(0, lambda: self.status_var.set("导出完成"))
                else:
                    self.root.after(0, lambda: self._log("❌ 数据导出失败"))
                    self.root.after(0, lambda: self.status_var.set("导出失败"))

            except Exception as e:
                self.root.after(0, lambda: self._log(f"❌ 导出异常：{e}"))
                self.root.after(0, lambda: self.status_var.set("导出异常"))

        threading.Thread(target=do_export, daemon=True).start()

    def _total_data(self):
        """数据汇总"""
        if not messagebox.askyesno("确认", "确定要执行数据汇总吗？"):
            return

        self._log("开始数据汇总...")
        self.status_var.set("汇总中...")

        def do_total():
            try:
                from total_info import run
                run()
                self.root.after(0, lambda: self._log("✅ 数据汇总完成"))
                self.root.after(0, lambda: self.status_var.set("汇总完成"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"❌ 汇总异常：{e}"))
                self.root.after(0, lambda: self.status_var.set("汇总异常"))

        threading.Thread(target=do_total, daemon=True).start()


def main():
    root = tk.Tk()
    app = AccountManagerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
