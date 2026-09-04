(function (root) {
  const wrappers = [
    ["linkedin.com", "/safety/go", ["url"]],
    ["google.com", "/url", ["q", "url"]],
    ["l.facebook.com", "/l.php", ["u"]],
    ["out.reddit.com", "", ["url"]],
    ["away.vk.com", "", ["to"]],
  ];

  function isHttpUrl(raw) {
    try { return ["http:", "https:"].includes(new URL(raw).protocol); }
    catch (error) { return false; }
  }

  function unwrapUrl(raw) {
    let value = String(raw || "").trim();
    for (let i = 0; i < 3; i++) {
      let url;
      try { url = new URL(value); } catch (error) { return value; }
      const host = url.hostname.toLowerCase().replace(/^www\./, "");
      let next = "";
      if (host === "href.li" && url.search.length > 1) next = url.search.slice(1);
      for (const [domain, path, keys] of wrappers) {
        if ((host === domain || host.endsWith("." + domain)) && (!path || url.pathname.startsWith(path))) {
          for (const key of keys) if (!next && url.searchParams.get(key)) next = url.searchParams.get(key);
        }
      }
      if (!isHttpUrl(next) || next === value) break;
      value = next;
    }
    return value;
  }

  function linkedInPostUrl(values) {
    for (const raw of values || []) {
      const text = String(raw || "");
      const urn = text.match(/urn:li:activity:\d+/i);
      if (urn) return "https://www.linkedin.com/feed/update/" + urn[0].toLowerCase() + "/";
      try {
        const url = new URL(text, "https://www.linkedin.com");
        if (!url.hostname.toLowerCase().endsWith("linkedin.com")) continue;
        if (/^\/posts\/[^/]+/i.test(url.pathname)) return "https://www.linkedin.com" + url.pathname;
      } catch (error) {}
    }
    return "";
  }

  function isContainerUrl(raw) {
    try {
      const url = new URL(raw);
      const host = url.hostname.toLowerCase().replace(/^www\./, "");
      const path = url.pathname.replace(/\/+$/, "") || "/";
      if (host.endsWith("linkedin.com")) return path === "/" || path === "/feed" || path === "/mynetwork";
      if (host.endsWith("reddit.com")) return path === "/" || path === "/r/all" || path === "/r/popular";
      if (host === "news.ycombinator.com") return ["/", "/news", "/newest"].includes(path);
      return false;
    } catch (error) { return false; }
  }

  function contextIdentity({ pageUrl = "", linkUrl = "", itemUrl = "" }) {
    const item = unwrapUrl(itemUrl);
    let post = linkedInPostUrl([item]);
    try {
      const url = new URL(item);
      if (!post && url.hostname.toLowerCase() === "lnkd.in" && url.pathname.startsWith("/p/")) post = item;
    } catch (error) {}
    if (linkUrl) {
      const unwrapped = unwrapUrl(linkUrl);
      try {
        const url = new URL(unwrapped);
        const bareLnkd = url.hostname.toLowerCase() === "lnkd.in" && !url.pathname.startsWith("/p/");
        if (bareLnkd) return post;
      } catch (error) {}
      return linkedInPostUrl([unwrapped]) || unwrapped;
    }
    if (post) return post;
    return isContainerUrl(pageUrl) ? "" : unwrapUrl(pageUrl);
  }

  root.CD = { contextIdentity, isContainerUrl, isHttpUrl, linkedInPostUrl, unwrapUrl };
})(globalThis);
