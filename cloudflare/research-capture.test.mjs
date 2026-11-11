// node --test cloudflare/
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  classifyIm, hasUrl, handleResearchCommand, handleImEvent, handleSlackEvents,
  FAILED_START, HELP, NOT_ALLOWED,
} from "./research-capture.js";

const TRENT = "U04ECG6KEA3";
const env = {
  TRENT_SLACK_USER: TRENT, SLACK_SIGNING_SECRET: "sek", SLACK_BOT_TOKEN: "xoxb",
  RB_GITHUB_PAT: "pat", RB_GITHUB_REPO: "trent-luecke/research-brain",
};

let calls;
let githubStatus;
beforeEach(() => {
  calls = [];
  githubStatus = 204;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: init.body });
    if (String(url).includes("api.github.com")) return new Response(null, { status: githubStatus });
    if (String(url).includes("conversations.open")) return Response.json({ ok: true, channel: { id: "D1" } });
    return Response.json({ ok: true, ts: "1.1" });
  };
});

function ctx() {
  const pending = [];
  return { waitUntil: (p) => pending.push(p), done: () => Promise.all(pending) };
}

function signed(body, headers = {}) {
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = "v0=" + createHmac("sha256", env.SLACK_SIGNING_SECRET).update(`v0:${ts}:${body}`).digest("hex");
  return new Request("https://w/slack/research", {
    method: "POST", body,
    headers: { "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig, ...headers },
  });
}

const im = (o) => ({ channel_type: "im", user: TRENT, ts: "1", text: "", ...o });

test("screenshot DM (file_share) is dispatched, not dropped", () => {
  const r = classifyIm(im({ subtype: "file_share", files: [{ url_private_download: "u", mimetype: "image/png" }] }), TRENT);
  assert.equal(r.action, "dispatch");
  assert.equal(r.kind, "dm");
  assert.deepEqual(r.files, [{ url: "u", mimetype: "image/png" }]);
});

test("wrapped and bare links detected", () => {
  assert.ok(hasUrl("<https://a.com|a.com>"));
  assert.ok(hasUrl("see https://a.com/x"));
  assert.ok(!hasUrl("hello"));
});

test("thread reply classified as reply", () => {
  assert.equal(classifyIm(im({ ts: "2", thread_ts: "1", text: "body" }), TRENT).kind, "reply");
});

test("top-level DM without a link or image gets help", () => {
  assert.equal(classifyIm(im({ text: "hello" }), TRENT).action, "help");
});

test("other users, bots, edits and non-DMs ignored", () => {
  assert.equal(classifyIm(im({ user: "U999", text: "https://a.com" }), TRENT).action, "ignore");
  assert.equal(classifyIm(im({ bot_id: "B1", text: "https://a.com" }), TRENT).action, "ignore");
  assert.equal(classifyIm(im({ subtype: "message_changed" }), TRENT).action, "ignore");
  assert.equal(classifyIm({ ...im({ text: "https://a.com" }), channel_type: "channel" }, TRENT).action, "ignore");
});

test("/research dispatches capture.yml with trigger_id as idem key", async () => {
  const c = ctx();
  const res = await handleResearchCommand(signed(new URLSearchParams({ user_id: TRENT, text: "https://a.com note", trigger_id: "T9", response_url: "https://hooks/x" }).toString()), env, c);
  await c.done();
  assert.equal(res.status, 200);
  const gh = calls.find((x) => x.url.includes("capture.yml/dispatches"));
  const inputs = JSON.parse(gh.body).inputs;
  assert.deepEqual([inputs.kind, inputs.user, inputs.idem_key, inputs.text], ["command", TRENT, "T9", "https://a.com note"]);
});

test("/research from someone else is refused without dispatch", async () => {
  const res = await handleResearchCommand(signed(new URLSearchParams({ user_id: "U999", text: "https://a.com" }).toString()), env, ctx());
  assert.equal((await res.json()).text, NOT_ALLOWED);
  assert.equal(calls.length, 0);
});

test("bad signature is rejected", async () => {
  const req = new Request("https://w", { method: "POST", body: "x", headers: { "X-Slack-Request-Timestamp": String(Math.floor(Date.now() / 1000)), "X-Slack-Signature": "v0=00" } });
  assert.equal((await handleResearchCommand(req, env, ctx())).status, 401);
});

test("retry header returns 200 without dispatch", async () => {
  const c = ctx();
  const res = await handleResearchCommand(signed("user_id=" + TRENT + "&text=https://a.com", { "X-Slack-Retry-Num": "1" }), env, c);
  await c.done();
  assert.equal(res.status, 200);
  assert.equal(calls.length, 0);
});

test("failed dispatch from a DM posts Failed-to-start", async () => {
  githubStatus = 401;
  const c = ctx();
  await handleImEvent(im({ text: "<https://a.com>" }), env, c, "Ev1");
  await c.done();
  const post = calls.find((x) => x.url.includes("chat.postMessage"));
  assert.ok(post && new URLSearchParams(post.body).get("text") === FAILED_START);
});

test("help DM is answered by the worker without dispatch", async () => {
  const c = ctx();
  await handleImEvent(im({ text: "hello" }), env, c, "Ev2");
  await c.done();
  assert.ok(!calls.some((x) => x.url.includes("api.github.com")));
  assert.equal(new URLSearchParams(calls.find((x) => x.url.includes("chat.postMessage")).body).get("text"), HELP);
});

test("events endpoint answers url_verification and passes event_id", async () => {
  const v = await handleSlackEvents(signed(JSON.stringify({ type: "url_verification", challenge: "abc" })), env, ctx());
  assert.equal((await v.json()).challenge, "abc");
  const c = ctx();
  await handleSlackEvents(signed(JSON.stringify({ type: "event_callback", event_id: "Ev3", event: im({ text: "<https://a.com>" }) })), env, c);
  await c.done();
  assert.equal(JSON.parse(calls.find((x) => x.url.includes("dispatches")).body).inputs.idem_key, "Ev3");
});
