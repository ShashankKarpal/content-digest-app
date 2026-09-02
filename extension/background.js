// Content Digest Capture — browser-side capture layer.
// Grabs the rendered page text (what YOU see, logged in, residential IP)
// and POSTs it to the Content Digest server. No server-side fetch can be
// blocked this way: Reddit, LinkedIn, paywalled-but-logged-in pages all work.

const DEFAULTS = {
  server: "http://localhost:7778",
  token: "",
};

async function getSettings() {
  // storage.local: the token stays in this browser profile (was storage.sync).
  return new Promise((resolve) => {
    chrome.storage.local.get(DEFAULTS, resolve);
  });
}

// Captures that fail to reach the server (off-LAN, server down) are queued
// locally and replayed every 15 minutes, so a capture never vanishes just
// because the tailnet was not up at that moment (2026-08-31 incident).
const PENDING_KEY = "pending";
const FLUSH_ALARM = "cd-flush";

async function postAdd(payload) {
  const { server, token } = await getSettings();
  const resp = await fetch(server.replace(/\/$/, "") + "/add", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  return resp;
}

async function queuePending(payload) {
  const { [PENDING_KEY]: pending = [] } = await chrome.storage.local.get(PENDING_KEY);
  pending.push({ ...payload, queuedAt: Date.now() });
  await chrome.storage.local.set({ [PENDING_KEY]: pending.slice(-100) });
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 15 });
}

async function flushPending() {
  const { [PENDING_KEY]: pending = [] } = await chrome.storage.local.get(PENDING_KEY);
  if (!pending.length) { chrome.alarms.clear(FLUSH_ALARM); return; }
  const remaining = [];
  for (const item of pending) {
    try { await postAdd(item); } catch (e) { remaining.push(item); }
  }
  await chrome.storage.local.set({ [PENDING_KEY]: remaining });
  if (!remaining.length) chrome.alarms.clear(FLUSH_ALARM);
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) flushPending();
});

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
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: grabPageContent,
    });
    setBadge(tab.id, "...", "#ff9f1c");
    const payload = { url: result.url, title: result.title, content: result.content };
    try {
      await postAdd(payload);
      setBadge(tab.id, "✓", "#22c55e");
    } catch (e) {
      // 401/403 are configuration errors and will not heal by waiting.
      if (/HTTP 40[13]/.test(String(e))) { setBadge(tab.id, "401", "#c83232"); return; }
      await queuePending(payload);
      setBadge(tab.id, "Q", "#ff9f1c");
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
    try {
      await postAdd({ url: info.linkUrl });
      if (tab && tab.id) setBadge(tab.id, "✓", "#22c55e");
    } catch (e) {
      await queuePending({ url: info.linkUrl });
      if (tab && tab.id) setBadge(tab.id, "Q", "#ff9f1c");
    }
    return;
  }
  capture(tab);
});
