const DEFAULTS = { server: "http://localhost:7778", token: "" };

chrome.storage.sync.get(DEFAULTS, (s) => {
  document.getElementById("server").value = s.server;
  document.getElementById("token").value = s.token;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set(
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
