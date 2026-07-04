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
    return false;
  }
  return true;
}

async function postEphemeral(responseUrl, text) {
  if (!responseUrl) return;
  try {
    await fetch(responseUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response_type: "ephemeral", replace_original: true, text }),
    });
  } catch (e) {
    console.error(`Failed to post ephemeral to Slack: ${e}`);
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
      text: "Usage: /task <title> [owner:<name>] [due:<date>] [horizon:<date>]",
    });
  }

  // Extract owner:<name> token (single word; order-independent with due:/horizon:)
  const ownerMatch = text.match(/\bowner:(\S+)/i);
  const ownerRaw = ownerMatch ? ownerMatch[1] : "";
  const textWithoutOwner = ownerMatch
    ? text.replace(ownerMatch[0], "").replace(/\s+/g, " ").trim()
    : text;

  // Extract due:<date> and horizon:<date> tokens (multi-word values; either order)
  const tokenRe = /\b(due|horizon):/gi;
  const tokens = [...textWithoutOwner.matchAll(tokenRe)];
  const title = tokens.length
    ? textWithoutOwner.slice(0, tokens[0].index).trim()
    : textWithoutOwner.trim();
  let dueDateRaw = "";
  let horizonRaw = "";
  tokens.forEach((m, i) => {
    const start = m.index + m[0].length;
    const end = i + 1 < tokens.length ? tokens[i + 1].index : textWithoutOwner.length;
    const val = textWithoutOwner.slice(start, end).trim();
    if (m[1].toLowerCase() === "due") dueDateRaw = val;
    else horizonRaw = val;
  });

  if (!title) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [owner:<name>] [due:<date>] [horizon:<date>]",
    });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw: dueDateRaw,
      horizon_raw: horizonRaw,
      owner_raw: ownerRaw,
      channel_id: channelId,
      user_id: userId,
    }).then(ok => {
      if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue task — GitHub dispatch error. Try again or check the PAT.");
    })
  );

  return Response.json({
    response_type: "ephemeral",
    text: "Adding task...",
  });
}

async function handleSlackNote(request, env, ctx) {
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

  const usage = "Usage: /note <body> [person:<name>] [project:<name>] [tag:<TAG>]";
  if (!text) {
    return Response.json({ response_type: "ephemeral", text: usage });
  }

  // Extract single-word tokens; order-independent. Body is whatever remains.
  let rest = text;
  const grab = (re) => {
    const m = rest.match(re);
    if (!m) return "";
    rest = rest.replace(m[0], "").replace(/\s+/g, " ").trim();
    return m[1];
  };
  const personRaw = grab(/\bperson:(\S+)/i);
  const projectRaw = grab(/\bproject:(\S+)/i);
  const tagRaw = grab(/\btag:(\S+)/i);
  const body = rest.trim();

  if (!body) {
    return Response.json({ response_type: "ephemeral", text: usage });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "note_add.yml", {
      body,
      response_url: responseUrl,
      person_raw: personRaw,
      project_raw: projectRaw,
      tag_raw: tagRaw,
      channel_id: channelId,
      user_id: userId,
    }).then(ok => {
      if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue note — GitHub dispatch error. Try again or check the PAT.");
    })
  );

  return Response.json({ response_type: "ephemeral", text: "Adding note..." });
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
  const responseUrl = payload.response_url || "";

  let data;
  try {
    data = JSON.parse(action?.value || "{}");
  } catch {
    return Response.json({ text: "Invalid action data." });
  }

  // Note person disambiguation → note_add.yml
  if (action?.action_id?.startsWith("link_note_person")) {
    const { body, project_raw = "", tag = "", person_raw = "" } = data;
    ctx.waitUntil(
      dispatchToGitHub(env, "note_add.yml", {
        body,
        response_url: responseUrl,
        person_raw,
        project_raw,
        tag_raw: tag,
      }).then(ok => {
        if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue note — GitHub dispatch error. Try again or check the PAT.");
      })
    );
    const who = person_raw || "no one";
    return Response.json({
      replace_original: true,
      text: `⏳ Saving note (→ ${who})...`,
      blocks: [
        { type: "section", text: { type: "mrkdwn", text: `⏳ Saving note (→ ${who})...` } },
      ],
    });
  }

  // Task owner disambiguation → task_add.yml (unchanged behavior)
  if (action?.action_id?.startsWith("assign_owner")) {
    const { title, due_date_raw = "", owner_raw } = data;
    const horizon_raw = data.horizon_raw || "";
    ctx.waitUntil(
      dispatchToGitHub(env, "task_add.yml", {
        title,
        response_url: responseUrl,
        due_date_raw,
        horizon_raw,
        owner_raw,
      }).then(ok => {
        if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue task — GitHub dispatch error. Try again or check the PAT.");
      })
    );
    return Response.json({
      replace_original: true,
      text: `⏳ Assigning to ${owner_raw}...`,
      blocks: [
        { type: "section", text: { type: "mrkdwn", text: `⏳ Assigning *${title}* to ${owner_raw}...` } },
      ],
    });
  }

  return Response.json({ text: "Unknown action." });
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

    if (url.pathname === "/slack/note") {
      return handleSlackNote(request, env, ctx);
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

  // Cron Trigger (see wrangler.toml [triggers]). Fires the daily brief punctually
  // at 7am CDT instead of relying on GitHub's best-effort scheduler. brief.yml's
  // own `schedule:` remains a backstop; the brief's same-day guard dedupes.
  async scheduled(event, env, ctx) {
    console.log(`Cron fired (${event.cron}) — dispatching brief.yml`);
    ctx.waitUntil(
      dispatchToGitHub(env, "brief.yml", {}).then((ok) => {
        if (!ok) console.error("brief.yml dispatch failed — GitHub schedule backstop will still run.");
      })
    );
  },
};
