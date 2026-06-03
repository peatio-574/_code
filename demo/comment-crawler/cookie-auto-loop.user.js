// ==UserScript==
// @name         Cookie自动循环刷新 - 全自动版
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  全自动Cookie循环：获取→保存→刷新→保存→循环，刷新后自动继续
// @author       You
// @match        *://*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_addStyle
// @grant        GM_notification
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    // ==================== 配置 ====================
    const CONFIG = {
        REFRESH_INTERVAL: 300,        // 刷新间隔（秒），默认5分钟
        AUTO_RESUME: true,             // 刷新后自动恢复
        SAVE_ON_LOAD: true,            // 页面加载时自动保存Cookie
        SHOW_NOTIFICATION: true,       // 显示通知
        LOG_MAX_LINES: 50             // 日志最大行数
    };

    // ==================== 全局变量 ====================
    let isRunning = false;
    let refreshTimer = null;
    let countdownTimer = null;
    let remainingSeconds = 0;
    let cycleCount = 0;
    let currentInterval = CONFIG.REFRESH_INTERVAL;

    // ==================== 样式 ====================
    GM_addStyle(`
        #cookie-loop-panel {
            position: fixed;
            top: 10px;
            right: 10px;
            width: 320px;
            background: white;
            border: 3px solid #4CAF50;
            border-radius: 15px;
            z-index: 99999;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
            animation: slideIn 0.3s ease-out;
        }
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        #panel-header {
            background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
            color: white;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #panel-header h3 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
        }
        .panel-btn {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s;
        }
        .panel-btn:hover {
            background: rgba(255,255,255,0.3);
            transform: scale(1.1);
        }
        #panel-body {
            padding: 15px;
            max-height: 70vh;
            overflow-y: auto;
        }
        .info-box {
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 12px;
            border-left: 4px solid #2196F3;
        }
        .info-box.warning {
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            border-left-color: #FF9800;
        }
        .info-box.success {
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            border-left-color: #4CAF50;
        }
        .info-label {
            font-size: 11px;
            color: #666;
            margin-bottom: 4px;
        }
        .info-value {
            font-size: 18px;
            font-weight: bold;
            color: #2196F3;
        }
        .info-value.running {
            color: #4CAF50;
            animation: blink 1.5s infinite;
        }
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 12px;
        }
        .stat-item {
            background: #f5f5f5;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }
        .progress-container {
            margin: 12px 0;
        }
        .progress-label {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }
        .progress-bar {
            height: 6px;
            background: #e0e0e0;
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4CAF50 0%, #2196F3 100%);
            transition: width 1s linear;
            border-radius: 3px;
        }
        .control-box {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }
        .ctrl-btn {
            flex: 1;
            padding: 12px 8px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .ctrl-btn:active {
            transform: scale(0.95);
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .btn-start {
            background: linear-gradient(135deg, #4CAF50, #45a049);
            color: white;
        }
        .btn-stop {
            background: linear-gradient(135deg, #f44336, #d32f2f);
            color: white;
        }
        .btn-settings {
            background: linear-gradient(135deg, #FF9800, #F57C00);
            color: white;
        }
        .settings-box {
            background: #fff3e0;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 12px;
            display: none;
            border: 2px solid #FF9800;
        }
        .settings-box.show {
            display: block;
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .setting-item {
            margin-bottom: 12px;
        }
        .setting-item label {
            display: block;
            font-size: 13px;
            color: #333;
            margin-bottom: 6px;
            font-weight: 500;
        }
        .setting-item input {
            width: 100%;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            box-sizing: border-box;
            transition: border-color 0.3s;
        }
        .setting-item input:focus {
            outline: none;
            border-color: #FF9800;
        }
        #log-area {
            max-height: 180px;
            overflow-y: auto;
            background: #fafafa;
            padding: 10px;
            border-radius: 8px;
            font-size: 12px;
            line-height: 1.6;
            border: 1px solid #e0e0e0;
        }
        .log-item {
            margin: 5px 0;
            padding: 6px 10px;
            border-left: 3px solid #2196F3;
            background: white;
            border-radius: 4px;
            animation: fadeIn 0.3s;
        }
        .log-success {
            border-left-color: #4CAF50;
            background: #f1f8e9;
        }
        .log-warning {
            border-left-color: #FF9800;
            background: #fff3e0;
        }
        .log-error {
            border-left-color: #f44336;
            background: #ffebee;
        }
        .log-info {
            border-left-color: #2196F3;
            background: #e3f2fd;
        }
        #minimize-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 60px;
            height: 60px;
            background: linear-gradient(135deg, #4CAF50, #45a049);
            color: white;
            border-radius: 50%;
            display: none;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            cursor: pointer;
            z-index: 99998;
            box-shadow: 0 6px 16px rgba(76,175,80,0.4);
            transition: all 0.3s;
            animation: bounce 2s infinite;
        }
        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-5px); }
        }
        #minimize-btn.show {
            display: flex;
        }
        #minimize-btn:active {
            transform: scale(0.9);
        }
    `);

    // ==================== 工具函数 ====================
    function getCurrentDomain() {
        return window.location.hostname;
    }

    function getAllCookies() {
        return document.cookie;
    }

    function notify(title, message, type = 'info') {
        if (!CONFIG.SHOW_NOTIFICATION) return;

        try {
            GM_notification({
                text: message,
                title: title,
                timeout: 3000,
                onclick: () => {
                    const panel = document.getElementById('cookie-loop-panel');
                    if (panel) {
                        panel.style.display = 'block';
                    }
                    const minBtn = document.getElementById('minimize-btn');
                    if (minBtn) {
                        minBtn.classList.remove('show');
                    }
                }
            });
        } catch (e) {
            console.log('通知失败:', e);
        }
    }

    // ==================== UI 元素 ====================
    const panel = document.createElement('div');
    panel.id = 'cookie-loop-panel';
    panel.innerHTML = `
        <div id="panel-header">
            <h3>🔄 Cookie自动循环</h3>
            <button class="panel-btn" id="minimize-panel" title="最小化">−</button>
        </div>
        <div id="panel-body">
            <div class="info-box success">
                <div class="info-label">运行状态</div>
                <div class="info-value" id="status-text"> 未启动</div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="info-label">循环次数</div>
                    <div class="info-value" id="cycle-count" style="color:#4CAF50;">0</div>
                </div>
                <div class="stat-item">
                    <div class="info-label">Cookie数量</div>
                    <div class="info-value" id="cookie-count" style="color:#2196F3;">0</div>
                </div>
            </div>
            
            <div class="info-box">
                <div class="info-label">下次刷新倒计时</div>
                <div class="info-value" id="countdown" style="font-size:24px;">--:--</div>
            </div>
            
            <div class="progress-container">
                <div class="progress-label">
                    <span>刷新进度</span>
                    <span id="progress-text">0%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
                </div>
            </div>
            
            <div class="control-box">
                <button class="ctrl-btn btn-start" id="startBtn">▶ 启动</button>
                <button class="ctrl-btn btn-stop" id="stopBtn" style="display:none;">⏹ 停止</button>
                <button class="ctrl-btn btn-settings" id="settingsBtn">⚙ 设置</button>
            </div>
            
            <div class="settings-box" id="settings-box">
                <div class="setting-item">
                    <label> 刷新间隔（秒）</label>
                    <input type="number" id="interval-input" value="${CONFIG.REFRESH_INTERVAL}" min="30" max="3600" placeholder="30-3600秒">
                </div>
                <div class="setting-item">
                    <label> 显示通知</label>
                    <input type="checkbox" id="notification-toggle" ${CONFIG.SHOW_NOTIFICATION ? 'checked' : ''}>
                </div>
                <button class="ctrl-btn btn-start" id="saveSettingsBtn" style="width:100%; margin-top:8px;">💾 保存设置</button>
            </div>
            
            <div id="log-area"></div>
        </div>
    `;
    document.body.appendChild(panel);

    const minimizeBtn = document.createElement('div');
    minimizeBtn.id = 'minimize-btn';
    minimizeBtn.innerHTML = '🔄';
    minimizeBtn.title = '打开控制面板';
    document.body.appendChild(minimizeBtn);

    // ==================== 日志功能 ====================
    const logEl = document.getElementById('log-area');
    const statusText = document.getElementById('status-text');
    const cycleCountEl = document.getElementById('cycle-count');
    const countdownEl = document.getElementById('countdown');
    const cookieCountEl = document.getElementById('cookie-count');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    function log(msg, type = 'info') {
        const div = document.createElement('div');
        div.className = `log-item log-${type}`;
        const time = new Date().toLocaleTimeString('zh-CN');
        div.innerHTML = `<strong>[${time}]</strong> ${msg}`;
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;

        while (logEl.children.length > CONFIG.LOG_MAX_LINES) {
            logEl.removeChild(logEl.firstChild);
        }
    }

    // ==================== 核心逻辑 ====================
    function saveCookie() {
        const domain = getCurrentDomain();
        const cookies = getAllCookies();
        const cookieKey = `cookie_${domain}`;
        const stateKey = `state_${domain}`;

        if (!cookies) {
            log('️ 当前页面没有Cookie', 'warning');
            return 0;
        }

        // 保存Cookie
        GM_setValue(cookieKey, {
            cookies: cookies,
            timestamp: new Date().toISOString(),
            url: window.location.href,
            cycleCount: cycleCount
        });

        // 保存运行状态（用于刷新后恢复）
        if (isRunning) {
            GM_setValue(stateKey, {
                isRunning: true,
                cycleCount: cycleCount,
                interval: currentInterval,
                startTime: Date.now()
            });
        }

        const count = cookies.split(';').length;
        cookieCountEl.textContent = count;

        log(`✅ 已保存 ${count} 个Cookie`, 'success');
        return count;
    }

    function startCycle() {
        if (isRunning) {
            log('⚠️ 已经在运行中', 'warning');
            return;
        }

        isRunning = true;
        cycleCount = 0;

        document.getElementById('startBtn').style.display = 'none';
        document.getElementById('stopBtn').style.display = 'block';
        statusText.textContent = '🟢 运行中';
        statusText.className = 'info-value running';

        log('🚀 自动循环已启动', 'success');
        log(' 工作流程：获取Cookie → 保存 → 等待 → 刷新 → 循环', 'info');
        notify('Cookie循环', '✅ 自动循环已启动', 'success');

        // 先保存一次Cookie
        saveCookie();

        // 开始倒计时循环
        executeCycle();
    }

    function executeCycle() {
        if (!isRunning) return;

        cycleCount++;
        cycleCountEl.textContent = cycleCount;

        currentInterval = parseInt(document.getElementById('interval-input').value) || CONFIG.REFRESH_INTERVAL;
        remainingSeconds = currentInterval;

        log(`━━━━━━━━━━━━━━━━━━━━`, 'info');
        log(`🔄 第 ${cycleCount} 次循环开始`, 'warning');
        log(`⏱️ 刷新间隔：${currentInterval} 秒`, 'info');

        // 倒计时显示
        updateCountdown();
        countdownTimer = setInterval(updateCountdown, 1000);

        // 定时刷新
        refreshTimer = setTimeout(() => {
            if (!isRunning) return;

            log('⏰ 时间到！开始刷新页面...', 'warning');

            // 保存当前Cookie
            saveCookie();

            log('🔄 3秒后刷新页面...', 'info');

            setTimeout(() => {
                if (isRunning) {
                    window.location.reload();
                }
            }, 3000);
        }, currentInterval * 1000);
    }

    function updateCountdown() {
        remainingSeconds--;

        if (remainingSeconds <= 0) {
            remainingSeconds = 0;
            clearInterval(countdownTimer);
        }

        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        countdownEl.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

        const progress = ((currentInterval - remainingSeconds) / currentInterval) * 100;
        progressFill.style.width = `${progress}%`;
        progressText.textContent = `${Math.round(progress)}%`;
    }

    function stopCycle() {
        isRunning = false;

        if (refreshTimer) {
            clearTimeout(refreshTimer);
            refreshTimer = null;
        }
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }

        document.getElementById('startBtn').style.display = 'block';
        document.getElementById('stopBtn').style.display = 'none';
        statusText.textContent = '⏸ 已停止';
        statusText.className = 'info-value';
        countdownEl.textContent = '--:--';
        progressFill.style.width = '0%';
        progressText.textContent = '0%';

        // 清除运行状态
        const domain = getCurrentDomain();
        const stateKey = `state_${domain}`;
        GM_deleteValue(stateKey);

        log('⏹ 自动循环已停止', 'warning');
        notify('Cookie循环', ' 自动循环已停止', 'warning');
    }

    // ==================== 自动恢复 ====================
    function autoResume() {
        if (!CONFIG.AUTO_RESUME) return;

        const domain = getCurrentDomain();
        const stateKey = `state_${domain}`;
        const cookieKey = `cookie_${domain}`;

        const savedState = GM_getValue(stateKey);
        const savedCookie = GM_getValue(cookieKey);

        if (savedState && savedState.isRunning) {
            const elapsed = Math.floor((Date.now() - savedState.startTime) / 1000);
            const remaining = savedState.interval - (elapsed % savedState.interval);

            log('🔍 检测到之前的运行状态', 'info');
            log(` 已运行 ${savedState.cycleCount} 次循环`, 'info');

            if (savedCookie) {
                const saveTime = new Date(savedCookie.timestamp);
                const hoursAgo = ((Date.now() - saveTime) / (1000 * 60 * 60)).toFixed(1);
                log(`💾 发现保存的Cookie（${hoursAgo}小时前）`, 'success');
            }

            // 自动恢复运行
            setTimeout(() => {
                isRunning = true;
                cycleCount = savedState.cycleCount;
                currentInterval = savedState.interval;
                remainingSeconds = remaining > 0 ? remaining : savedState.interval;

                document.getElementById('startBtn').style.display = 'none';
                document.getElementById('stopBtn').style.display = 'block';
                statusText.textContent = '🟢 运行中（自动恢复）';
                statusText.className = 'info-value running';
                cycleCountEl.textContent = cycleCount;

                log('🚀 自动恢复运行，继续循环', 'success');
                notify('Cookie循环', '🔄 已自动恢复运行', 'success');

                // 先保存当前Cookie
                saveCookie();

                // 继续倒计时
                updateCountdown();
                countdownTimer = setInterval(updateCountdown, 1000);

                refreshTimer = setTimeout(() => {
                    if (isRunning) {
                        log('⏰ 时间到！刷新页面...', 'warning');
                        saveCookie();
                        setTimeout(() => {
                            if (isRunning) window.location.reload();
                        }, 3000);
                    }
                }, remainingSeconds * 1000);
            }, 2000);
        } else if (savedCookie) {
            const saveTime = new Date(savedCookie.timestamp);
            const hoursAgo = ((Date.now() - saveTime) / (1000 * 60 * 60)).toFixed(1);
            log(`📋 发现保存的Cookie（${hoursAgo}小时前）`, 'info');
            log(`💡 点击"▶ 启动"开始自动循环`, 'info');
        }
    }

    // ==================== 页面加载时保存Cookie ====================
    function autoSaveOnLoad() {
        if (!CONFIG.SAVE_ON_LOAD) return;

        setTimeout(() => {
            const domain = getCurrentDomain();
            const cookies = getAllCookies();
            if (cookies) {
                const count = cookies.split(';').length;
                const cookieKey = `cookie_${domain}`;

                GM_setValue(cookieKey, {
                    cookies: cookies,
                    timestamp: new Date().toISOString(),
                    url: window.location.href,
                    cycleCount: cycleCount
                });

                cookieCountEl.textContent = count;
                log(` 页面加载完成，自动保存 ${count} 个Cookie`, 'success');
            }
        }, 3000);
    }

    // ==================== 事件绑定 ====================
    document.getElementById('startBtn').addEventListener('click', () => {
        log('👆 用户点击启动按钮', 'info');
        startCycle();
    });

    document.getElementById('stopBtn').addEventListener('click', () => {
        log(' 用户点击停止按钮', 'info');
        stopCycle();
    });

    document.getElementById('settingsBtn').addEventListener('click', () => {
        const box = document.getElementById('settings-box');
        box.classList.toggle('show');
    });

    document.getElementById('saveSettingsBtn').addEventListener('click', () => {
        const interval = parseInt(document.getElementById('interval-input').value);
        const notification = document.getElementById('notification-toggle').checked;

        if (interval >= 30 && interval <= 3600) {
            CONFIG.REFRESH_INTERVAL = interval;
            CONFIG.SHOW_NOTIFICATION = notification;
            currentInterval = interval;
            log(` 设置已保存：刷新间隔 ${interval} 秒`, 'success');
            document.getElementById('settings-box').classList.remove('show');
        } else {
            log('❌ 间隔必须在30-3600秒之间', 'error');
        }
    });

    document.getElementById('minimize-panel').addEventListener('click', () => {
        panel.style.display = 'none';
        minimizeBtn.classList.add('show');
        log('📌 面板已最小化', 'info');
    });

    minimizeBtn.addEventListener('click', () => {
        panel.style.display = 'block';
        minimizeBtn.classList.remove('show');
        log('📌 面板已打开', 'info');
    });

    // ==================== 初始化 ====================
    window.addEventListener('load', () => {
        setTimeout(() => {
            autoResume();
            autoSaveOnLoad();
        }, 2000);
    });

})();