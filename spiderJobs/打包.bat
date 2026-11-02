@echo off
chcp 936 >nul 2>nul
setlocal EnableDelayedExpansion

rem ============================================================
rem  Jobs 打包脚本（PyInstaller 单文件 exe）
rem
rem  体积优化要点：
rem    * 只保留 patchright 一个浏览器驱动，排除 playwright（省约 106MB）
rem    * 去掉驱动包里运行时用不到的部分：types/*.d.ts、lib/vite/**、
rem      traceViewer/recorder/dashboard（约 2.9MB）、*.map/*.md/*.sh 等
rem    * --optimize 2 去掉 docstring 与 assert
rem    * 排除 numpy/pandas/scipy/matplotlib/IPython 等重量级依赖
rem    * 提供 UPX_DIR 可再压 30-50%%（可选）
rem
rem  exe 同目录（外部可读写）：
rem    config.ini / logs\ / *.xlsx
rem    医护知音图片\  医护知音附件\  wechat_links.json   <- 医护知音采集用
rem  config\*.json 打进 exe
rem ============================================================

set "APP_NAME=Jobs"
set "ENTRY=getJobs.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "WORK_DIR=%BUILD_DIR%\work"
set "HOOK_DIR=%BUILD_DIR%\hooks"

if not defined PYTHON set "PYTHON=d:\_code\python\python.exe"
if not defined PIP_MIRROR set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
rem 字节码优化级别：2 = 去掉 docstring + 断言，体积更小
if not defined OPTIMIZE set "OPTIMIZE=2"

cd /d "%~dp0"

rem ============ 1. 检查 Python ============
echo.
echo [1/6] 检查 Python...
set "PY_OK=0"
if exist "%PYTHON%" set "PY_OK=1"
if "%PY_OK%"=="0" (
    where "%PYTHON%" >nul 2>nul
    if not errorlevel 1 set "PY_OK=1"
)
if "%PY_OK%"=="0" goto :no_python
"%PYTHON%" -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)" >nul 2>nul
if errorlevel 1 goto :bad_python
"%PYTHON%" -c "import sys;print('  Python ' + sys.version.split()[0] + '  (' + sys.executable + ')')"

rem ============ 2. 检查 PyInstaller 与依赖 ============
echo.
echo [2/6] 检查 PyInstaller 与依赖...
"%PYTHON%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo   未安装，正在安装...
    "%PYTHON%" -m pip install --upgrade pyinstaller -i "%PIP_MIRROR%"
    if errorlevel 1 goto :fail
)
"%PYTHON%" -c "import PyInstaller;print('  PyInstaller', PyInstaller.__version__)"
rem 用 patchright 作为唯一浏览器驱动，playwright 会被排除
"%PYTHON%" -c "import requests, openpyxl, patchright" >nul 2>nul
if errorlevel 1 (
    echo   缺少依赖，正在安装...
    "%PYTHON%" -m pip install requests openpyxl beautifulsoup4 patchright -i "%PIP_MIRROR%"
    if errorlevel 1 goto :fail
)
"%PYTHON%" -c "import ttkbootstrap" >nul 2>nul
if errorlevel 1 (
    echo   安装 ttkbootstrap（界面主题）...
    "%PYTHON%" -m pip install ttkbootstrap -i "%PIP_MIRROR%"
)
rem winsdk 用于医护知音的图片 OCR 预筛（Windows 自带 OCR 的 Python 绑定）。
rem 装不上不影响打包，只是运行时退化成"所有图片都送 AI"。
"%PYTHON%" -c "import winsdk" >nul 2>nul
if errorlevel 1 (
    echo   安装 winsdk（图片 OCR 预筛）...
    "%PYTHON%" -m pip install winsdk -i "%PIP_MIRROR%"
    if errorlevel 1 echo   [警告] winsdk 安装失败，医护知音将跳过 OCR 预筛
)
echo   依赖齐全

rem ============ 3. 清理旧产物 ============
echo.
echo [3/6] 清理旧产物...
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%BUILD_DIR%\*.spec" del /f /q "%BUILD_DIR%\*.spec" >nul 2>nul
if not exist "%HOOK_DIR%" mkdir "%HOOK_DIR%" >nul 2>nul
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%" >nul 2>nul
if exist "%DIST_DIR%\%APP_NAME%.exe" del /f /q "%DIST_DIR%\%APP_NAME%.exe" >nul 2>nul
echo   完成

rem ============ 4. 生成裁剪 hook ============
rem patchright 官方 hook 用 collect_data_files 会把整个 driver（约 103MB）打进去，
rem 但运行时只用得到其中一部分：types（1.9MB 的 .d.ts）、lib\vite（2.9MB 的
rem traceViewer/recorder/dashboard 前端页面），以及大量 map/md/sh/css/ttf。
echo.
echo [4/6] 生成裁剪用的 hook...
call :write_hook "hook-patchright.sync_api.py" "patchright"
call :write_hook "hook-patchright.async_api.py" "patchright"
call :write_hook "hook-patchright._impl.py" "patchright"
call :write_pil_hook
call :write_winsdk_hook
echo   已排除: types / lib\vite / *.d.ts / *.map / *.md / *.sh / *.css / *.ttf
echo   PIL: 只保留常用格式，排除 AVIF/MPO
echo   winsdk: 收集 Windows OCR 所需命名空间

rem ============ 5. 打包 ============
echo.
echo [5/6] 开始打包（约 1-3 分钟）...
set "UPX_ARG=--noupx"
if defined UPX_DIR if exist "%UPX_DIR%" set "UPX_ARG=--upx-dir \"%UPX_DIR%\""

rem 注意：不要 exclude asyncio / asyncio.tasks，zhipin 异步采集依赖它
rem 注意：不要 exclude bs4，ncss 用它解析网页
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%WORK_DIR%" ^
    --specpath "%BUILD_DIR%" ^
    --additional-hooks-dir "%HOOK_DIR%" ^
    --optimize %OPTIMIZE% ^
    --log-level WARN ^
    --paths "." ^
    --paths ".." ^
    --add-data "%~dp0config\*.json;config" ^
    --hidden-import "Logger" ^
    --hidden-import "Config" ^
    --hidden-import "PatchRightClass" ^
    --hidden-import "guopin" ^
    --hidden-import "ncss" ^
    --hidden-import "zhipin" ^
    --hidden-import "Boss" ^
    --hidden-import "wechat" ^
    --hidden-import "requests" ^
    --hidden-import "openpyxl" ^
    --hidden-import "screeninfo" ^
    --hidden-import "patchright" ^
    --hidden-import "patchright.sync_api" ^
    --hidden-import "patchright.async_api" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.simpledialog" ^
    --hidden-import "tkinter.messagebox" ^
    --hidden-import "tkinter.filedialog" ^
    --hidden-import "ttkbootstrap" ^
    --hidden-import "winsdk" ^
    --hidden-import "winsdk.windows.media.ocr" ^
    --hidden-import "winsdk.windows.graphics.imaging" ^
    --hidden-import "winsdk.windows.storage" ^
    --hidden-import "winsdk.windows.globalization" ^
    --exclude-module "playwright" ^
    --exclude-module "cryptography" ^
    --exclude-module "cffi" ^
    --exclude-module "lxml" ^
    --exclude-module "pandas" ^
    --exclude-module "numpy" ^
    --exclude-module "scipy" ^
    --exclude-module "matplotlib" ^
    --exclude-module "IPython" ^
    --exclude-module "jupyter" ^
    --exclude-module "notebook" ^
    --exclude-module "pytest" ^
    --exclude-module "setuptools" ^
    --exclude-module "pkg_resources" ^
    --exclude-module "pip" ^
    --exclude-module "wheel" ^
    --exclude-module "unittest" ^
    --exclude-module "doctest" ^
    --exclude-module "lib2to3" ^
    --exclude-module "test" ^
    --exclude-module "pydoc_data" ^
    --exclude-module "xlsxwriter" ^
    --exclude-module "ensurepip" ^
    --exclude-module "venv" ^
    --exclude-module "idlelib" ^
    --exclude-module "turtle" ^
    --exclude-module "turtledemo" ^
    --exclude-module "distutils" ^
    --exclude-module "sqlite3" ^
    --exclude-module "curses" ^
    --exclude-module "multiprocessing" ^
    %UPX_ARG% ^
    "%ENTRY%"

if errorlevel 1 goto :fail
if not exist "%DIST_DIR%\%APP_NAME%.exe" goto :fail

rem ============ 6. 生成外部目录与说明 ============
echo.
echo [6/6] 生成外部目录与使用说明...
call :ensure_config
call :ensure_wechat_files
call :ensure_readme

for %%F in ("%DIST_DIR%\%APP_NAME%.exe") do set "EXE_SIZE=%%~zF"
set /a EXE_MB=%EXE_SIZE%/1048576
set /a EXE_KB=%EXE_SIZE%/1024

echo.
echo ============================================================
echo  打包完成
echo ============================================================
echo   EXE : %cd%\%DIST_DIR%\%APP_NAME%.exe
echo         约 %EXE_MB% MB（%EXE_KB% KB）
echo.
echo  exe 同目录下的文件（全部可外部读写）：
echo    config.ini         登录 Cookie，可直接编辑
echo    logs\              运行日志
echo    *.xlsx             采集结果
echo    医护知音图片\      文章配图（识别用，按文章分子目录）
echo    医护知音附件\      文章 xlsx 附件
echo    wechat_links.json  公众号文章链接清单（含抓取状态）
echo.
echo  图片先用 Windows 自带 OCR 粗筛，没有岗位信息的（封面/二维码/海报）
echo  直接跳过，只把像岗位表的图送去视觉模型识别。
echo.
echo  config\ 下的规则数据以 JSON 形式打进 exe，如需覆盖，
echo  在 exe 同目录放一个同名 config\ 与同名 JSON，优先使用外部文件。
echo.
echo  使用说明：
echo    * 首次运行会自动生成 config.ini 与 logs 目录
echo    * 浏览器用系统自带 Edge/Chrome，无需额外安装；
echo      若需指定，设置环境变量 PLAYWRIGHT_CHANNEL 为 msedge / chrome
echo ============================================================
echo.
pause
exit /b 0

rem ==================== 子过程 ====================

:write_hook
rem 生成裁剪版 hook：只排除运行时确实用不到的文件，不影响功能
rem 参数1 = hook 文件名，参数2 = 包名（patchright）
> "%HOOK_DIR%\%~1" echo from PyInstaller.utils.hooks import collect_data_files
>>"%HOOK_DIR%\%~1" echo datas = collect_data_files(
>>"%HOOK_DIR%\%~1" echo     "%~2",
>>"%HOOK_DIR%\%~1" echo     excludes=[
rem 类型声明：只给 IDE 用，运行时不需要（1.9MB）
>>"%HOOK_DIR%\%~1" echo         "driver/package/types/**/*",
rem 前端页面：traceViewer / recorder / dashboard，命令行用不到（2.9MB）
>>"%HOOK_DIR%\%~1" echo         "driver/package/lib/vite/**/*",
rem 自带浏览器内核目录 bin：用系统 Edge/Chrome 就不需要，体积很大所以排除
>>"%HOOK_DIR%\%~1" echo         "driver/package/bin/*",
rem 文档/脚本/样式/字体
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.d.ts",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.map",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.md",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.sh",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.ts",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.css",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.ttf",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.png",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.svg",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.license",
>>"%HOOK_DIR%\%~1" echo         "driver/package/**/*.LICENSE",
rem 字节码缓存与跨平台脚本
>>"%HOOK_DIR%\%~1" echo         "**/__pycache__/**",
>>"%HOOK_DIR%\%~1" echo         "**/*.ps1",
>>"%HOOK_DIR%\%~1" echo     ],
>>"%HOOK_DIR%\%~1" echo )
exit /b 0

:write_pil_hook
rem 覆盖 PyInstaller 自带的 hook-PIL.Image，避免把所有 ImagePlugin 都收进来
rem 排除 AVIF 等插件（PIL\_avif.pyd 约 7.5MB），本项目完全用不到
rem ttkbootstrap 只用得到 ImageColor / ImageDraw / ImageFont，这些仍然保留
> "%HOOK_DIR%\hook-PIL.Image.py" echo from PyInstaller.utils.hooks import collect_submodules
>>"%HOOK_DIR%\hook-PIL.Image.py" echo hiddenimports = collect_submodules(
>>"%HOOK_DIR%\hook-PIL.Image.py" echo     "PIL", lambda name: "ImagePlugin" in name)
>>"%HOOK_DIR%\hook-PIL.Image.py" echo excludedimports = [
>>"%HOOK_DIR%\hook-PIL.Image.py" echo     "PIL.AvifImagePlugin",
>>"%HOOK_DIR%\hook-PIL.Image.py" echo     "PIL.MpoImagePlugin",
>>"%HOOK_DIR%\hook-PIL.Image.py" echo     "PIL.BlpImagePlugin",
>>"%HOOK_DIR%\hook-PIL.Image.py" echo ]
exit /b 0

:write_winsdk_hook
rem winsdk 的命名空间是动态生成的，PyInstaller 静态分析扫不全，
rem 用 collect_submodules 一次性收齐，否则打出来的 exe 一调 OCR 就 ImportError。
> "%HOOK_DIR%\hook-winsdk.py" echo from PyInstaller.utils.hooks import collect_submodules
>>"%HOOK_DIR%\hook-winsdk.py" echo hiddenimports = collect_submodules("winsdk")
exit /b 0

:ensure_config
rem config.ini 放在 dist 目录（exe 同级）。已存在则保留，避免覆盖已登录的 Cookie
if exist "%DIST_DIR%\config.ini" (
    echo   config.ini 已存在，保留原文件
    exit /b 0
)
if exist "config.ini" (
    copy /y "config.ini" "%DIST_DIR%\config.ini" >nul
    echo   已复制 config.ini
    exit /b 0
)
rem 空白模板：各平台 Cookie 留空，首次运行登录后自动写入
> "%DIST_DIR%\config.ini" echo [login]
>>"%DIST_DIR%\config.ini" echo nscc_cookie =
>>"%DIST_DIR%\config.ini" echo nscc_cookie_api =
>>"%DIST_DIR%\config.ini" echo boss_cookie =
>>"%DIST_DIR%\config.ini" echo boss_cookie_api =
>>"%DIST_DIR%\config.ini" echo zhipin_cookie =
>>"%DIST_DIR%\config.ini" echo zhipin_cookie_api =
echo   已创建空白 config.ini 模板
exit /b 0

:ensure_wechat_files
rem 医护知音：图片、附件、链接清单全部放 exe 同目录，用户能直接打开查看和编辑。
rem 已存在的绝不覆盖 —— 链接清单里存着每篇文章的抓取状态，图片是下载缓存。
if not exist "%DIST_DIR%\医护知音图片" mkdir "%DIST_DIR%\医护知音图片" >nul 2>nul
if not exist "%DIST_DIR%\医护知音附件" mkdir "%DIST_DIR%\医护知音附件" >nul 2>nul
if exist "%DIST_DIR%\wechat_links.json" (
    echo   wechat_links.json 已存在，保留原文件
    exit /b 0
)
> "%DIST_DIR%\wechat_links.json" echo {}
echo   已创建空的 wechat_links.json（点「提取公众号链接」后自动填充）
exit /b 0

:ensure_readme
if exist "%DIST_DIR%\使用说明.txt" exit /b 0
> "%DIST_DIR%\使用说明.txt" echo 招聘数据采集系统 - 使用说明
>>"%DIST_DIR%\使用说明.txt" echo ========================================
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo 【启动】
>>"%DIST_DIR%\使用说明.txt" echo   双击 Jobs.exe 即可，无需安装环境。
>>"%DIST_DIR%\使用说明.txt" echo   浏览器使用系统自带 Edge/Chrome，无需额外安装。
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo 【登录】
>>"%DIST_DIR%\使用说明.txt" echo   国家大学生就业服务平台：首次运行按提示手动登录，
>>"%DIST_DIR%\使用说明.txt" echo       Cookie 自动写入 config.ini 的 nscc_cookie_api。
>>"%DIST_DIR%\使用说明.txt" echo   智联招聘：首次运行手机号 + 短信验证码，
>>"%DIST_DIR%\使用说明.txt" echo       Cookie 自动写入 config.ini 的 zhipin_cookie。
>>"%DIST_DIR%\使用说明.txt" echo   BOSS直聘：Cookie 存在 config.ini 的 boss_cookie。
>>"%DIST_DIR%\使用说明.txt" echo   国聘：无需登录。
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo 【医护知音（公众号）】
>>"%DIST_DIR%\使用说明.txt" echo   1. 先在微信里打开目标公众号文章（内存里才会有链接）
>>"%DIST_DIR%\使用说明.txt" echo   2. 点「提取公众号链接」，把文章链接写入 wechat_links.json
>>"%DIST_DIR%\使用说明.txt" echo   3. 再点「开始采集」，按清单逐篇抓取并识别岗位
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo   以下三项都在 exe 同目录，可直接打开查看和编辑：
>>"%DIST_DIR%\使用说明.txt" echo     wechat_links.json  文章链接清单（status=true 表示已抓过）
>>"%DIST_DIR%\使用说明.txt" echo     医护知音图片\      文章配图，按文章分子目录
>>"%DIST_DIR%\使用说明.txt" echo     医护知音附件\      文章 xlsx 附件
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo   图片会先用系统 OCR 粗筛：封面、二维码、宣传海报这类
>>"%DIST_DIR%\使用说明.txt" echo   没有岗位信息的图直接跳过，只把像岗位表的图送去 AI 识别。
>>"%DIST_DIR%\使用说明.txt" echo   OCR 用的是 Windows 自带组件，无需联网、无需安装。
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo   想重抓某篇：把它的 status 改成 false，或整条删掉再提取。
>>"%DIST_DIR%\使用说明.txt" echo   想跳过某篇：把它的 status 改成 true。
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo 【可编辑配置】
>>"%DIST_DIR%\使用说明.txt" echo    config.ini      登录 Cookie（可直接编辑）
>>"%DIST_DIR%\使用说明.txt" echo   config\ 下的 JSON 已打进 exe，需要时可在外部放同名文件覆盖。
>>"%DIST_DIR%\使用说明.txt" echo.
>>"%DIST_DIR%\使用说明.txt" echo 【常见问题】
>>"%DIST_DIR%\使用说明.txt" echo   Q: 采集没有反应？
>>"%DIST_DIR%\使用说明.txt" echo   A: 查看 logs 目录里最新的日志。
>>"%DIST_DIR%\使用说明.txt" echo   Q: 登录失效？
>>"%DIST_DIR%\使用说明.txt" echo   A: 删除 config.ini 里对应的 cookie 行，重新采集即可。
>>"%DIST_DIR%\使用说明.txt" echo   Q: 想换界面主题？
>>"%DIST_DIR%\使用说明.txt" echo   A: 在 exe 同目录建 config\ui.json，改 themename 后重启。
>>"%DIST_DIR%\使用说明.txt" echo   Q: 采集太慢？
>>"%DIST_DIR%\使用说明.txt" echo   A: BOSS 用 BossJobType.json 限定岗位越少越快，只留需要的。
>>"%DIST_DIR%\使用说明.txt" echo ========================================
echo   已生成 使用说明.txt
exit /b 0

:no_python
echo.
echo [ERROR] 未找到 Python：%PYTHON%
echo         请安装 3.8+，或用环境变量 PYTHON 指定路径。
echo.
pause
exit /b 1

:bad_python
echo.
echo [ERROR] Python 版本过低（需 3.8+）：%PYTHON%
echo.
pause
exit /b 1

:fail
echo.
echo [ERROR] 打包失败，请查看上方日志。
echo.
pause
exit /b 1
