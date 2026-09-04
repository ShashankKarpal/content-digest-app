importScripts("shared.js");

const PENDING_KEY = "pending";
const HISTORY_KEY = "captureHistory";
const FLUSH_ALARM = "cd-flush";

async function getSettings() {
  return chrome.storage.local.get(["server", "token"]);
}

function cleanPayload(item) {
  const { queuedAt, queueReason, ...payload } = item;
  return payload;
}

async function postAdd(payload) {
  const { server = "", token = "" } = await getSettings();
  if (!server.trim() || !token.trim()) throw new Error("CONFIG: Open Options and set the server URL and token.");
  const resp = await fetch(server.trim().replace(/\/$/, "") + "/add_sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token.trim() },
    body: JSON.stringify(payload),
  });
  if (resp.status === 401 || resp.status === 403) throw new Error("AUTH: The server rejected the token.");
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  return resp.json();
}

async function addHistory(outcome, message, url) {
  const { [HISTORY_KEY]: history = [] } = await chrome.storage.local.get(HISTORY_KEY);
  history.unshift({ outcome, message, url, at: Date.now() });
  await chrome.storage.local.set({ [HISTORY_KEY]: history.slice(0, 5) });
}

async function queuePending(payload, reason) {
  const { [PENDING_KEY]: pending = [] } = await chrome.storage.local.get(PENDING_KEY);
  pending.push({ ...payload, queuedAt: Date.now(), queueReason: reason });
  await chrome.storage.local.set({ [PENDING_KEY]: pending.slice(-100) });
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 15 });
}

function setBadge(tabId, text, color) {
  if (!tabId) return;
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 4000);
}

async function rejectCapture(url, tabId, message) {
  await addHistory("refused", message, url || "");
  setBadge(tabId, "NO", "#c83232");
  return { outcome: "refused", message, url: url || "" };
}

async function resolveItemUrl(url) {
  try {
    const parsed = new URL(url);
    if (parsed.hostname.toLowerCase() !== "lnkd.in" || !parsed.pathname.startsWith("/p/")) return url;
    const response = await fetch(url, { redirect: "follow" });
    return CD.linkedInPostUrl([response.url]) || url;
  } catch (error) {
    return url;
  }
}

async function submit(payload, tabId, fromQueue = false) {
  let url = CD.unwrapUrl(payload.url || "");
  if (!CD.isHttpUrl(url)) return rejectCapture(url, tabId, "Paste a valid http or https URL.");
  url = await resolveItemUrl(url);
  if (CD.isContainerUrl(url)) return rejectCapture(url, tabId, "This is a feed, not an item. Copy the post permalink and paste it in the popup.");
  payload = { ...payload, url };
  setBadge(tabId, "...", "#b17e51");
  try {
    const result = await postAdd(payload);
    const status = result.status || "failed";
    if (status === "saved") {
      await addHistory("saved", "Saved.", result.url || url);
      setBadge(tabId, "OK", "#22c55e");
      return { outcome: "saved", message: "Saved.", url: result.url || url };
    }
    if (status === "already_saved") {
      await addHistory("already_saved", "Already saved. Nothing was added twice.", result.url || url);
      setBadge(tabId, "DUP", "#64748b");
      return { outcome: "already_saved", message: "Already saved. Nothing was added twice.", url: result.url || url };
    }
    const message = result.reason || "The server could not save this item.";
    await addHistory(status, message, result.url || url);
    setBadge(tabId, "ERR", "#c83232");
    return { outcome: status, message, url: result.url || url };
  } catch (error) {
    const message = String(error.message || error);
    if (!fromQueue) {
      await queuePending(payload, message);
      await addHistory("queued", message.startsWith("AUTH:") || message.startsWith("CONFIG:")
        ? message + " Capture queued."
        : "Server unreachable. Capture queued for retry.", url);
    }
    setBadge(tabId, message.startsWith("AUTH:") || message.startsWith("CONFIG:") ? "CFG" : "Q", "#ff9f1c");
    return { outcome: "queued", message, url };
  }
}

async function flushPending() {
  const { [PENDING_KEY]: pending = [] } = await chrome.storage.local.get(PENDING_KEY);
  if (!pending.length) {
    chrome.alarms.clear(FLUSH_ALARM);
    return;
  }
  const remaining = [];
  for (const item of pending) {
    const payload = cleanPayload(item);
    const result = await submit(payload, 0, true);
    if (result.outcome === "queued") remaining.push(item);
  }
  await chrome.storage.local.set({ [PENDING_KEY]: remaining });
  if (!remaining.length) chrome.alarms.clear(FLUSH_ALARM);
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) flushPending();
});

function grabPageContent() {
  const main = document.querySelector("article") || document.querySelector("main") || document.body;
  return {
    url: location.href,
    title: document.title,
    content: ((main && main.innerText) || "").replace(/\n{3,}/g, "\n\n").slice(0, 20000),
  };
}

async function capturePage(tab) {
  if (!tab || !tab.id || !CD.isHttpUrl(tab.url || "")) {
    return rejectCapture(tab && tab.url, tab && tab.id, "This tab cannot be captured. Paste an http or https permalink in the popup.");
  }
  if (CD.isContainerUrl(tab.url)) {
    return rejectCapture(tab.url, tab.id, "This is a feed, not an item. Copy the post permalink and paste it in the popup.");
  }
  try {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: grabPageContent });
    return submit(result, tab.id);
  } catch (error) {
    return rejectCapture(tab.url, tab.id, "Chrome could not read this page. Paste its permalink in the popup.");
  }
}

async function getContext(tabId) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "context" });
  } catch (error) {
    return {};
  }
}

async function captureContext(info, tab) {
  const tabId = tab && tab.id;
  const context = tabId ? await getContext(tabId) : {};
  const url = CD.contextIdentity({
    pageUrl: tab && tab.url,
    linkUrl: info.linkUrl,
    itemUrl: context.itemUrl,
  });
  if (!url) return rejectCapture(tab && tab.url, tabId, "No item permalink was found. Copy the post permalink and paste it in the popup.");
  if (info.selectionText) {
    return submit({ url, title: context.title || "", content: info.selectionText.slice(0, 20000) }, tabId);
  }
  if (context.itemUrl && url === context.itemUrl) {
    return submit({ url, title: context.title || "", content: (context.content || "").slice(0, 20000) }, tabId);
  }
  return submit({ url }, tabId);
}

// Keep the 0.5.1 local-storage migration intact. Local values win and sync is
// purged unconditionally, even when it has nothing useful to recover.
const MIGRATION_KEY = "migratedFromSync";
const MIGRATED_KEYS = ["server", "token"];

async function migrateFromSync() {
  try {
    const { [MIGRATION_KEY]: alreadyDone } = await chrome.storage.local.get(MIGRATION_KEY);
    if (alreadyDone) return;
    let old = {};
    try { old = (await chrome.storage.sync.get(MIGRATED_KEYS)) || {}; }
    catch (error) { console.warn("Content Digest migration: sync storage unreadable."); }
    const local = await chrome.storage.local.get(MIGRATED_KEYS);
    const recovered = {};
    for (const key of MIGRATED_KEYS) {
      if (typeof local[key] === "string" && local[key].trim()) continue;
      if (typeof old[key] === "string" && old[key].trim()) recovered[key] = old[key];
    }
    if (Object.keys(recovered).length) await chrome.storage.local.set(recovered);
    try { await chrome.storage.sync.clear(); }
    catch (error) { console.warn("Content Digest migration: sync clear failed."); }
    await chrome.storage.local.set({ [MIGRATION_KEY]: true });
  } catch (error) {
    console.warn("Content Digest migration failed.");
  }
}

function createMenu() {
  chrome.contextMenus.removeAll(() => chrome.contextMenus.create({
    id: "cd-save",
    title: "Save to Content Digest",
    contexts: ["page", "selection", "link"],
  }));
}

chrome.runtime.onInstalled.addListener((details) => {
  createMenu();
  if (details.reason === "install" || details.reason === "update") migrateFromSync();
});
chrome.runtime.onStartup.addListener(createMenu);

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "cd-save") captureContext(info, tab);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "saveUrl") submit({ url: message.url }, message.tabId).then(sendResponse);
  else if (message.type === "savePage") capturePage({ id: message.tabId, url: message.url }).then(sendResponse);
  else if (message.type === "flush") flushPending().then(() => sendResponse({ ok: true }));
  else return false;
  return true;
});
