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
  storage: { local: area(local), sync: area(sync) },
  alarms: {
    create: (name, options) => calls.push(["alarm", name, options]),
    clear: (name) => calls.push(["clear", name]),
    onAlarm: { addListener: (fn) => { listeners.alarm = fn; } },
  },
  action: {
    setBadgeText: (x) => calls.push(["badge", x.text]),
    setBadgeBackgroundColor: () => {},
  },
  contextMenus: {
    removeAll: (callback) => { calls.push(["removeAll"]); callback(); },
    create: (options) => calls.push(["menu", options]),
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
  contextReply = {};
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
}

function requestBody(index = -1) {
  const fetches = calls.filter((call) => call[0] === "fetch");
  return JSON.parse(fetches.at(index)[2].body);
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

  assert.equal(manifest.manifest_version, 3, "manifest stays on MV3");
  assert.equal(manifest.version, "0.6.0", "manifest version bumped so onInstalled update fires");
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
  fetchReply = async () => ({ ok: true, status: 200, json: async () => ({ status: "saved" }) });
  await sandbox.flushPending();
  assert.equal(local.pending.length, 0, "T10 restored auth flushes the queue");

  reset();
  fetchReply = async () => { throw new Error("offline"); };
  await sandbox.submit({ url: exact }, 1);
  assert.equal(local.pending.length, 1, "T11 unreachable server queues the capture");
  assert.equal(calls.some((call) => call[0] === "alarm" && call[2].periodInMinutes === 15), true, "T11 keeps the 15-minute alarm");
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
  assert.equal(calls.some((call) => call[0] === "removeAll"), true, "T15 clears old menus before creation");
  console.log("extension acceptance: " + assertionCount + " assertions passed");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
