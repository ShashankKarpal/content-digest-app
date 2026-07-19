// Content Digest Capture — browser-side capture layer.
// Grabs the rendered page text (what YOU see, logged in, residential IP)
// and POSTs it to the Content Digest server. No server-side fetch can be
// blocked this way: Reddit, LinkedIn, paywalled-but-logged-in pages all work.

const DEFAULTS = {
  server: "http://100.112.78.47:7778",
  token: "",
};

async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULTS, resolve);
  });
}

function grabPageContent() {
  // Runs inside the page. Prefer the user's selection; otherwise take the
  // main article/body text. Cap generously; the server trims to 3000 chars.
  const sel = window.getSelection ? String(window.getSelection()) : "";
  let text = sel && sel.trim().length > 80 ? sel : "";
  if (!text) {
    const main =
      document.querySelector("article") ||
      document.querySelector("main") ||
      document.body;
    text = main ? main.innerText : "";
  }
  return {
    url: location.href,
    title: document.title,
    content: (text || "").replace(/\n{3,}/g, "\n\n").slice(0, 20000),
  };
}

function setBadge(tabId, text, color) {
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 4000);
}

async function capture(tab) {
  if (!tab || !tab.id || !/^https?:/.test(tab.url || "")) return;
  const { server, token } = await getSettings();
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: grabPageContent,
    });
    setBadge(tab.id, "...", "#ff9f1c");
    const resp = await fetch(server.replace(/\/$/, "") + "/add", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + token,
      },
      body: JSON.stringify({
        url: result.url,
        title: result.title,
        content: result.content,
      }),
    });
    if (resp.ok) {
      setBadge(tab.id, "✓", "#22c55e");
    } else {
      setBadge(tab.id, String(resp.status), "#c83232");
    }
  } catch (e) {
    console.warn("Content Digest capture failed:", e);
    setBadge(tab.id, "✗", "#c83232");
  }
}

chrome.action.onClicked.addListener(capture);

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "cd-save",
    title: "Save to Content Digest",
    contexts: ["page", "selection", "link"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "cd-save") return;
  // Right-clicked a link: send the link URL for server-side fetch.
  if (info.linkUrl) {
    const { server, token } = await getSettings();
    try {
      await fetch(server.replace(/\/$/, "") + "/add", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        body: JSON.stringify({ url: info.linkUrl }),
      });
      if (tab && tab.id) setBadge(tab.id, "✓", "#22c55e");
    } catch (e) {
      if (tab && tab.id) setBadge(tab.id, "✗", "#c83232");
    }
    return;
  }
  capture(tab);
});
