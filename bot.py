import os
import time
import requests
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# Load credentials from environment variables
EMAIL = os.getenv("generalderp07@gmail.com")          
PASSWORD = os.getenv("ujmohfmrnbrxuelx") 
DISCORD_WEBHOOK_URL = os.getenv("https://discord.com/api/webhooks/1413774501312729149/kP-3sw8glZCreCL3mlNoNZVo9-msbsbhcl6O3zplTfdwd4vsT_MIAeXewoHEoVOERYUC") 

# Config
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds between checks
ALLOWED_SENDER = "entalabador@mymail.mapua.edu.ph"

def safe_str(value):
    """Return a safe string, never None"""
    return str(value) if value is not None else ""

def extract_course_body_link(msg):
    """Extract course name, body text, and a 'View' link from the HTML email"""
    course = "(Unknown Course)"
    body_text = "(No content)"
    link = None

    try:
        html_content = safe_str(msg.html)
        text_content = safe_str(msg.text)

        if html_content.strip():
            soup = BeautifulSoup(html_content, "html.parser")

            # Course name (look for first header or bold text)
            header = soup.find(["h1", "h2", "strong"])
            if header:
                course = header.get_text(strip=True)

            # Extract body text (short preview)
            text = soup.get_text(separator="\n", strip=True)
            if text.strip():
                body_text = "\n".join(text.splitlines()[1:8])

            # Find "View" link
            view_link = soup.find("a", string=lambda s: s and "view" in s.lower())
            if view_link and view_link.get("href"):
                link = view_link["href"]
            else:
                # fallback: grab first link
                first_link = soup.find("a")
                if first_link and first_link.get("href"):
                    link = first_link["href"]

        elif text_content.strip():
            body_text = text_content
        else:
            body_text = "(empty)"
    except Exception as e:
        print("⚠️ Extract error:", e)

    return course, body_text[:1000], link

def send_to_discord(sender, course, body, link=None):
    """Send embed with course, announcement, and link"""
    embed = {
        "title": f"From: {safe_str(sender)}",
        "description": f"**{course}**\n\n{body}",
        "color": 15105570
    }

    if link:
        embed["url"] = link  # make embed title clickable

    payload = {
        "content": "<@&1413784173570818080>",  # role mention
        "embeds": [embed]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code != 204:
        print("⚠️ Discord webhook error:", resp.status_code, resp.text)

def check_mail():
    """Check Gmail for new matching emails"""
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            sender = safe_str(msg.from_)
            if sender.lower() == ALLOWED_SENDER.lower():
                course, body, link = extract_course_body_link(msg)
                send_to_discord(sender, course, body, link)

if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", e)
        time.sleep(CHECK_INTERVAL)
