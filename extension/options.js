const DEFAULTS = { server: "http://localhost:7778", token: "" };

// storage.local, not sync: the bearer token used to replicate to the Google
// account's sync backend (audit 2026-09-02). Re-enter it once after updating.
chrome.storage.local.get(DEFAULTS, (s) => {
  document.getElementById("server").value = s.server;
  document.getElementById("token").value = s.token;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.local.set(
    {
      server: document.getElementById("server").value.trim(),
      token: document.getElementById("token").value.trim(),
    },
    () => {
      const st = document.getElementById("status");
      st.textContent = "Saved.";
      setTimeout(() => (st.textContent = ""), 2000);
    }
  );
});
