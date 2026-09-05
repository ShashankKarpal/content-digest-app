const server = document.getElementById("server");
const token = document.getElementById("token");
const status = document.getElementById("status");

chrome.storage.local.get(["server", "token"], (settings) => {
  server.value = settings.server || "";
  token.value = settings.token || "";
});

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ server: server.value.trim(), token: token.value.trim(), configuredAt: Date.now() });
  status.textContent = "Saved locally in this Chrome profile.";
});

document.getElementById("test").addEventListener("click", async () => {
  const base = server.value.trim().replace(/\/$/, "");
  const auth = token.value.trim();
  if (!base || !auth) { status.textContent = "Enter both the server URL and token first."; return; }
  status.textContent = "Testing...";
  try {
    const health = await fetch(base + "/health");
    if (!health.ok) throw new Error("Server health returned HTTP " + health.status + ".");
    const check = await fetch(base + "/failures", { headers: { Authorization: "Bearer " + auth, "X-Client": "extension" } });
    status.textContent = check.ok ? "Connected. Server and token are valid." : "Server reached, but the token was rejected (HTTP " + check.status + ").";
  } catch (error) {
    status.textContent = "Connection failed: " + error.message;
  }
});
