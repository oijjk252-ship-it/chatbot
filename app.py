import os
import html
import requests
from flask import Flask, request

# ===== ENV VARS (Render -> Environment) =====
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
MODAL_API_KEY = os.environ["MODAL_API_KEY"]
MODEL = os.environ.get("MODAL_MODEL", "zai-org/GLM-5-FP8")

MODAL_URL = "https://api.us-west-2.modal.direct/v1/chat/completions"
TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ✅ Faster + shorter by default
SYSTEM_PROMPT = (
    "You are a friendly, professional AI assistant.\n"
    "Prefer short, clear answers by default. If the user asks for details, then expand.\n"
    "Use simple bullet points when helpful.\n"
    "If the user asks for code, return a single <pre><code>...</code></pre> block that is easy to copy.\n"
    "Always end every response with: — Developed by Bishal\n"
    "Use plain text + simple HTML only.\n"
)

# ✅ Faster memory: keep last 4 turns (8 messages)
user_history = {}
MAX_MESSAGES = 8  # was 20 (10 turns)

app = Flask(__name__)

def safe_html(text: str) -> str:
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
        resp = requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": safe[i:i+3500], "parse_mode": "HTML"},
            timeout=20,
        )
        if resp.status_code != 200:
            print("Telegram sendMessage failed:", resp.status_code, resp.text)

def call_modal(user_id: int, user_text: str) -> str:
    hist = user_history.get(user_id, [])[-MAX_MESSAGES:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist + [{"role": "user", "content": user_text}]

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 200,  # ✅ was 700 (big speed boost)
    }
    headers = {"Authorization": f"Bearer {MODAL_API_KEY}", "Content-Type": "application/json"}

    # ✅ 1 retry on read timeout (helps when the model is busy)
    for attempt in range(2):
        try:
            r = requests.post(
                MODAL_URL,
                headers=headers,
                json=payload,
                timeout=(15, 90),               # connect, read
                proxies={"http": None, "https": None},
            )
            if r.status_code != 200:
                return f"⚠️ AI error {r.status_code}:\n{r.text}\n— Developed by Bishal"

            reply = r.json()["choices"][0]["message"]["content"]
            if "— Developed by Bishal" not in reply:
                reply = reply.rstrip() + "\n— Developed by Bishal"

            hist = hist + [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
            user_history[user_id] = hist[-MAX_MESSAGES:]
            return reply

        except requests.exceptions.ReadTimeout:
            if attempt == 0:
                continue
            return "⚠️ The AI is busy right now. Please try again.\n— Developed by Bishal"
        except Exception as e:
            return f"⚠️ Network error:\n{e}\n— Developed by Bishal"

@app.get("/")
def home():
    return "OK"

@app.post("/webhook")
def webhook():
    update = request.get_json(force=True)
    print("Incoming update:", update)

    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    user_id = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()

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
        # ✅ Quick UX response so it feels faster
        send_message(chat_id, "⏳ Working on it…\n— Developed by Bishal")
        reply = call_modal(user_id, text)
        send_message(chat_id, reply)

    return "ok"
