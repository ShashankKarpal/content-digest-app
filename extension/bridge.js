(() => {
  const clipboard = navigator.clipboard;
  if (!clipboard || typeof clipboard.writeText !== "function" || window.__contentDigestBridge) return;
  window.__contentDigestBridge = true;
  const writeText = clipboard.writeText.bind(clipboard);
  clipboard.writeText = (text) => {
    document.dispatchEvent(new CustomEvent("content-digest-copied-link", { detail: String(text || "") }));
    return writeText(text);
  };
})();
