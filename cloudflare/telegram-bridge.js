// cloudflare/telegram-bridge.js
export default {
  async fetch(request, env) {
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
        body: JSON.stringify({
          ref: "main",
          inputs: {
            query: message.text,
            chat_id: String(message.chat.id),
          },
        }),
      }
    );

    if (!resp.ok) {
      console.error(`GitHub API error: ${resp.status} ${await resp.text()}`);
    }

    return new Response("OK");
  },
};
