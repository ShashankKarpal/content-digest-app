let activeTab;
const urlInput = document.getElementById("url");
const result = document.getElementById("result");
const buttons = Array.from(document.querySelectorAll("button"));

function show(message) { result.textContent = message; }
function busy(value) { buttons.forEach((button) => { button.disabled = value; }); }

async function refresh() {
  const { pending = [], captureHistory = [] } = await chrome.storage.local.get(["pending", "captureHistory"]);
  document.getElementById("meta").textContent = "Recent activity" + (pending.length ? " (" + pending.length + " queued)" : "");
  document.getElementById("history").replaceChildren(...captureHistory.map((item) => {
    const li = document.createElement("li");
    li.textContent = item.message + " " + item.url;
    return li;
  }));
}

async function send(message) {
  busy(true);
  show("Sent. Content Digest is working on it...");
  try {
    const response = await chrome.runtime.sendMessage(message);
    if (response.outcome === "saved") show("Done. The summary is now in Content Digest.");
    else if (response.outcome === "already_saved") show("This URL is already in Content Digest.");
    else if (response.outcome === "queued" && String(response.message || "").startsWith("AUTH:")) {
      show("The token was rejected by the server. Check the token in Settings. Your URL is safely queued.");
    }
    else if (response.outcome === "queued" && String(response.message || "").startsWith("CONFIG:")) {
      show("Set the server URL and token in Settings. Your URL is safely queued.");
    }
    else if (response.outcome === "queued") show("The server is unavailable or needs attention. Your URL is safely queued for retry.");
    else show(response.message);
  } catch (error) {
    show("The extension could not complete the request.");
  }
  busy(false);
  refresh();
}

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  activeTab = tab;
  show("Ready. Paste a URL above.");
});

document.getElementById("capture-form").addEventListener("submit", (event) => {
  event.preventDefault();
  send({
  type: "saveUrl", url: urlInput.value.trim(), tabId: activeTab && activeTab.id,
  });
});
document.getElementById("save-page").addEventListener("click", () => send({
  type: "savePage", url: activeTab && activeTab.url, tabId: activeTab && activeTab.id,
}));
// The token never goes in a URL, where browser history (and synced history)
// would keep it (leak audit H3). The popup signs this Chrome profile in with
// the session cookie the server's Locked form would set, then opens plain
// /view. The value must match server.py _session_cookie_value().
async function sessionCookieValue(token) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode("content-digest-cookie-v1")));
  return Array.from(mac, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

document.getElementById("open-digest").addEventListener("click", async () => {
  const { server = "", token = "" } = await chrome.storage.local.get(["server", "token"]);
  if (!server.trim() || !token.trim()) { show("Open Settings and enter the server URL and token first."); return; }
  const base = server.trim().replace(/\/$/, "");
  try {
    await chrome.cookies.set({
      url: base + "/view", name: "cd_session", value: await sessionCookieValue(token.trim()), path: "/",
      httpOnly: true, sameSite: "lax", expirationDate: Math.floor(Date.now() / 1000) + 31536000,
    });
  } catch (error) {
    // Still open the page: its Locked form signs in by hand.
    console.warn("Content Digest: could not set the sign-in cookie: " + (error && error.message));
    show("Could not sign in automatically. The page will ask for the token.");
  }
  chrome.tabs.create({ url: base + "/view" });
});
document.getElementById("options").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});
chrome.storage.onChanged.addListener(refresh);
refresh();
