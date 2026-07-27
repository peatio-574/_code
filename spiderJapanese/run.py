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
from concurrent.futures import ThreadPoolExecutor, as_completed
from openpyxl import load_workbook
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
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        self.file_path = None
        self.is_running = False
        self.stop_flag = False
        self.log_queue = queue.Queue()

        self.file_label = None
        self.thread_var = None
        self.thread_spinbox = None
        self.start_btn = None
        self.stop_btn = None
        self.clear_btn = None
        self.progress = None
        self.status_label = None
        self.log_text = None

        self.start_time = time.time()
        self.end_time = None
        self.token = None

        self.create_widgets()
        self.poll_log_queue()

    def create_widgets(self):
        """可视化界面"""
        file_frame = tk.LabelFrame(self.root, text="数据文件", padx=10, pady=10)
        file_frame.pack(fill=tk.X, padx=10, pady=5)

        self.file_label = tk.Label(file_frame, text="未选择文件")
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        select_btn = tk.Button(file_frame, text="选择 xlsx 文件", command=self.select_file)
        select_btn.pack(side=tk.RIGHT, padx=5)

        thread_frame = tk.LabelFrame(self.root, text="线程设置", padx=10, pady=10)
        thread_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(thread_frame, text="并发数:").pack(side=tk.LEFT, padx=5)
        self.thread_var = tk.StringVar(value="10")
        self.thread_spinbox = tk.Spinbox(thread_frame, from_=1, to=20, width=5, textvariable=self.thread_var)
        self.thread_spinbox.pack(side=tk.LEFT, padx=5)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.start_btn = tk.Button(btn_frame, text="开始", command=self.start_task, bg="#4CAF50", fg="white", width=10)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="停止", command=self.stop_task, bg="#f44336", fg="white", width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = tk.Button(btn_frame, text="清空日志", command=self.clear_log, width=10)
        self.clear_btn.pack(side=tk.RIGHT, padx=5)

        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=tk.X, padx=10, pady=5)

        self.status_label = tk.Label(self.root, text="就绪")
        self.status_label.pack(padx=10, anchor=tk.W)

        log_frame = tk.LabelFrame(self.root, text="执行日志", padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

    def select_file(self):
        """选择文件"""
        file_path = filedialog.askopenfilename(
            title="选择 xlsx 文件",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            self.file_path = file_path
            self.file_label.config(text=os.path.basename(file_path))
            self.log(f"已选择文件: {file_path}")

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

    def get_profile_ids(self):
        user_id_str = get_config_value('login', 'user_id', file=config_file)
        if not user_id_str:
            self.log("错误: 未配置 user_id")
            return []
        profile_ids = [pid.strip() for pid in user_id_str.split(',') if pid.strip()]
        return profile_ids

    def start_task(self):
        if not self.file_path:
            self.log("错误: 请先选择数据文件")
            return

        if self.is_running:
            self.log("任务正在运行中")
            return

        self.is_running = True
        self.stop_flag = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        thread = threading.Thread(target=self.run_task)
        thread.daemon = True
        thread.start()

    def stop_task(self):
        self.stop_flag = True
        self.log("正在停止任务...")
        self.stop_btn.config(state=tk.DISABLED)

    def run_task(self):
        try:
            self.log("开始执行任务...")

            profile_ids = self.get_profile_ids()
            if not profile_ids:
                self.reset_ui()
                return

            self.log(f"可用指纹浏览器: {len(profile_ids)}个")

            data = ReadData.read_xlsx_row(self.file_path)
            if not data:
                self.log("错误: 读取数据文件失败")
                self.reset_ui()
                return

            self.log(f"共读取{len(data)}条数据")

            wb = load_workbook(self.file_path)
            ws = wb.active
            total = len(data)
            completed = [0]
            lock = threading.Lock()

            max_workers = min(int(self.thread_var.get()), len(profile_ids))
            self.log(f"启动{max_workers}个线程并发执行")

            def process_row(row_id, row, profile_id):
                if self.stop_flag:
                    return

                email = row.get('邮箱', '')
                account_code = row.get('编号', '')
                account_code = f"{account_code}_{email}" if account_code else email
                email_url = row.get('邮箱验证地址', '')
                password = row.get('密码', '')

                self.log(f"[{profile_id}] 正在处理: {account_code}")

                try:
                    sp = SpecialPlayWright(config_file=config_file, profile_id=profile_id)
                    status = self.login_account(sp, account_code, email, password, email_url)
                    sp.clear_cookie()
                except Exception as e:
                    self.log(f"[{profile_id}] {account_code} 异常: {str(e)}")
                    status = False

                with lock:
                    ws.cell(row=row_id, column=5, value=1 if status else 0)
                    ws.cell(row=row_id, column=6, value=status)

                    wb.save(self.file_path)
                    completed[0] += 1
                    self.update_progress(completed[0], total)

                result = "成功" if status else "失败"
                self.log(f"[{profile_id}] 结果: {account_code} - {result}")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for row_id, row in enumerate(data, start=2):
                    if self.stop_flag:
                        break
                    profile_id = profile_ids[(row_id - 2) % len(profile_ids)]
                    future = executor.submit(process_row, row_id, row, profile_id)
                    futures.append(future)

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        self.log(f"线程异常: {str(e)}")

            self.log("任务执行完成")

        except Exception as e:
            self.log(f"错误: {str(e)}")
        finally:
            self.reset_ui()

    def reset_ui(self):
        self.is_running = False
        self.stop_flag = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def login_account(self, sp, account_code, email, password, email_url):
        try:
            self.log(f"{account_code}: 开始登录...")

            enter_verify = False
            for roll in range(3):
                if self.stop_flag:
                    return False
                self.log(f"{account_code}: 第{roll+1}次尝试输入账号密码")
                enter_verify = self.input_info(sp, email, password)
                if enter_verify:
                    break

            if not enter_verify:
                self.log(f"{account_code}: 登录失败 - 未进入验证码页面")
                return False

            verify_code = False
            time.sleep(10)
            for roll in range(10):
                if self.stop_flag:
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

            if status:
                self.log(f"✅️ {account_code}: 登录成功")
                status = sp.context.cookies()
                time.sleep(100000)
            else:
                self.log(f"❌️ {account_code}: 登录失败")

            return status

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

    def verify_phone(self, sp):
        try:
            sp.click('//div[@class="topBox"]//a[contains(@href, "mypage")]') # 点击我的
            sp.click('//form[@class="sendCertification-form"]') # 点击电话验证

            submit_ele = '//a[@name="smsSubmit"]'
            success = sp.wait_for_selector(submit_ele, timeout=10*1000)
            if not success:
                self.log('电话号码验证页面跳转失败')
                return False
            
            sp.click(submit_ele)

            phone_ele = ''
            success = sp.wait_for_selector(phone_ele, timeout=10*1000)
            if not success:
                self.log('发送获取电话号码验证失败')
                return False

            phone = self.get_phone_code('')
            sp.input(phone_ele, phone)
            sp.click('//input[@type="submit"]')  # 确认

            success = sp.wait_for_selector('//div[@class="comBtn"]', timeout=10*1000)
            return success
        except Exception as e:
            self.log(f'验证电话号码流程异常：{e}')
            return False

    def get_phone_code(self, phone):
        """获取电话验证码"""
        try:
            url = f'https://test3.zmdybwl.top/ajax/getYzm?id={phone}'
            response = requests.get(url=url, headers=self.headers)
            phone_code = response.json()['yzm']
            return phone_code
        except Exception as e:
            self.log(f'【{phone}】电话验证码获取失败：{e}')
            return False

    def get_phone(self):
        """获取电话号码"""
        try:
            url = f'https://test3.zmdybwl.top/simadmin/sqlb_data?id=&page=1&limit=50'
            headers = {
                'Authorization': f'Bearer {self.get_token()}',
            }
            response = requests.get(url=url, headers=headers).json()
            print(response)

            # phone_code = response.json()['username']
            return response
        except Exception as e:
            self.log(f'【】电话获取失败：{e}')
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
    app.get_phone()
    # root.mainloop()

