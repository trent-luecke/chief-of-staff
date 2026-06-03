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

async function handleSlackTask(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp");
  const signature = request.headers.get("X-Slack-Signature");

  if (!timestamp || !signature) {
    return new Response("Unauthorized", { status: 401 });
  }

  // Reject requests older than 5 minutes (replay attack prevention)
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) {
    return new Response("Unauthorized", { status: 401 });
  }

  const rawBody = await request.text();
  const sigBase = `v0:${timestamp}:${rawBody}`;
  const encoder = new TextEncoder();

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.SLACK_SIGNING_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode(sigBase));
  const expected =
    "v0=" +
    Array.from(new Uint8Array(mac))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

  if (expected !== signature) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const responseUrl = params.get("response_url") || "";

  if (!text) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [due:<date>]",
    });
  }

  const dueMatch = text.match(/\bdue:(\S+)/i);
  const dueDateRaw = dueMatch ? dueMatch[1] : "";
  const title = text.replace(/\bdue:\S+/i, "").trim();

  if (!title) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [due:<date>]",
    });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw: dueDateRaw,
    })
  );

  return Response.json({
    response_type: "ephemeral",
    text: "Adding task...",
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
