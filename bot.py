import os
import time
import requests
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# ---- env helpers ----
def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"❌ Missing env var: {name}. Set it in Heroku: heroku config:set {name}=... -a <your-app>")
        raise SystemExit(1)
    return val

# Load credentials from environment variables (✅ use proper names)
EMAIL = require_env("GMAIL_EMAIL")                 # e.g. generalderp07@gmail.com
PASSWORD = require_env("GMAIL_APP_PASSWORD")       # 16-char Gmail App Password (no spaces)
DISCORD_WEBHOOK_URL = require_env("DISCORD_WEBHOOK_URL")  # your Discord webhook URL

# Config
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds between checks
ALLOWED_SENDER = "entalabador@mymail.mapua.edu.ph"
SUBJECT_KEYWORDS = ["due soon", "announcement"]

def extract_text(msg):
    """Extract plain text from HTML or plain email body safely"""
    try:
        html_content = msg.html or ""     # always a string
        text_content = msg.text or ""     # always a string

        if html_content.strip():
            soup = BeautifulSoup(html_content, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
        elif text_content.strip():
            text = text_content
        else:
            text = "(no content)"
    except Exception as e:
        print("⚠️ Extract error:", repr(e))
        text = "(error extracting text)"
    # ensure string and trim
    return str(text)[:1000]

def send_to_discord(sender, subject, preview):
    """Send nicely formatted embed message to Discord"""
    payload = {
        "embeds": [
            {
                "title": f"<@&1413784173570818080>, Let it be known unto all good subjects, that His Most Gracious Majesty, King {sender}, hath dispatched word from the depths of hell.",
                "description": f"**Subject:** {subject}\n\n**Preview:**\n{preview}",
                "color": 5814783
            }
        ]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
        if r.status_code not in (200, 204):
            print("⚠️ Discord webhook error:", r.status_code, r.text[:300])
        else:
            print("✅ Sent to Discord:", subject)
    except Exception as e:
        print("⚠️ Discord post failed:", repr(e))

def check_mail():
    """Check Gmail for new matching emails"""
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, "INBOX") as mailbox:
        # mark_seen=True prevents re-sending the same emails every minute
        for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
            sender_email = (msg.from_ or "").lower()
            subject = msg.subject or ""
            if sender_email == ALLOWED_SENDER.lower() and any(
                word.lower() in subject.lower() for word in SUBJECT_KEYWORDS
            ):
                text_preview = extract_text(msg)
                send_to_discord(msg.from_, subject, text_preview)
            else:
                # Uncomment for debugging:
                # print("⏭️ Skipped:", sender_email, "|", subject)
                pass

if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", repr(e))
        time.sleep(CHECK_INTERVAL)
