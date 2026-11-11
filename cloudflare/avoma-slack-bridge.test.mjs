// node --test cloudflare/avoma-slack-bridge.test.mjs
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import bridge from "./avoma-slack-bridge.js";

const env = {
  SLACK_SIGNING_SECRET: "sek", SLACK_BOT_TOKEN: "xoxb", GITHUB_PAT: "pat", GITHUB_REPO: "trent-luecke/claude-projects",
  AVOMA_CHANNEL_ID: "C_AVOMA", TRENT_SLACK_USER: "U04ECG6KEA3", RB_GITHUB_PAT: "rbpat", RB_GITHUB_REPO: "trent-luecke/research-brain",
};
let calls;
beforeEach(() => {
  calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: init.body });
    if (String(url).includes("api.github.com")) return new Response(null, { status: 204 });
    if (String(url).includes("conversations.open")) return Response.json({ ok: true, channel: { id: "D1" } });
    return Response.json({ ok: true });
  };
});
const ctx = () => { const p = []; return { waitUntil: (x) => p.push(x), done: () => Promise.all(p) }; };
function signed(obj) {
  const body = JSON.stringify(obj);
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = "v0=" + createHmac("sha256", env.SLACK_SIGNING_SECRET).update(`v0:${ts}:${body}`).digest("hex");
  return new Request("https://w", { method: "POST", body, headers: { "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig } });
}

test("Avoma thread reply still dispatches the Avoma workflow (regression)", async () => {
  const c = ctx();
  await bridge.fetch(signed({ type: "event_callback", event_id: "E1", event: {
    type: "message", channel: "C_AVOMA", channel_type: "channel", user: "U1", ts: "2", thread_ts: "1", text: "ready to process" } }), env, c);
  await c.done();
  assert.ok(calls.some((x) => x.url.includes("avoma_slack_trigger.yml/dispatches")));
  assert.ok(!calls.some((x) => x.url.includes("capture.yml")));
});

test("DM to the app routes to research capture", async () => {
  const c = ctx();
  await bridge.fetch(signed({ type: "event_callback", event_id: "E2", event: {
    type: "message", channel: "D1", channel_type: "im", user: "U04ECG6KEA3", ts: "3", text: "<https://a.com>" } }), env, c);
  await c.done();
  const gh = calls.find((x) => x.url.includes("research-brain/actions/workflows/capture.yml"));
  assert.ok(gh);
  assert.equal(JSON.parse(gh.body).inputs.idem_key, "E2");
  assert.ok(!calls.some((x) => x.url.includes("avoma_slack_trigger")));
});

test("screenshot DM (file_share subtype) reaches capture, not the subtype filter", async () => {
  const c = ctx();
  await bridge.fetch(signed({ type: "event_callback", event_id: "E3", event: {
    type: "message", subtype: "file_share", channel: "D1", channel_type: "im", user: "U04ECG6KEA3", ts: "4", text: "",
    files: [{ url_private_download: "https://files.slack.com/x.png", mimetype: "image/png" }] } }), env, c);
  await c.done();
  assert.ok(calls.some((x) => x.url.includes("capture.yml")));
});
