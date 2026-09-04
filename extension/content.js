let lastContext = {};
let lastPost = null;

function findFeedItem(target) {
  let node = target;
  while (node && node !== document.body) {
    if (node.matches && node.matches(
      "article,.feed-shared-update-v2,[data-urn*='urn:li:activity'],[data-id*='urn:li:activity'],[data-view-name='feed-full-update']"
    )) return node;
    const menus = node.querySelectorAll && node.querySelectorAll("button[aria-label^='Open control menu for post']");
    if (menus && menus.length === 1) return node;
    node = node.parentElement;
  }
  return null;
}

function contextSnapshot(target) {
  const containers = [];
  let node = target;
  for (let i = 0; node && i < 40; i++, node = node.parentElement) {
    containers.push(node);
  }
  let post = findFeedItem(target);
  if (post && !containers.includes(post)) containers.unshift(post);
  let itemUrl = "";
  for (const el of containers) {
    if (itemUrl) break;
    const attrs = el.attributes ? Array.from(el.attributes, (attr) => attr.value) : [];
    if (el.href) attrs.push(el.href);
    itemUrl = CD.linkedInPostUrl(attrs);
    if (itemUrl) { post = el; break; }
    const links = el.querySelectorAll ? Array.from(el.querySelectorAll("a[href]"), (a) => a.href) : [];
    itemUrl = CD.linkedInPostUrl(links);
    if (itemUrl) post = el;
  }
  if (!post) post = target.closest && target.closest("article");
  lastPost = post;
  return {
    itemUrl,
    title: document.title,
    content: ((post && post.innerText) || "").replace(/\n{3,}/g, "\n\n").slice(0, 20000),
  };
}

function resolveLinkedInPost(post) {
  if (!post || !location.hostname.endsWith("linkedin.com")) return Promise.resolve("");
  const button = post.querySelector("button[aria-label^='Open control menu for post']");
  if (!button) return Promise.resolve("");
  return new Promise((resolve) => {
    let clicked = false;
    const finish = (url = "") => {
      observer.disconnect();
      document.removeEventListener("content-digest-copied-link", onCopied);
      clearTimeout(timer);
      resolve(CD.contextIdentity({ pageUrl: location.href, itemUrl: url }));
    };
    const onCopied = (event) => {
      const url = CD.contextIdentity({ pageUrl: location.href, itemUrl: event.detail });
      if (url) finish(url);
    };
    const clickCopy = () => {
      if (clicked) return;
      const items = Array.from(document.querySelectorAll("[role='menuitem']"));
      const copy = items.find((item) => item.innerText.trim() === "Copy link to post");
      if (copy) { clicked = true; copy.click(); }
    };
    const observer = new MutationObserver(clickCopy);
    const timer = setTimeout(() => finish(), 2000);
    document.addEventListener("content-digest-copied-link", onCopied);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    button.click();
    clickCopy();
  });
}

document.addEventListener("contextmenu", (event) => {
  lastContext = contextSnapshot(event.target);
}, true);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "context") return;
  if (lastContext.itemUrl || !location.hostname.endsWith("linkedin.com")) {
    sendResponse(lastContext);
    return;
  }
  resolveLinkedInPost(lastPost).then((itemUrl) => {
    if (itemUrl) lastContext.itemUrl = itemUrl;
    sendResponse(lastContext);
  });
  return true;
});
