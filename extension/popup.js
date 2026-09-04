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
document.getElementById("open-digest").addEventListener("click", async () => {
  const { server = "", token = "" } = await chrome.storage.local.get(["server", "token"]);
  if (!server.trim() || !token.trim()) { show("Open Settings and enter the server URL and token first."); return; }
  chrome.tabs.create({ url: server.trim().replace(/\/$/, "") + "/view?token=" + encodeURIComponent(token.trim()) });
});
document.getElementById("options").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});
chrome.storage.onChanged.addListener(refresh);
refresh();
