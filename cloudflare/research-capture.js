// cloudflare/research-capture.js
// Slack → research-brain capture routing: the /research slash command and DMs to the app.
// The Worker only filters and dispatches; the private research-brain repo's capture.yml does the
// reading, saving and the DM reply. Never log message text here (this repo is public).

export const NOT_ALLOWED = "This command isn't available to you.";
export const USAGE = "Usage: /research <link> [note]";
export const ACK = "Got it, I'll confirm in our DM.";
export const HELP = "Send me a link (with an optional note) and I'll save it to the research library.";
export const FAILED_START = "Capture failed to start, try again later.";

const IGNORED_SUBTYPES = new Set(["message_changed", "message_deleted", "bot_message", "channel_join"]);

export function hasUrl(text) {
  return /https?:\/\/[^\s>|]+/.test(text || "");
}

export async function verifySlackSig(signingSecret, timestamp, rawBody, signature) {
  const now = Math.floor(Date.now() / 1000);
  if (!timestamp || Math.abs(now - parseInt(timestamp, 10)) > 300) return false;
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(signingSecret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(`v0:${timestamp}:${rawBody}`)));
  const hex = (signature || "").startsWith("v0=") ? signature.slice(3) : "";
  const sig = new Uint8Array((hex.match(/../g) || []).map((h) => parseInt(h, 16)));
  let diff = mac.length ^ sig.length;
  for (let i = 0; i < mac.length; i++) diff |= mac[i] ^ (sig[i] ?? 0);
  return diff === 0;
}

// Pure: decide what to do with a Slack message event.
export function classifyIm(event, trentId) {
  if (!event || event.channel_type !== "im") return { action: "ignore" };
  if (event.bot_id || IGNORED_SUBTYPES.has(event.subtype)) return { action: "ignore" };
  if (event.subtype && event.subtype !== "file_share") return { action: "ignore" };
  if (event.user !== trentId) return { action: "ignore" };
  const files = (event.files || [])
    .filter((f) => String(f.mimetype || "").startsWith("image/"))
    .map((f) => ({ url: f.url_private_download || f.url_private, mimetype: f.mimetype }));
  const isReply = Boolean(event.thread_ts && event.thread_ts !== event.ts);
  if (!isReply && !hasUrl(event.text) && files.length === 0) return { action: "help" };
  return { action: "dispatch", kind: isReply ? "reply" : "dm", files };
}

async function dispatchCapture(env, inputs) {
  try {
    const resp = await fetch(`https://api.github.com/repos/${env.RB_GITHUB_REPO}/actions/workflows/capture.yml/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RB_GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "chief-of-staff-bot",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    });
    if (!resp.ok) console.error(`research capture dispatch failed: ${resp.status}`);
    return resp.ok;
  } catch (e) {
    console.error(`research capture dispatch error: ${e}`);
    return false;
  }
}

async function slackApi(env, method, params) {
  const resp = await fetch(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.SLACK_BOT_TOKEN}`, "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params).toString(),
  });
  return resp.json();
}

async function postDm(env, user, text) {
  const open = await slackApi(env, "conversations.open", { users: user });
  if (!open.ok) return console.error(`conversations.open failed: ${open.error}`);
  const r = await slackApi(env, "chat.postMessage", { channel: open.channel.id, text });
  if (!r.ok) console.error(`chat.postMessage failed: ${r.error}`);
}

export async function handleResearchCommand(request, env, ctx) {
  if (request.headers.get("X-Slack-Retry-Num")) return new Response("", { status: 200 });
  const rawBody = await request.text();
  const ok = await verifySlackSig(env.SLACK_SIGNING_SECRET, request.headers.get("X-Slack-Request-Timestamp") || "",
    rawBody, request.headers.get("X-Slack-Signature") || "");
  if (!ok) return new Response("Unauthorized", { status: 401 });

  const p = new URLSearchParams(rawBody);
  const user = p.get("user_id") || "";
  const text = (p.get("text") || "").trim();
  if (user !== env.TRENT_SLACK_USER) return Response.json({ response_type: "ephemeral", text: NOT_ALLOWED });
  if (!hasUrl(text)) return Response.json({ response_type: "ephemeral", text: USAGE });

  const responseUrl = p.get("response_url") || "";
  ctx.waitUntil(
    dispatchCapture(env, { kind: "command", text, user, thread_ts: "", files: "[]", idem_key: p.get("trigger_id") || "" })
      .then((sent) => {
        if (!sent && responseUrl) {
          return fetch(responseUrl, { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ response_type: "ephemeral", text: FAILED_START }) });
        }
      }),
  );
  return Response.json({ response_type: "ephemeral", text: ACK });
}

// Shared by whichever Worker owns the app's Events URL.
export async function handleImEvent(event, env, ctx, eventId) {
  const d = classifyIm(event, env.TRENT_SLACK_USER);
  if (d.action === "help") ctx.waitUntil(postDm(env, event.user, HELP));
  if (d.action === "dispatch") {
    ctx.waitUntil(
      dispatchCapture(env, { kind: d.kind, text: event.text || "", user: event.user,
        thread_ts: d.kind === "reply" ? event.thread_ts : "", files: JSON.stringify(d.files), idem_key: eventId || event.ts })
        .then((sent) => { if (!sent) return postDm(env, event.user, FAILED_START); }),
    );
  }
  return new Response("OK");
}

export async function handleSlackEvents(request, env, ctx) {
  const rawBody = await request.text();
  let payload;
  try { payload = JSON.parse(rawBody); } catch { return new Response("OK"); }
  if (payload.type === "url_verification") return Response.json({ challenge: payload.challenge });
  if (request.headers.get("X-Slack-Retry-Num")) return new Response("OK");
  const ok = await verifySlackSig(env.SLACK_SIGNING_SECRET, request.headers.get("X-Slack-Request-Timestamp") || "",
    rawBody, request.headers.get("X-Slack-Signature") || "");
  if (!ok) return new Response("Unauthorized", { status: 401 });
  return handleImEvent(payload.event, env, ctx, payload.event_id);
}
