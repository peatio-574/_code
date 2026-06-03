let commentsData = [];
let isCrawling = false;
let crawlInterval = null;
const logEl = document.getElementById("log");
const statusEl = document.getElementById("status");
const crawlBtn = document.getElementById("crawlBtn");
const stopBtn = document.getElementById("stopBtn");

function log(txt) {
  logEl.innerHTML += "<br>" + txt;
  logEl.scrollTop = logEl.scrollHeight;
}

function updateStatus(text, isStopping = false) {
  statusEl.textContent = text;
  if (isStopping) {
    statusEl.classList.add('stopping');
  } else {
    statusEl.classList.remove('stopping');
  }
}

// 1. 开始滚动抓取
crawlBtn.onclick = async () => {
  if (isCrawling) {
    log("已经在抓取中...");
    return;
  }

  log("🚀 开始滚动抓取...");
  commentsData = [];
  isCrawling = true;
  crawlBtn.style.display = "none";
  stopBtn.style.display = "block";
  updateStatus("正在抓取...", false);

  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // 注入内容脚本（只注入一次）
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"]
  });

  // 初始化抓取状态
  await chrome.tabs.sendMessage(tab.id, { action: "initCrawl" });
  log("✅ 初始化完成\n");

  // 定时滚动并抓取
  let scrollCount = 0;
  const maxScrolls = 100; // 最大滚动次数，防止无限滚动

  crawlInterval = setInterval(async () => {
    if (!isCrawling) {
      clearInterval(crawlInterval);
      return;
    }

    try {
      // 发送消息到 content script，执行滚动和抓取
      const response = await chrome.tabs.sendMessage(tab.id, {
        action: "scrollAndCrawl",
        scrollCount: scrollCount
      });

      if (response && response.success) {
        scrollCount++;
        const newComments = response.newComments || [];

        log(`━━━━━━━━━━━━━━━━━━━━`);
        log(`📄 第${scrollCount}次滚动 | 新增${newComments.length}条 | 累计${commentsData.length + newComments.length}条`);

        // === 关键：逐条打印新抓取的评论 ===
        if (newComments.length > 0) {
          newComments.forEach((comment, index) => {
            const preview = comment.text.length > 40 ? comment.text.substring(0, 40) + "..." : comment.text;
            log(`  [${index + 1}] 👤 ${comment.author} | ⏰ ${comment.time}`);
            log(`      💬 ${preview}`);
            log(`      👍 ${comment.likes} 点赞`);
          });
          log(""); // 空行分隔
        }

        // 更新总数据
        commentsData = commentsData.concat(newComments);
        updateStatus(`抓取中... 已滚动${scrollCount}次，共${commentsData.length}条评论`, false);

        // 如果没有新评论，可能已经到底部
        if (newComments.length === 0 && scrollCount > 3) {
          log("⚠️ 连续多次未发现新评论，可能已到达底部");
          stopCrawling();
        }

        // 达到最大滚动次数
        if (scrollCount >= maxScrolls) {
          log(`⚠️ 已达到最大滚动次数(${maxScrolls})，停止抓取`);
          stopCrawling();
        }
      } else {
        log("❌ 抓取失败：" + (response?.error || "未知错误"));
      }
    } catch (error) {
      log("❌ 通信错误：" + error.message);
      stopCrawling();
    }
  }, 2000); // 每2秒滚动一次
};

// 停止抓取函数
function stopCrawling() {
  isCrawling = false;
  if (crawlInterval) {
    clearInterval(crawlInterval);
    crawlInterval = null;
  }
  crawlBtn.style.display = "block";
  stopBtn.style.display = "none";
  updateStatus(`✅ 抓取完成，共${commentsData.length}条评论`, false);
  log(`━━━━━━━━━━━━━━━━━━━━`);
  log(`✅ 抓取结束，共 ${commentsData.length} 条评论`);
}

// 停止按钮点击事件
stopBtn.onclick = async () => {
  log("⏹️ 正在停止抓取...");
  updateStatus("正在停止...", true);

  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  try {
    // 通知 content script 停止
    await chrome.tabs.sendMessage(tab.id, { action: "stopCrawl" });
  } catch (e) {
    log("发送停止信号失败：" + e.message);
  }

  stopCrawling();
};

// 2. 导出CSV
document.getElementById("exportBtn").onclick = () => {
  if (!commentsData.length) return alert("先抓取评论");
  let csv = "作者,时间,评论内容,点赞数\n";
  commentsData.forEach(c => {
    csv += `"${c.author}","${c.time}","${c.text.replace(/"/g, '""')}","${c.likes}"\n`;
  });
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `comments_${new Date().getTime()}.csv`;
  a.click();
  log("📥 已导出 comments.csv");
};

// 3. 发送到Python（Flask）
document.getElementById("sendBtn").onclick = async () => {
  if (!commentsData.length) return alert("先抓取评论");
  try {
    const resp = await fetch("http://127.0.0.1:5000/receive_comments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(commentsData)
    });
    const ret = await resp.json();
    log("✅ 发送成功：" + ret.msg);
  } catch (e) {
    log("❌ 发送失败：" + e.message);
  }
};