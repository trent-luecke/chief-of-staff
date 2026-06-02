// cloudflare/avoma-slack-bridge.js
// Slack Events API bridge → GitHub Actions dispatch for Avoma thread processing.

async function verifySlackSignature(request, body, signingSecret) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp");
  const provided = request.headers.get("X-Slack-Signature");
  if (!timestamp || !provided) return false;

  // Replay protection: reject if > 5 minutes old
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) return false;

  const encoder = new TextEncoder();
  const keyData = encoder.encode(signingSecret);
  const msgData = encoder.encode(`v0:${timestamp}:${body}`);

  const key = await crypto.subtle.importKey(
    "raw", keyData, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, msgData);
  const hexSig = "v0=" + Array.from(new Uint8Array(sig))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");

  // Constant-time comparison
  if (hexSig.length !== provided.length) return false;
  let diff = 0;
  for (let i = 0; i < hexSig.length; i++) {
    diff |= hexSig.charCodeAt(i) ^ provided.charCodeAt(i);
  }
  return diff === 0;
}

async function dispatchToGitHub(env, thread_ts, channel_id, trigger_text) {
  const inputs = { thread_ts, channel_id, trigger_text };
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/avoma_slack_trigger.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "chief-of-staff-avoma-bridge",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (!resp.ok) {
    console.error(`GitHub dispatch error: ${resp.status} ${await resp.text()}`);
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("OK");

    const body = await request.text();

    // Parse body first so we can handle url_verification before signature check.
    // Slack sends the challenge without a valid signature during initial setup.
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return new Response("OK");
    }

    // Handle Slack's initial url_verification challenge (no signature required)
    if (payload.type === "url_verification") {
      return new Response(JSON.stringify({ challenge: payload.challenge }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // Verify Slack signature for all real events
    const valid = await verifySlackSignature(request, body, env.SLACK_SIGNING_SECRET);
    if (!valid) return new Response("Unauthorized", { status: 401 });

    const event = payload.event;
    if (!event) return new Response("OK");

    // Drop: non-message events, any subtype (bot_message, message_changed, etc.), bot messages
    if (event.type !== "message") return new Response("OK");
    if (event.subtype) return new Response("OK");
    if (event.bot_id) return new Response("OK");

    // Only process events in the configured Avoma channel
    if (event.channel !== env.AVOMA_CHANNEL_ID) return new Response("OK");

    // Only process thread replies, not root posts
    // Root posts have thread_ts === ts (or no thread_ts)
    if (!event.thread_ts || event.thread_ts === event.ts) return new Response("OK");

    const thread_ts = event.thread_ts;
    const channel_id = event.channel;
    const trigger_text = (event.text || "").trim();

    console.log(`Avoma thread reply: thread_ts=${thread_ts}, text="${trigger_text.slice(0, 60)}"`);

    // Ack immediately; dispatch runs in background after response is sent
    ctx.waitUntil(dispatchToGitHub(env, thread_ts, channel_id, trigger_text));
    return new Response("OK");
  },
};
