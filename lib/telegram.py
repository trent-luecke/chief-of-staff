import requests


def send_message(bot_token: str, chat_id: str, text: str) -> int | None:
    """Send a Telegram message. Returns the message_id assigned by Telegram, or None on error."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()
    try:
        return resp.json()["result"]["message_id"]
    except (KeyError, ValueError):
        return None
