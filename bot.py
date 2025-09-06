import os
import time
import requests
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# Load credentials from environment variables
EMAIL = os.getenv("generalderp07@gmail.com")          # your Gmail address
PASSWORD = os.getenv("ujmohfmrnbrxuelx") # Gmail App Password (no spaces!)
DISCORD_WEBHOOK_URL = os.getenv("https://discord.com/api/webhooks/1413774501312729149/kP-3sw8glZCreCL3mlNoNZVo9-msbsbhcl6O3zplTfdwd4vsT_MIAeXewoHEoVOERYUC") # your Discord webhook

# Config
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds between checks
ALLOWED_SENDER = "entalabador@mymail.mapua.edu.ph"
SUBJECT_KEYWORDS = ["due soon", "announcement"]

def extract_text(msg):
    """Extract plain text from HTML or plain email body"""
    if msg.html:
        soup = BeautifulSoup(msg.html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
    else:
        text = msg.text or ""
    return text[:1000]  # limit to avoid flooding Discord

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
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

def check_mail():
    """Check Gmail for new matching emails"""
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            if msg.from_ == ALLOWED_SENDER and any(word.lower() in msg.subject.lower() for word in SUBJECT_KEYWORDS):
                text_preview = extract_text(msg)
                send_to_discord(msg.from_, msg.subject, text_preview)

if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", e)
        time.sleep(CHECK_INTERVAL)
