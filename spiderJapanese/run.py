# coding='utf-8'
import sys
import os

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = BUNDLE_DIR

parent_dir = os.path.join(BASE_DIR, '..')
sys.path.insert(0, BUNDLE_DIR)
sys.path.insert(0, parent_dir)

import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
import threading

from newPlayWright import SpecialPlayWright
from Config import get_config_value
from ReadFile import ReadData
import re
import time
import requests
import queue

config_file = os.path.join(BASE_DIR, 'config.ini')


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("宝可梦 登录工具")
        self.root.geometry("900x700")
        self.root.resizable(True, True)

        self.file_path = None
        self.userid_file_path = None
        self.is_running = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.task_epoch = 0
        self.log_queue = queue.Queue()
        self.phone_queue_list = []
        self.phone_queue_lock = threading.Lock()

        self.userid_file_label = None
        self.file_label = None
        self.thread_var = None
        self.thread_spinbox = None
        self.start_btn = None
        self.pause_btn = None
        self.stop_btn = None
        self.clear_btn = None
        self.queue_listbox = None
        self.account_tree = None
        self.progress = None
        self.status_label = None
        self.log_text = None

        self.start_time = time.time()
        self.end_time = None
        self.token = None
        self.create_widgets()
        self.poll_log_queue()
        self.poll_queue_display()

    def create_widgets(self):
        config_frame = tk.LabelFrame(self.root, text="配置信息", padx=10, pady=10)
        config_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(config_frame, text="UserID 文件:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.userid_file_label = tk.Label(config_frame, text="未选择文件", anchor=tk.W)
        self.userid_file_label.grid(row=0, column=1, padx=5, pady=3, sticky=tk.W+tk.E)
        select_userid_btn = tk.Button(config_frame, text="选择", command=self.select_userid_file, width=8)
        select_userid_btn.grid(row=0, column=2, padx=5, pady=3)

        tk.Label(config_frame, text="账号文件:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.file_label = tk.Label(config_frame, text="未选择文件", anchor=tk.W)
        self.file_label.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W+tk.E)
        select_btn = tk.Button(config_frame, text="选择", command=self.select_file, width=8)
        select_btn.grid(row=1, column=2, padx=5, pady=3)

        tk.Label(config_frame, text="并发数:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        self.thread_var = tk.StringVar(value="3")
        self.thread_spinbox = tk.Spinbox(config_frame, from_=1, to=20, width=5, textvariable=self.thread_var)
        self.thread_spinbox.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)

        config_frame.columnconfigure(1, weight=1)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.start_btn = tk.Button(btn_frame, text="开始", command=self.start_task, bg="#4CAF50", fg="white", width=10)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = tk.Button(btn_frame, text="暂停", command=self.toggle_pause, bg="#FF9800", fg="white", width=10, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="停止", command=self.stop_task, bg="#f44336", fg="white", width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = tk.Button(btn_frame, text="清空日志", command=self.clear_log, width=10)
        self.clear_btn.pack(side=tk.RIGHT, padx=5)

        status_frame = tk.Frame(self.root)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        queue_frame = tk.LabelFrame(status_frame, text="电话号码队列", padx=5, pady=5)
        queue_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.queue_listbox = tk.Listbox(queue_frame, height=8, font=("Consolas", 9))
        self.queue_listbox.pack(fill=tk.BOTH, expand=True)
        queue_scroll = tk.Scrollbar(self.queue_listbox)
        queue_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.queue_listbox.config(yscrollcommand=queue_scroll.set)
        queue_scroll.config(command=self.queue_listbox.yview)

        account_frame = tk.LabelFrame(status_frame, text="账号状态", padx=5, pady=5)
        account_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        columns = ('account', 'email', 'status')
        self.account_tree = ttk.Treeview(account_frame, columns=columns, show='headings', height=8)
        self.account_tree.heading('account', text='编号')
        self.account_tree.heading('email', text='邮箱')
        self.account_tree.heading('status', text='状态')
        self.account_tree.column('account', width=80)
        self.account_tree.column('email', width=160)
        self.account_tree.column('status', width=70, anchor=tk.CENTER)
        self.account_tree.pack(fill=tk.BOTH, expand=True)
        tree_scroll = tk.Scrollbar(self.account_tree, orient=tk.VERTICAL, command=self.account_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.account_tree.configure(yscrollcommand=tree_scroll.set)

        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=tk.X, padx=10, pady=2)

        self.status_label = tk.Label(self.root, text="就绪")
        self.status_label.pack(padx=10, anchor=tk.W)

        log_frame = tk.LabelFrame(self.root, text="执行日志", padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 xlsx 文件",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            self.file_path = file_path
            self.file_label.config(text=os.path.basename(file_path))
            self.log(f"已选择文件: {file_path}")
            self.populate_accounts()

    def select_userid_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 UserID xlsx 文件",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            self.userid_file_path = file_path
            self.userid_file_label.config(text=os.path.basename(file_path))
            ids = self.get_user_ids()
            self.log(f"已选择 UserID 文件: {file_path}, 共 {len(ids)} 个 ID")

    def toggle_pause(self):
        if self.is_paused:
            self.is_paused = False
            self.pause_event.clear()
            self.pause_btn.config(text="暂停")
            self.log("任务继续")
        else:
            self.is_paused = True
            self.pause_event.set()
            self.pause_btn.config(text="继续")
            self.log("任务暂停")

    def poll_queue_display(self):
        self.queue_listbox.delete(0, tk.END)
        with self.phone_queue_lock:
            for phone in self.phone_queue_list[-100:]:
                self.queue_listbox.insert(tk.END, phone)
        self.root.after(1000, self.poll_queue_display)

    def update_account_status(self, account_code, status):
        def _update():
            for item in self.account_tree.get_children():
                values = self.account_tree.item(item, 'values')
                if values and values[0] == account_code:
                    self.account_tree.item(item, values=(values[0], values[1], status))
                    break
        self.root.after(0, _update)

    def populate_accounts(self):
        if not self.file_path:
            return
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        data = ReadData.read_xlsx_row(self.file_path)
        if data:
            for row in data:
                email = row.get('邮箱', '')
                account_code = row.get('编号', '')
                account_code = f"{account_code}_{email}" if account_code else email
                self.account_tree.insert('', tk.END, values=(account_code, email, '等待'))
            self.log(f"已加载 {len(data)} 个账号")

    def log(self, message):
        self.log_queue.put(message)

    def poll_log_queue(self):
        while not self.log_queue.empty():
            message = self.log_queue.get_nowait()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(100, self.poll_log_queue)

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_progress(self, current, total):
        if total > 0:
            progress_value = (current / total) * 100
            self.progress['value'] = progress_value
            self.status_label.config(text=f"进度: {current}/{total}")

    def get_user_ids(self):
        if self.userid_file_path:
            try:
                rows = ReadData.read_xlsx_row(self.userid_file_path)
                if rows:
                    return [list(row.values())[0] for row in rows if list(row.values())[0]]
            except Exception as e:
                self.log(f"读取 UserID 文件失败: {e}")
        user_id_str = get_config_value('login', 'user_id', file=config_file)
        if not user_id_str:
            self.log("错误: 未配置 user_id，请选择 UserID 文件或在 config.ini 中配置")
            return []
        user_ids = [pid.strip() for pid in user_id_str.split(',') if pid.strip()]
        return user_ids

    def start_task(self):
        if not self.file_path:
            self.log("错误: 请先选择数据文件")
            return

        if self.is_running:
            self.log("任务正在运行中")
            return

        self.is_running = True
        self.is_paused = False
        self.stop_event.clear()
        self.pause_event.clear()
        self.task_epoch += 1
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL, text="暂停")
        self.stop_btn.config(state=tk.NORMAL)

        user_ids = self.get_user_ids()
        id_source = os.path.basename(self.userid_file_path) if self.userid_file_path else "config.ini"
        config_info = f"UserID 来源: {id_source} | 并发: {self.thread_var.get()} | 浏览器: {len(user_ids)}个"
        self.log(f"配置信息: {config_info}")

        self.populate_accounts()
        with self.phone_queue_lock:
            self.phone_queue_list.clear()
        self.queue_listbox.delete(0, tk.END)

        thread = threading.Thread(target=self.run_task)
        thread.daemon = True
        thread.start()

    def stop_task(self):
        self.stop_event.set()
        self.pause_event.clear()
        self.log("正在停止任务...")
        self.stop_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)

    def run_task(self):
        try:
            self.log("开始执行任务...")

            user_ids = self.get_user_ids()
            if not user_ids:
                self.reset_ui()
                return

            self.log(f"可用指纹浏览器: {len(user_ids)}个")

            data = ReadData.read_xlsx_row(self.file_path)
            if not data:
                self.log("错误: 读取数据文件失败")
                self.reset_ui()
                return

            self.log(f"共读取{len(data)}条账户数据")

            phone_queue = queue.Queue()
            lock = threading.Lock()
            processed_count = [0]
            failed_count = [0]
            account_index = [0]
            max_workers = min(int(self.thread_var.get()), len(user_ids))
            self.log(f"启动{max_workers}个并发线程")

            def fetch_phones_loop():
                epoch = self.task_epoch
                while not self.stop_event.is_set() and self.task_epoch == epoch:
                    while self.pause_event.is_set() and not self.stop_event.is_set():
                        time.sleep(0.5)
                    try:
                        phones = self.get_phone()
                        if phones:
                            for phone in phones:
                                phone_queue.put(phone)
                                with self.phone_queue_lock:
                                    self.phone_queue_list.append(phone['data'])
                                self.log(f"加入队列: {phone['data']}")
                    except Exception as e:
                        self.log(f"获取电话异常: {e}")
                    time.sleep(10)

            fetcher = threading.Thread(target=fetch_phones_loop, daemon=True)
            fetcher.start()

            def worker_loop(user_id, epoch):
                while not self.stop_event.is_set() and self.task_epoch == epoch:
                    while self.pause_event.is_set() and not self.stop_event.is_set():
                        time.sleep(0.5)
                    if self.stop_event.is_set() or self.task_epoch != epoch:
                        break
                    phone_item = None
                    try:
                        phone_item = phone_queue.get(timeout=1)
                    except queue.Empty:
                        continue

                    phone_code = phone_item['data']
                    phone_id = phone_item['id']

                    with self.phone_queue_lock:
                        if phone_code in self.phone_queue_list:
                            self.phone_queue_list.remove(phone_code)
                    self.log(f"[{user_id}] 处理: {phone_code}")

                    success = False
                    try:
                        sp = SpecialPlayWright(config_file=config_file, user_id=user_id)

                        login_ok = False
                        login_attempts = 0
                        while not login_ok and not self.stop_event.is_set():
                            while self.pause_event.is_set() and not self.stop_event.is_set():
                                time.sleep(0.5)
                            if self.stop_event.is_set() or self.task_epoch != epoch:
                                break
                            with lock:
                                if account_index[0] >= len(data) * 3:
                                    break
                                row = data[account_index[0] % len(data)]
                                account_index[0] += 1
                                email = row.get('邮箱', '')
                                account_code = row.get('编号', '')
                                account_code = f"{account_code}_{email}" if account_code else email
                                email_url = row.get('邮箱验证地址', '')
                                password = row.get('密码', '')

                            if login_attempts > 0:
                                sp.close()
                                sp = SpecialPlayWright(config_file=config_file, user_id=user_id)

                            login_attempts += 1
                            self.update_account_status(account_code, '登录中')
                            self.log(f"[{user_id}] 尝试登录({login_attempts}): {account_code}")
                            login_ok = self.login_account(sp, account_code, email, password, email_url)
                            if login_ok:
                                self.update_account_status(account_code, '登录成功')
                            else:
                                self.update_account_status(account_code, '登录失败')

                        if not login_ok:
                            self.log(f"[{user_id}] {phone_code} 所有账号登录失败")
                            sp.clear_cookie()
                            with lock:
                                failed_count[0] += 1
                            self.root.after(0, lambda: self.status_label.config(
                                text=f"成功: {processed_count[0]} | 失败: {failed_count[0]} | 总计: {processed_count[0] + failed_count[0]}"))
                            continue

                        modify_ok = self.modify_phone(sp, phone_code)
                        if not modify_ok:
                            self.log(f"[{user_id}] {phone_code} 修改电话失败")
                            sp.clear_cookie()
                            with lock:
                                failed_count[0] += 1
                            self.root.after(0, lambda: self.status_label.config(
                                text=f"成功: {processed_count[0]} | 失败: {failed_count[0]} | 总计: {processed_count[0] + failed_count[0]}"))
                            continue

                        verify_ok = self.verify_phone(sp, phone_id)
                        if verify_ok:
                            success = True
                            self.log(f"[{user_id}] {phone_code} 完成")
                        else:
                            self.log(f"[{user_id}] {phone_code} 验证失败，替换号码")
                            try:
                                retry_item = phone_queue.get(timeout=1)
                                retry_phone = retry_item['data']
                                retry_id = retry_item['id']
                                with self.phone_queue_lock:
                                    if retry_phone in self.phone_queue_list:
                                        self.phone_queue_list.remove(retry_phone)
                                self.log(f"[{user_id}] 替换为: {retry_phone}")
                                modify_ok = self.modify_phone(sp, retry_phone)
                                if modify_ok:
                                    verify_ok = self.verify_phone(sp, retry_id)
                                    if verify_ok:
                                        success = True
                                        self.log(f"[{user_id}] {retry_phone} 完成")
                                    else:
                                        self.log(f"[{user_id}] {retry_phone} 验证失败")
                                else:
                                    self.log(f"[{user_id}] {retry_phone} 修改失败")
                            except queue.Empty:
                                self.log(f"[{user_id}] 队列无可用替换号码")

                        sp.clear_cookie()
                    except Exception as e:
                        self.log(f"[{user_id}] {phone_code} 异常: {str(e)}")

                    with lock:
                        if success:
                            processed_count[0] += 1
                        else:
                            failed_count[0] += 1
                        total = processed_count[0] + failed_count[0]
                    self.root.after(0, lambda p=processed_count[0], f=failed_count[0]: (
                        self.progress.__setitem__('value', p % 100),
                        self.status_label.config(text=f"成功: {p} | 失败: {f} | 总计: {p + f}")))

            epoch = self.task_epoch
            threads = []
            for user_id in user_ids[:max_workers]:
                t = threading.Thread(target=worker_loop, args=(user_id, epoch), daemon=True)
                t.start()
                threads.append(t)

            while not self.stop_event.is_set():
                self.stop_event.wait(1)

            self.log(f"任务停止. 成功: {processed_count[0]}, 失败: {failed_count[0]}")

        except Exception as e:
            self.log(f"错误: {str(e)}")
        finally:
            self.reset_ui()

    def reset_ui(self):
        self.is_running = False
        self.is_paused = False
        self.pause_event.clear()
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED, text="暂停")
        self.stop_btn.config(state=tk.DISABLED)

    def login_account(self, sp, account_code, email, password, email_url):
        try:
            self.log(f"{account_code}: 开始登录...")

            enter_verify = False
            for roll in range(3):
                if self.stop_event.is_set():
                    return False
                self.log(f"{account_code}: 第{roll+1}次尝试输入账号密码")
                enter_verify = self.input_info(sp, email, password)
                if enter_verify:
                    break

            if not enter_verify:
                self.log(f"{account_code}: 登录失败 - 未进入验证码页面")
                return False

            verify_code = False
            if not self.stop_event.is_set():
                self.stop_event.wait(10)
            for roll in range(10):
                if self.stop_event.is_set():
                    return False
                self.log(f"{account_code}: 第{roll+1}次尝试获取邮箱验证码")
                verify_code = self.get_email_code(sp, email_url)
                if verify_code:
                    break

            if not verify_code:
                self.log(f"{account_code}: 登录失败 - 获取邮箱验证码失败")
                return False

            self.log(f"{account_code}: 验证码: {verify_code}")
            sp.input('//input[@id="authCode"]', verify_code)
            sp.click('//input[@id="rememberMe"]')
            sp.click('//a[@id="authBtn"]')
            status = sp.wait_for_selector('//ul[@class="tabUl flex"]', timeout=15*1000)
            if not status:
                self.log(f"{account_code}: 输入邮箱验证码后，未登录成功")
                return False

            self.log(f"{account_code}: 登录成功")
            return True
            
        except Exception as e:
            self.log(f"{account_code}: 登录异常: {str(e)}")
            return False

    def input_info(self, sp, email, password):
        """输入账号密码点击确认"""
        try:
            url = 'https://www.pokemoncenter-online.com/login/'
            sp.goto(url)

            email_ele = '//input[@type="email" and @id="login-form-email"]'
            sp.wait_for_selector(email_ele, timeout=10*1000)

            sp.input(email_ele, email)
            sp.input('//input[@type="password" and @id="current-password"]', password)
            sp.click('//button[@type="submit" and @class="btn btn-block btn-primary"]')

            success = sp.wait_for_selector('//input[@id="authCode"]', timeout=10*1000)
            return success
        except Exception as e:
            self.log(f"输入账号密码流程异常: {str(e)}")
            return False

    def get_email_code(self, sp, api_url):
        """获取邮箱验证码"""
        try:
            sp.new_goto(api_url, close=False)

            verify_code_ele = '//div[@class="email-content"]/div[1]/div/p[3]'
            success = sp.wait_for_selector(verify_code_ele, timeout=10*1000)

            if success:
                text = sp.get_text(verify_code_ele)
                verify_code = re.findall(r'\d+', text)[0]
                success = verify_code

            sp.switch_page('old')
            return success
        except Exception as e:
            self.log(f"获取邮箱验证码流程异常: {str(e)}")
            return False

    def modify_phone(self, sp, phone):
        """修改电话号码"""
        try:
            sp.click('//a[@class="editProfile "]')  # 点击信息变更

            phone_ele = '//input[@class="js-validate telNumber form-control"]'
            success = sp.wait_for_selector(phone_ele, timeout=10*1000)
            if not success:
                self.log('电话号码修改页面跳转失败')
                return False

            sp.mouse_wheel(1000)

            sp.input(phone_ele, phone)  # 输入电话号码
            confirm_ele = '//button[@class="submitButton"]'
            sp.click(confirm_ele)  # 点击确认

            success = sp.wait_for_selector(confirm_ele, timeout=6*1000)
            if not success:
                self.log('点击确认修改电话号码，跳转失败')
                return False

            sp.mouse_wheel(1000)
            sp.click(confirm_ele)  # 点击确认

            success = sp.wait_for_selector('//ul[@class="linkList"]/li/a[@href="/"]', timeout=10*1000)

            return success
        except Exception as e:
            self.log(f"修改手机号流程异常：{str(e)}")
            return False

    def verify_phone(self, sp, phone_id):
        try:
            sp.click('//div[@class="topBox"]//a[contains(@href, "mypage")]')
            sp.click('//form[@class="sendCertification-form"]')

            submit_ele = '//a[@name="smsSubmit"]'
            success = sp.wait_for_selector(submit_ele, timeout=10*1000)
            if not success:
                self.log('电话号码验证页面跳转失败')
                return False

            sp.click(submit_ele)

            phone_ele = '//input[@name="certificationCode"]'
            success = sp.wait_for_selector(phone_ele, timeout=15*1000)
            if not success:
                self.log('发送获取电话号码验证失败')
                return False

            code = self.get_phone_code(phone_id)
            if not code:
                self.log(f'获取手机验证码失败: {phone_id}')
                return False

            sp.input(phone_ele, code)
            sp.click('//input[@type="submit"]')

            success = sp.wait_for_selector('//div[@class="comBtn"]', timeout=10*1000)
            return success
        except Exception as e:
            self.log(f'验证电话号码流程异常：{e}')
            return False

    def get_phone_code(self, phone_id):
        """获取电话验证码"""
        try:
            headers = {
                'Authorization': f'Bearer {self.get_token()}',
            }
            url = f'https://test3.zmdybwl.top/ajax/getYzm?id={phone_id}'
            response = requests.post(url=url, headers=headers)

            phone_code = response.json()['yzm']
            return phone_code
        except Exception as e:
            self.log(f'【{phone_id}】电话验证码获取失败：{e}')
            print(f'【{phone_id}】电话验证码获取失败：{e}')
            return False

    def get_phone(self):
        """获取电话号码"""
        try:
            url = f'https://test3.zmdybwl.top/simadmin/sqlb_data?page=1&limit=50'
            headers = {
                'Authorization': f'Bearer {self.get_token()}',
            }
            self.log(headers)
            response = requests.get(url=url, headers=headers).json()['data']
            data = [{'time': i['time'], 'data': eval(i['data1'])['username'], 'id': i['id']} for i in response]
            print(data)
            return data
        except Exception as e:
            self.log(f'电话获取失败：{e}')
            return False

    def get_token(self):
        """获取token"""
        self.end_time = time.time()
        if self.end_time - self.start_time <= 110 * 60 and self.token:
            return self.token
        # 超过110分钟失效
        try:
            url = 'https://test3.zmdybwl.top/simlogin/login'
            params = {
                'username': 'admin',
                'password': 'admin123',
            }
            response = requests.post(url=url, data=params)
            token = response.json()['token']
            self.token = token
            self.start_time = time.time()
            return self.token
        except Exception as e:
            self.log(f'token获取异常：{e}')
            return False




if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.mainloop()

