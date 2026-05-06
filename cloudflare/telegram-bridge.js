// cloudflare/telegram-bridge.js
async function dispatchToGitHub(env, message) {
  const inputs = {
    query: message.text,
    chat_id: String(message.chat.id),
  };

  const replyToId = message.reply_to_message?.message_id;
  if (replyToId) {
    inputs.reply_to_message_id = String(replyToId);
  }

  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/ask.yml/dispatches`,
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

export default {
  // ctx (ExecutionContext) is required so we can use ctx.waitUntil() to fire
  // the GitHub dispatch *after* returning OK to Telegram. Without this,
  // Telegram retries the webhook if GitHub is slow, creating duplicate runs.
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("OK");

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

    console.log(`Telegram message received: "${message.text}" from chat ${message.chat.id}`);

    // Acknowledge immediately — Telegram will not retry if we respond quickly.
    // The GitHub dispatch runs in the background after the response is sent.
    ctx.waitUntil(dispatchToGitHub(env, message));
    return new Response("OK");
  },
};
