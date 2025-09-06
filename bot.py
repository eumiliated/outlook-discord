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

def extract_course_body_link(msg):
    """Extract course name, body text, and a 'View' link from the HTML email"""
    course = "(Unknown Course)"
    body_text = "(No content)"
    link = None

    try:
        html_content = msg.html or ""
        if html_content.strip():
            soup = BeautifulSoup(html_content, "html.parser")

            # Course name (look for first header or bold text)
            header = soup.find(["h1", "h2", "strong"])
            if header:
                course = header.get_text(strip=True)

            # Extract body text (short preview)
            text = soup.get_text(separator="\n", strip=True)
            body_text = "\n".join(text.splitlines()[1:8])  # preview

            # Find "View" link
            view_link = soup.find("a", string=lambda s: s and "view" in s.lower())
            if view_link and view_link.get("href"):
                link = view_link["href"]
            else:
                # fallback: grab first link
                first_link = soup.find("a")
                if first_link and first_link.get("href"):
                    link = first_link["href"]

        else:
            body_text = msg.text or "(empty)"
    except Exception as e:
        print("⚠️ Extract error:", e)

    return course, body_text[:1000], link

def send_to_discord(sender, course, body, link=None):
    """Send embed with course, announcement, and link button"""
    embed = {
        "title": f"mapua",
        "description": f"**{course}**\n\n{body}",
        "color": 15105570
    }

    if link:
        embed["url"] = link  # clicking embed title opens link

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
            if msg.from_ == ALLOWED_SENDER:
                course, body, link = extract_course_body_link(msg)
                send_to_discord(msg.from_, course, body, link)

if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", e)
        time.sleep(CHECK_INTERVAL)
