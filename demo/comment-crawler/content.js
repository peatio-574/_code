// 通用评论抓取器，适配多数网站
function scrapeComments() {
  const comments = [];
  // 常见评论区选择器
  const selectors = [
    ".comment", ".comments", ".review", ".reply", "[class*='el-table__row']",
    "[class*='comment']", "[class*='review']", "[data-comment]"
  ];
  let els = [];
  selectors.forEach(s => {
    els = els.concat(Array.from(document.querySelectorAll(s)));
  });
  // 去重
  els = [...new Set(els)];

  els.forEach(el => {
    const text = el.innerText.trim().replace(/\s+/g, " ");
    if (!text || text.length < 5) return;

    // 尝试提取作者/时间/点赞（根据常见结构）
    const author = el.querySelector(".author, .name, .user")?.innerText.trim() || "匿名";
    const time = el.querySelector(".time, .date")?.innerText.trim() || "未知时间";
    const likes = el.querySelector(".like, .likes, .count")?.innerText.trim() || "0";

    comments.push({ author, time, text, likes });
  });
  return comments;
}

// 存储已抓取的评论文本，用于去重
let crawledTexts = new Set();

// 监听来自 popup 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

  // 初始化抓取状态
  if (request.action === "initCrawl") {
    crawledTexts.clear();
    sendResponse({ success: true, message: "初始化完成" });
  }

  // 滚动并抓取新评论
  else if (request.action === "scrollAndCrawl") {
    try {
      // 先抓取当前页面的评论
      const allComments = scrapeComments();

      // 过滤出未抓取过的评论
      const newComments = allComments.filter(comment => {
        if (crawledTexts.has(comment.text)) {
          return false;
        }
        crawledTexts.add(comment.text);
        return true;
      });

      // 滚动页面（向下滚动500像素）
      window.scrollBy({ top: 500, behavior: 'smooth' });

      sendResponse({
        success: true,
        newComments: newComments,
        totalComments: allComments.length,
        scrolled: true
      });
    } catch (error) {
      sendResponse({ success: false, error: error.message });
    }
  }

  // 停止抓取
  else if (request.action === "stopCrawl") {
    sendResponse({ success: true, message: "已停止" });
  }

  return true; // 保持消息通道开启
});