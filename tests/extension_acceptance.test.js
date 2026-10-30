const strict = require("node:assert/strict");
const fs = require("node:fs");
let assertionCount = 0;
const assert = new Proxy(strict, {
  get(target, key) {
    const value = target[key];
    if (typeof value !== "function") return value;
    return (...args) => { assertionCount++; return value.apply(target, args); };
  },
});
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const local = {};
const sync = {};
const calls = [];
const listeners = {};
let contextReply = {};
// The context menu model: removeAll clears at once but calls back later, as
// in Chrome, so two rebuilds in flight can race.
const menus = new Set();
const menuErrors = [];
const menuCallbacks = [];
let menuCreateThrows = false;
const alarms = new Set();
let fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });

function area(data) {
  return {
    get(keys, callback) {
      let result = {};
      if (typeof keys === "string") result[keys] = data[keys];
      else if (Array.isArray(keys)) for (const key of keys) result[key] = data[key];
      else {
        result = { ...keys };
        for (const key of Object.keys(keys)) if (data[key] !== undefined) result[key] = data[key];
      }
      if (callback) callback(result);
      else return Promise.resolve(result);
    },
    set(values, callback) { Object.assign(data, values); if (callback) callback(); return Promise.resolve(); },
    clear() { for (const key of Object.keys(data)) delete data[key]; return Promise.resolve(); },
  };
}

const chrome = {
  storage: {
    local: area(local),
    sync: area(sync),
    onChanged: { addListener: (fn) => { listeners.storage = fn; } },
  },
  alarms: {
    create: (name, options) => { alarms.add(name); calls.push(["alarm", name, options]); },
    clear: (name) => { alarms.delete(name); calls.push(["clear", name]); },
    get: async (name) => (alarms.has(name) ? { name } : undefined),
    onAlarm: { addListener: (fn) => { listeners.alarm = fn; } },
  },
  action: {
    setBadgeText: (x) => calls.push(["badge", x.text]),
    setBadgeBackgroundColor: () => {},
  },
  contextMenus: {
    removeAll: (callback) => { calls.push(["removeAll"]); menus.clear(); menuCallbacks.push(callback); },
    create: (options, callback) => {
      calls.push(["menu", options]);
      if (menuCreateThrows) { menuCreateThrows = false; throw new Error("Invalid menu options"); }
      if (menus.has(options.id)) {
        chrome.runtime.lastError = { message: "Cannot create item with duplicate id " + options.id };
        menuErrors.push(chrome.runtime.lastError.message);
      } else menus.add(options.id);
      if (callback) callback();
      delete chrome.runtime.lastError;
    },
    onClicked: { addListener: (fn) => { listeners.context = fn; } },
  },
  runtime: {
    onInstalled: { addListener: (fn) => { listeners.installed = fn; } },
    onStartup: { addListener: (fn) => { listeners.startup = fn; } },
    onMessage: { addListener: (fn) => { listeners.message = fn; } },
  },
  scripting: { executeScript: async () => [{ result: { url: "https://example.com/article", title: "Article", content: "useful ".repeat(50) } }] },
  tabs: { sendMessage: async () => contextReply },
};

const sandbox = {
  chrome,
  console,
  fetch: (...args) => { calls.push(["fetch", ...args]); return fetchReply(...args); },
  importScripts: () => {},
  setTimeout: () => 0,
  AbortSignal,
  URL,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "extension/shared.js"), "utf8"), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "extension/background.js"), "utf8"), sandbox);

function reset(settings = { server: "http://server.test:7778", token: "test-token" }) {
  for (const key of Object.keys(local)) delete local[key];
  Object.assign(local, settings);
  calls.length = 0;
  alarms.clear();
  contextReply = {};
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
}

function requestBody(index = -1) {
  const fetches = calls.filter((call) => call[0] === "fetch");
  return JSON.parse(fetches.at(index)[2].body);
}

function requestHeaders(index = -1) {
  const fetches = calls.filter((call) => call[0] === "fetch");
  return fetches.at(index)[2].headers || {};
}

// Runs the real popup.js against a minimal page and returns the status line it
// shows after the background answers a send with the given response.
// Fetches held open until the test releases them, to overlap flushes.
const held = [];
async function settle() {
  for (let i = 0; i < 5; i++) await new Promise((resolve) => setImmediate(resolve));
}
async function releaseUntil(done) {
  let finished = false;
  done.then(() => { finished = true; }, () => { finished = true; });
  for (let i = 0; i < 20 && !finished; i++) {
    await settle();
    while (held.length) held.shift()({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
  }
  return done;
}

async function settleMenus() {
  for (let i = 0; i < 10; i++) {
    while (menuCallbacks.length) {
      try { menuCallbacks.shift()(); } catch (error) { menuErrors.push("thrown: " + error.message); }
    }
    await new Promise((resolve) => setImmediate(resolve));
  }
}

async function popupText(response) {
  const elements = {};
  const element = (id) => elements[id] || (elements[id] = {
    id, textContent: "", value: "", disabled: false, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren() {},
  });
  const popupChrome = {
    runtime: { sendMessage: async () => response, openOptionsPage() {} },
    storage: { local: area({}), onChanged: { addListener() {} } },
    tabs: { query: (query, callback) => callback([{ id: 1, url: "https://example.com/" }]), create() {} },
  };
  const page = {
    chrome: popupChrome,
    document: { getElementById: element, querySelectorAll: () => [], createElement: () => ({}) },
  };
  vm.createContext(page);
  vm.runInContext(fs.readFileSync(path.join(root, "extension/popup.js"), "utf8"), page);
  elements["capture-form"].listeners.submit({ preventDefault() {} });
  // The listener does not return send()'s promise; let it settle first.
  for (let i = 0; i < 5; i++) await new Promise((resolve) => setImmediate(resolve));
  return elements.result.textContent;
}

// Runs the real popup.js, clicks Open Content Digest, and returns the tabs it
// opened and the cookies it set.
async function popupOpenDigest(settings) {
  const elements = {};
  const element = (id) => elements[id] || (elements[id] = {
    id, textContent: "", value: "", disabled: false, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren() {},
  });
  const opened = [];
  const cookies = [];
  const popupChrome = {
    runtime: { sendMessage: async () => ({}), openOptionsPage() {} },
    storage: { local: area({ ...settings }), onChanged: { addListener() {} } },
    tabs: { query: (query, callback) => callback([{ id: 1, url: "https://example.com/" }]), create: (options) => opened.push(options.url) },
    cookies: { set: async (details) => { cookies.push(details); return details; } },
  };
  const page = {
    chrome: popupChrome,
    crypto: globalThis.crypto,
    TextEncoder,
    document: { getElementById: element, querySelectorAll: () => [], createElement: () => ({}) },
  };
  vm.createContext(page);
  vm.runInContext(fs.readFileSync(path.join(root, "extension/popup.js"), "utf8"), page);
  elements["open-digest"].listeners.click();
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setImmediate(resolve));
  return { opened, cookies, status: elements.result.textContent };
}

async function run() {
  const CD = sandbox.CD;
  const popupHtml = fs.readFileSync(path.join(root, "extension/popup.html"), "utf8");
  const popupJs = fs.readFileSync(path.join(root, "extension/popup.js"), "utf8");
  const bridgeJs = fs.readFileSync(path.join(root, "extension/bridge.js"), "utf8");
  const contentJs = fs.readFileSync(path.join(root, "extension/content.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "extension/manifest.json"), "utf8"));
  const feed = "https://www.linkedin.com/feed/";
  const post = "https://www.linkedin.com/feed/update/urn:li:activity:7498695844070723585/";
  const wrapper = "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Flnkd.in%2Fey84cgC7&urlhash=x";

  assert.match(popupHtml, /Send to Content Digest/, "the popup makes pasted-URL submission the primary action");
  assert.match(popupHtml, /Open Content Digest/, "the popup links to the knowledge base");
  assert.doesNotMatch(popupJs, /urlInput\.value\s*=\s*tab/, "the popup opens with an empty field ready for a pasted URL");
  const rejected = await popupText({ outcome: "queued", message: "AUTH: The server rejected the token.", url: "https://example.com/a" });
  assert.match(rejected, /token was rejected/i, "the popup says the token was rejected on a 401 or 403");
  assert.doesNotMatch(rejected, /unavailable/i, "a rejected token is not reported as an unavailable server");
  const unset = await popupText({ outcome: "queued", message: "CONFIG: Open Options and set the server URL and token.", url: "https://example.com/a" });
  assert.match(unset, /Settings/, "the popup sends missing settings to Settings");
  assert.doesNotMatch(unset, /unavailable/i, "missing settings are not reported as an unavailable server");
  const offline = await popupText({ outcome: "queued", message: "Failed to fetch", url: "https://example.com/a" });
  assert.match(offline, /unavailable/i, "a network failure keeps the unavailable-server text");
  assert.doesNotMatch(offline, /token/i, "a network failure does not blame the token");

  const digest = await popupOpenDigest({ server: "http://server.test:7778/", token: " test-token " });
  assert.deepEqual(digest.opened, ["http://server.test:7778/view"], "H3 Open Content Digest opens plain /view");
  assert.equal(digest.opened.some((url) => /token/i.test(url)), false, "H3 the token is never put in a URL");
  assert.equal(digest.cookies.length, 1, "H3 the popup signs in with the session cookie");
  // The same value tests/test_view_sign_in.py pins for server.py's _session_cookie_value().
  assert.equal(digest.cookies[0].value, "4c98a261ffb59d2fb844723e5a40c3f2be729f554dce4a3badbc08d507e3e5d5",
    "H3 the cookie value matches the server's session cookie for the same token");
  assert.equal(digest.cookies[0].name, "cd_session", "H3 the cookie has the server's cookie name");
  assert.equal(digest.cookies[0].httpOnly, true, "H3 the cookie is HttpOnly, as the server sets it");
  assert.equal(new URL(digest.cookies[0].url).host, "server.test:7778", "H3 the cookie is set for the server");
  const unsetDigest = await popupOpenDigest({ server: "", token: "" });
  assert.deepEqual(unsetDigest.opened, [], "H3 no tab without settings");
  assert.equal(unsetDigest.cookies.length, 0, "H3 no cookie without settings");
  assert.ok(manifest.permissions.includes("cookies"), "H3 the manifest asks for the cookies permission");

  assert.equal(manifest.manifest_version, 3, "manifest stays on MV3");
  assert.equal(manifest.version, "0.6.3", "manifest version bumped so onInstalled update fires");
  assert.equal(manifest.action.default_popup, "popup.html", "the toolbar icon opens the popup");
  const bridgeScript = manifest.content_scripts.find((script) => script.js.includes("bridge.js"));
  assert.deepEqual(bridgeScript.matches, ["https://*.linkedin.com/*"], "the bridge is registered only on LinkedIn");
  assert.equal(bridgeScript.world, "MAIN", "the bridge runs in the MAIN world so it sees LinkedIn's own clipboard write");
  assert.doesNotMatch(bridgeJs, /console\.|chrome\.|fetch\(|XMLHttpRequest|localStorage|sessionStorage|sendBeacon/,
    "the bridge never logs, stores, or transmits clipboard text");
  assert.equal((contentJs.match(/addEventListener\("content-digest-copied-link"/g) || []).length, 1,
    "the content script listens for the bridge in exactly one place, the explicit post resolution");
  assert.match(contentJs, /removeEventListener\("content-digest-copied-link"/,
    "the content script stops listening once resolution finishes or times out");
  assert.doesNotMatch(contentJs, /console\.|chrome\.storage|fetch\(/, "the content script never logs or persists what it observes");

  assert.equal(CD.isContainerUrl(feed), true, "T3 recognizes the LinkedIn feed as a container");
  assert.equal(CD.linkedInPostUrl(["urn:li:activity:7498695844070723585"]), post, "T4 builds the proven activity permalink");
  assert.equal(CD.unwrapUrl(wrapper), "https://lnkd.in/ey84cgC7", "T5 unwraps LinkedIn safety/go");
  assert.equal(CD.contextIdentity({ pageUrl: feed, linkUrl: wrapper, itemUrl: post }), post, "T5 prefers the containing post over an unresolvable lnkd.in link");
  assert.equal(CD.unwrapUrl("https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fa"), "https://example.com/a");
  assert.equal(CD.unwrapUrl("https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2Fb"), "https://example.com/b");
  assert.equal(CD.unwrapUrl("https://out.reddit.com/?url=https%3A%2F%2Fexample.com%2Fc"), "https://example.com/c");
  assert.equal(CD.unwrapUrl("https://href.li/?https://example.com/d"), "https://example.com/d");
  assert.equal(CD.unwrapUrl("https://away.vk.com/away.php?to=https%3A%2F%2Fexample.com%2Fe"), "https://example.com/e");
  assert.equal(CD.unwrapUrl("https://lnkd.in/p/evwG7VAv"), "https://lnkd.in/p/evwG7VAv", "working mobile links are left alone");
  assert.equal(CD.contextIdentity({ pageUrl: feed, itemUrl: "https://lnkd.in/p/evwG7VAv" }), "https://lnkd.in/p/evwG7VAv", "current LinkedIn copied post links identify the post");

  reset();
  fetchReply = async (url) => url.startsWith("https://lnkd.in/p/")
    ? { ok: true, status: 200, url: post, json: async () => ({}) }
    : { ok: true, status: 200, json: async () => ({ status: "saved", url: post }) };
  await sandbox.submit({ url: "https://lnkd.in/p/evwG7VAv" }, 1);
  assert.equal(requestBody().url, post, "current LinkedIn copied links resolve to a proven direct permalink before POST");
  const lookup = calls.find((call) => call[0] === "fetch" && call[1].startsWith("https://lnkd.in/p/"));
  assert.ok(lookup[2].signal instanceof AbortSignal, "the lnkd.in lookup carries a timeout, so a hung redirect cannot hold the queue");
  assert.equal(requestHeaders()["X-Client"], "extension", "every server POST names the client so the runtime watchdog can count real contact");
  assert.match(requestHeaders().Authorization || "", /^Bearer /, "the token still travels in the Authorization header, never in the body or URL");
  const addCall = calls.filter((call) => call[0] === "fetch").at(-1);
  assert.ok(addCall[2].signal instanceof AbortSignal, "the capture POST carries a timeout, so a silent server cannot hold the queue");

  reset();
  let result = await sandbox.capturePage({ id: 1, url: feed });
  assert.equal(result.outcome, "refused", "T3 refuses toolbar page capture on a feed");
  assert.equal(calls.some((call) => call[0] === "fetch"), false, "T3 never posts the feed URL");

  reset();
  contextReply = { itemUrl: post, title: "LinkedIn", content: "post body ".repeat(50) };
  let serverOutcomes = ["saved", "already_saved"];
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: serverOutcomes.shift(), url: post }) });
  await sandbox.captureContext({ selectionText: "" }, { id: 1, url: feed });
  result = await sandbox.captureContext({ selectionText: "" }, { id: 1, url: feed });
  assert.equal(result.outcome, "already_saved", "T4 and T9 report the second save as already saved");
  assert.deepEqual(Array.from(local.captureHistory, (item) => item.outcome).slice(0, 2), ["already_saved", "saved"]);

  // Real capture 2 (08:50:42): right-click on a feed post body where neither the
  // DOM nor the bridge yields a post identity. Must refuse, never post /feed/.
  reset();
  contextReply = {};
  result = await sandbox.captureContext({ selectionText: "" }, { id: 1, url: feed });
  assert.equal(result.outcome, "refused", "T4 feed right-click with no post identity is refused");
  assert.equal(calls.some((call) => call[0] === "fetch"), false, "T4 never posts the feed URL");
  assert.equal(local.captureHistory[0].outcome, "refused", "T4 the refusal is visible in history");

  // Real capture 3 (08:51:59): right-click on a safety/go anchor whose target is
  // a bare, non-redirecting lnkd.in code, with no containing post identity.
  reset();
  assert.equal(CD.contextIdentity({ pageUrl: feed, linkUrl: wrapper }), "", "T5 wrapper alone never becomes an item identity");
  result = await sandbox.captureContext({ linkUrl: wrapper }, { id: 1, url: feed });
  assert.equal(result.outcome, "refused", "T5 unresolvable wrapper without a containing post is refused");
  assert.equal(calls.some((call) => call[0] === "fetch"), false, "T5 never posts the wrapper or the feed");

  // A bare lnkd.in code pasted directly is not a saved content item.
  reset();
  assert.equal(CD.contextIdentity({ pageUrl: feed, itemUrl: "https://lnkd.in/ey84cgC7" }), "", "bare lnkd.in code is not a post identity");

  reset();
  contextReply = { itemUrl: post, title: "LinkedIn", content: "wrong fallback" };
  await sandbox.captureContext({ selectionText: "Selected LinkedIn post text" }, { id: 1, url: feed });
  assert.equal(requestBody().url, post, "T7 selection uses the post permalink");
  assert.equal(requestBody().content, "Selected LinkedIn post text", "T7 uses explicit selectionText");

  reset();
  const exact = "https://example.com/permalink?keep=this";
  await sandbox.submit({ url: exact }, 1);
  assert.equal(requestBody().url, exact, "T8 pasted permalinks are sent unchanged");
  const fetchCall = calls.filter((call) => call[0] === "fetch").at(-1);
  assert.equal(fetchCall[1].endsWith("/add_sync"), true, "M5 uses the synchronous endpoint");
  assert.equal(fetchCall[2].headers.Authorization, "Bearer test-token", "section 8 keeps bearer auth on every POST");

  reset();
  const reddit = "https://news.ycombinator.com/item?id=123";
  await sandbox.captureContext({ linkUrl: reddit }, { id: 1, url: "https://news.ycombinator.com/news" });
  assert.equal(requestBody().url, reddit, "T6 real feed anchors use their destination");

  reset();
  await sandbox.capturePage({ id: 1, url: "https://example.com/article" });
  assert.equal(requestBody().url, "https://example.com/article", "T1 plain page URL survives");
  assert.ok(requestBody().content.length > 200, "T1 rendered page text is included");

  reset();
  fetchReply = async () => ({ ok: false, status: 401, json: async () => ({}) });
  result = await sandbox.submit({ url: exact }, 1);
  assert.equal(result.outcome, "queued", "T10 bad auth queues the capture");
  assert.equal(local.pending.length, 1);
  assert.match(local.captureHistory[0].message, /token.*queued/i);
  assert.equal(calls.some((call) => call[0] === "alarm"), false, "T10 a token refusal sets no 15-minute retry");
  calls.length = 0;
  await sandbox.flushPending();
  assert.equal(calls.some((call) => call[0] === "fetch"), false, "T10 the timed retry skips a token-refused item");
  assert.equal(local.pending.length, 1, "T10 the token-refused item stays queued");
  assert.equal(calls.some((call) => call[0] === "clear" && call[1] === "cd-flush"), true, "T10 the alarm stops when only token-refused items wait");
  await listeners.storage({ configuredAt: { newValue: 2 } }, "sync");
  assert.equal(calls.some((call) => call[0] === "fetch"), false, "T10 a change outside local settings retries nothing");
  await listeners.storage({ token: { newValue: "new-token" } }, "local");
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 1, "T10 a settings change retries the token-refused item once");
  assert.equal(local.pending.length, 1, "T10 a still-wrong token keeps the item queued");
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
  await listeners.storage({ configuredAt: { newValue: 3 } }, "local");
  assert.equal(local.pending.length, 0, "T10 restored auth flushes the queue after the settings change");

  // A fix on the server side: the next accepted capture releases the queue.
  reset();
  local.pending = [{ url: exact + "&waiting", queuedAt: 1, queueReason: "AUTH: The server rejected the token." }];
  result = await sandbox.submit({ url: exact }, 1);
  assert.equal(result.outcome, "saved", "the new capture's answer does not wait for the queue");
  await settle();
  assert.equal(local.pending.length, 0, "T10 an accepted capture retries items waiting for settings");

  // A settings save with a still-wrong token stops at the first refusal.
  reset();
  local.pending = [1, 2, 3].map((n) => ({ url: exact + "&n=" + n, queuedAt: n, queueReason: "AUTH: The server rejected the token." }));
  fetchReply = async () => ({ ok: false, status: 401, json: async () => ({}) });
  await listeners.storage({ token: { newValue: "still-wrong" } }, "local");
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 1, "T10 a still-wrong token is tried once, not once per queued item");
  assert.equal(local.pending.length, 3, "T10 every refused item stays queued");

  // A token rotated on the server: the timed retry meets one refusal, and the
  // items it skipped wait for settings too instead of one refusal per tick.
  reset();
  local.pending = [1, 2].map((n) => ({ url: exact + "&t=" + n, queuedAt: n, queueReason: "Failed to fetch" }));
  alarms.add("cd-flush");
  fetchReply = async () => ({ ok: false, status: 401, json: async () => ({}) });
  await sandbox.flushPending();
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 1, "T10 the timed retry stops at the first token refusal");
  assert.deepEqual(Array.from(local.pending, (item) => item.queueReason.slice(0, 5)), ["AUTH:", "AUTH:"],
    "T10 the skipped items wait for settings too");
  assert.equal(alarms.has("cd-flush"), false, "T10 no timed retry is left to repeat the refusal");

  // Clearing the token turns a refused item into a CONFIG one; it still waits
  // for Settings instead of re-arming the timed retry.
  reset();
  local.pending = [{ url: exact, queuedAt: 1, queueReason: "AUTH: The server rejected the token." }];
  local.token = "";
  await listeners.storage({ token: { newValue: "" } }, "local");
  assert.match(local.pending[0].queueReason, /^CONFIG:/, "T10 a cleared token leaves the item waiting for settings");
  assert.equal(calls.some((call) => call[0] === "alarm"), false, "T10 missing settings never arm the 15-minute retry");

  // A capture queued while a flush waits on the network survives the flush.
  reset();
  held.length = 0;
  fetchReply = () => new Promise((resolve) => held.push(resolve));
  local.pending = [{ url: "https://example.com/old", queuedAt: 1, queueReason: "offline" }];
  const flushing = sandbox.flushPending();
  await settle();
  assert.equal(held.length, 1, "T11 the flush is waiting on the network");
  await sandbox.queuePending({ url: "https://example.com/new" }, "offline");
  await releaseUntil(flushing);
  assert.deepEqual(Array.from(local.pending, (item) => item.url), ["https://example.com/new"],
    "T11 a capture queued during a flush is kept, the delivered one is removed");

  // Two triggers at once (alarm and a settings save) post each item once.
  reset();
  held.length = 0;
  fetchReply = () => new Promise((resolve) => held.push(resolve));
  local.pending = [{ url: "https://example.com/once", queuedAt: 1, queueReason: "offline" }];
  await releaseUntil(Promise.all([sandbox.flushPending(), sandbox.flushPending({ retryRefused: true })]));
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 1, "T11 overlapping flushes post an item once");
  assert.equal(local.pending.length, 0);

  // Server down: one flush tries one item, not every item at 30 s each.
  reset();
  local.pending = [1, 2, 3].map((n) => ({ url: exact + "&d=" + n, queuedAt: n, queueReason: "Failed to fetch" }));
  fetchReply = async () => { throw new Error("offline"); };
  await sandbox.flushPending();
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 1, "T11 a flush stops at the first network failure");
  assert.equal(local.pending.length, 3, "T11 every item stays queued for the next retry");

  // An HTTP status error is about one item; the flush goes on.
  reset();
  local.pending = [1, 2].map((n) => ({ url: exact + "&h=" + n, queuedAt: n, queueReason: "Failed to fetch" }));
  const statuses = [500, 200];
  fetchReply = async () => { const status = statuses.shift(); return { ok: status === 200, status, json: async () => ({ status: "saved" }) }; };
  await sandbox.flushPending();
  assert.equal(calls.filter((call) => call[0] === "fetch").length, 2, "T11 an HTTP error on one item does not stop the flush");
  assert.deepEqual(Array.from(local.pending, (item) => item.url), [exact + "&h=1"]);

  reset();
  fetchReply = async () => { throw new Error("offline"); };
  await sandbox.submit({ url: exact }, 1);
  assert.equal(local.pending.length, 1, "T11 unreachable server queues the capture");
  assert.equal(calls.some((call) => call[0] === "alarm" && call[2].periodInMinutes === 15), true, "T11 keeps the 15-minute alarm");
  await sandbox.submit({ url: exact + "&second" }, 1);
  assert.equal(calls.filter((call) => call[0] === "alarm").length, 1, "T11 a second failed capture does not restart the 15-minute period");
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
  await sandbox.flushPending();
  assert.equal(local.pending.length, 0, "T11 reachable server flushes the queue");

  reset({});
  result = await sandbox.submit({ url: exact }, 1);
  assert.equal(result.outcome, "queued", "T12 fresh install has no silent server default");
  assert.equal(calls.some((call) => call[0] === "fetch"), false);

  reset({ server: "http://chosen.test", token: "chosen-token", migratedFromSync: true });
  sync.server = "http://old.test";
  sync.token = "old-token";
  await sandbox.migrateFromSync();
  assert.equal(local.server, "http://chosen.test", "T13 local server survives");
  assert.equal(local.token, "chosen-token", "T13 local token survives");
  assert.equal(local.migratedFromSync, true, "T13 migration guard survives");

  reset({ server: "http://local.test", token: "local-token" });
  Object.assign(sync, { server: "http://stale.test", token: "stale-token" });
  await sandbox.migrateFromSync();
  assert.equal(local.server, "http://local.test", "section 8 migration never clobbers local server");
  assert.equal(local.token, "local-token", "section 8 migration never clobbers local token");
  assert.equal(Object.keys(sync).length, 0, "section 8 migration purges sync unconditionally");

  // Browser restart: alarms may be gone, so startup flushes and re-arms.
  reset();
  local.pending = [{ url: exact, queuedAt: 1, queueReason: "Failed to fetch" }];
  fetchReply = async () => { throw new Error("offline"); };
  listeners.startup();
  await settleMenus();
  assert.equal(calls.some((call) => call[0] === "fetch"), true, "T11 browser startup retries the queue");
  assert.equal(alarms.has("cd-flush"), true, "T11 browser startup re-arms the alarm for what is left");

  reset();
  for (let i = 0; i < 101; i++) await sandbox.queuePending({ url: "https://example.com/" + i }, "offline");
  assert.equal(local.pending.length, 100, "section 8 keeps the queue cap at 100");

  reset();
  result = await sandbox.capturePage({ id: 1, url: "chrome://extensions" });
  assert.equal(result.outcome, "refused", "T14 chrome pages get a clear refusal");

  reset();
  for (let i = 0; i < 6; i++) await sandbox.addHistory("saved", "Saved.", "https://example.com/" + i);
  assert.equal(local.captureHistory.length, 5, "history stays at five results");
  sandbox.createMenu();
  await settleMenus();
  assert.equal(calls.some((call) => call[0] === "removeAll"), true, "T15 clears old menus before creation");

  reset();
  menus.clear();
  menuErrors.length = 0;
  listeners.installed({ reason: "chrome_update" });
  listeners.startup();
  await settleMenus();
  assert.deepEqual(menuErrors, [], "T15 onInstalled and onStartup together never create cd-save twice");
  assert.deepEqual(Array.from(menus), ["cd-save"], "T15 exactly one Save to Content Digest item remains");

  reset();
  menus.clear();
  menuErrors.length = 0;
  menuCreateThrows = true;
  sandbox.createMenu();
  await settleMenus();
  sandbox.createMenu();
  await settleMenus();
  assert.deepEqual(Array.from(menus), ["cd-save"], "T15 a failed rebuild does not block the next one");
  console.log("extension acceptance: " + assertionCount + " assertions passed");
}

// A promise that never settles ends node with exit 0 and no summary line;
// count that as a failure, not a pass.
let finished = false;
process.on("exit", () => {
  if (!finished && !process.exitCode) {
    console.error("extension acceptance: did not finish (a promise never settled)");
    process.exitCode = 1;
  }
});
run().then(() => { finished = true; }, (error) => { console.error(error); process.exitCode = 1; });
