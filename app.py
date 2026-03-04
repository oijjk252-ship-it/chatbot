import os
import html
import requests
from flask import Flask, request

# ======================
# TOKENS VIA ENV (Render -> Environment)
# ======================
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
MODAL_API_KEY = os.environ["MODAL_API_KEY"]  # modalresearch_...
MODEL = os.environ.get("MODAL_MODEL", "zai-org/GLM-5-FP8")

MODAL_URL = "https://api.us-west-2.modal.direct/v1/chat/completions"
TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SYSTEM_PROMPT = (
    "You are a friendly, professional AI assistant.\n"
    "Style rules:\n"
    "1) Keep answers easy to understand, structured with short sections/bullets.\n"
    "2) Always be polite, friendly, and professional.\n"
    "3) ALWAYS end every response with this exact footer on a new line:\n"
    "   — Developed by Bishal\n"
    "4) If the user asks for code, return code in a single HTML block:\n"
    "   <pre><code>...code...</code></pre>\n"
    "   Keep it minimal and copy-ready.\n"
    "5) Do NOT use Markdown. Use plain text + simple HTML tags only.\n"
)

# 🧠 Memory: last 10 turns (per user). Resets on redeploy/restart.
user_history = {}
MAX_MESSAGES = 20  # 10 turns

app = Flask(__name__)

def safe_html(text: str) -> str:
    """Escape everything then allow a small whitelist of Telegram HTML tags."""
    escaped = html.escape(text)
    allowed = {
        "&lt;b&gt;": "<b>", "&lt;/b&gt;": "</b>",
        "&lt;pre&gt;": "<pre>", "&lt;/pre&gt;": "</pre>",
        "&lt;code&gt;": "<code>", "&lt;/code&gt;": "</code>",
    }
    for k, v in allowed.items():
        escaped = escaped.replace(k, v)
    return escaped

def send_message(chat_id: int, text: str):
    safe = safe_html(text)
    for i in range(0, len(safe), 3500):
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": safe[i:i+3500], "parse_mode": "HTML"},
            timeout=20,
        )

def call_modal(user_id: int, user_text: str) -> str:
    hist = user_history.get(user_id, [])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist + [{"role": "user", "content": user_text}]

    r = requests.post(
        MODAL_URL,
        headers={"Authorization": f"Bearer {MODAL_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": messages, "max_tokens": 700},
        timeout=60,
        proxies={"http": None, "https": None},
    )

    if r.status_code != 200:
        return f"⚠️ AI error {r.status_code}:\n{r.text}\n— Developed by Bishal"

    reply = r.json()["choices"][0]["message"]["content"]

    if "— Developed by Bishal" not in reply:
        reply = reply.rstrip() + "\n— Developed by Bishal"

    # update memory
    hist += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
    user_history[user_id] = hist[-MAX_MESSAGES:]

    return reply

@app.get("/")
def home():
    return "OK"

@app.post("/webhook")
def webhook():
    update = request.get_json(force=True)

    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    user_id = (message.get("from") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not user_id:
        return "ok"

    if text.startswith("/start"):
        send_message(chat_id, "Hello 👋\nSend a message.\n— Developed by Bishal")
        return "ok"

    if text.startswith("/clear"):
        user_history.pop(user_id, None)
        send_message(chat_id, "✅ Memory cleared\n— Developed by Bishal")
        return "ok"

    if text:
        reply = call_modal(user_id, text)
        send_message(chat_id, reply)

    return "ok"
