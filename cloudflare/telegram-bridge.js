// cloudflare/telegram-bridge.js

async function dispatchToGitHub(env, workflow, inputs) {
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "chief-of-staff-bot",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (!resp.ok) {
    console.error(`GitHub API error: ${resp.status} ${await resp.text()}`);
  }
}

// Constant-time HMAC-SHA256 verification for Slack request signatures.
async function verifySlackSig(signingSecret, timestamp, rawBody, signature) {
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) return false;
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(signingSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode(`v0:${timestamp}:${rawBody}`));
  const macBytes = new Uint8Array(mac);
  const sigHex = signature.startsWith("v0=") ? signature.slice(3) : "";
  const sigBytes = new Uint8Array((sigHex.match(/../g) || []).map((h) => parseInt(h, 16)));
  // OR all XOR differences — prevents timing oracle
  let diff = macBytes.length ^ sigBytes.length;
  for (let i = 0; i < macBytes.length; i++) diff |= macBytes[i] ^ (sigBytes[i] ?? 0);
  return diff === 0;
}

async function handleSlackTask(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp") || "";
  const signature = request.headers.get("X-Slack-Signature") || "";

  if (!timestamp || !signature) return new Response("Unauthorized", { status: 401 });

  const rawBody = await request.text();

  if (!await verifySlackSig(env.SLACK_SIGNING_SECRET, timestamp, rawBody, signature)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const responseUrl = params.get("response_url") || "";
  const channelId = params.get("channel_id") || "";
  const userId = params.get("user_id") || "";

  if (!text) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [owner:<name>] [due:<date>]",
    });
  }

  // Extract owner:<name> token (single word; order-independent with due:)
  const ownerMatch = text.match(/\bowner:(\S+)/i);
  const ownerRaw = ownerMatch ? ownerMatch[1] : "";
  const textWithoutOwner = ownerMatch
    ? text.replace(ownerMatch[0], "").replace(/\s+/g, " ").trim()
    : text;

  // Extract due:<date> from whatever remains (may be multi-word phrase to end of string)
  const dueMatch = textWithoutOwner.match(/\bdue:(.+)$/i);
  const dueDateRaw = dueMatch ? dueMatch[1].trim() : "";
  const title = dueMatch ? textWithoutOwner.slice(0, dueMatch.index).trim() : textWithoutOwner.trim();

  if (!title) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [owner:<name>] [due:<date>]",
    });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw: dueDateRaw,
      owner_raw: ownerRaw,
      channel_id: channelId,
      user_id: userId,
    })
  );

  return Response.json({
    response_type: "ephemeral",
    text: "Adding task...",
  });
}

// Handles button clicks from interactive owner-disambiguation messages.
async function handleSlackInteractive(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp") || "";
  const signature = request.headers.get("X-Slack-Signature") || "";

  if (!timestamp || !signature) return new Response("Unauthorized", { status: 401 });

  const rawBody = await request.text();

  if (!await verifySlackSig(env.SLACK_SIGNING_SECRET, timestamp, rawBody, signature)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  let payload;
  try {
    payload = JSON.parse(params.get("payload") || "{}");
  } catch {
    return new Response("Bad Request", { status: 400 });
  }

  const action = payload.actions?.[0];
  if (!action || !action.action_id.startsWith("assign_owner")) {
    return Response.json({ text: "Unknown action." });
  }

  let taskData;
  try {
    taskData = JSON.parse(action.value);
  } catch {
    return Response.json({ text: "Invalid action data." });
  }

  const { title, due_date_raw = "", owner_raw } = taskData;
  const responseUrl = payload.response_url || "";

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw,
      owner_raw,
    })
  );

  // Replace the buttons with a simple acknowledgement immediately
  return Response.json({
    replace_original: true,
    text: `Got it — adding task and assigning to ${owner_raw}...`,
  });
}

export default {
  // ctx (ExecutionContext) lets us use ctx.waitUntil() to fire GitHub dispatch
  // after returning OK, so Telegram/Slack don't retry on slow GitHub responses.
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("OK");

    const url = new URL(request.url);

    if (url.pathname === "/slack/task") {
      return handleSlackTask(request, env, ctx);
    }

    if (url.pathname === "/slack/interactive") {
      return handleSlackInteractive(request, env, ctx);
    }

    // Telegram path
    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (secret !== env.TELEGRAM_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("OK");
    }

    const message = body?.message;
    if (!message?.text || !message?.chat?.id) return new Response("OK");

    console.log(
      `Telegram message received: "${message.text}" from chat ${message.chat.id}`
    );

    const inputs = {
      query: message.text,
      chat_id: String(message.chat.id),
    };
    const replyToId = message.reply_to_message?.message_id;
    if (replyToId) inputs.reply_to_message_id = String(replyToId);

    ctx.waitUntil(dispatchToGitHub(env, "ask.yml", inputs));
    return new Response("OK");
  },
};
