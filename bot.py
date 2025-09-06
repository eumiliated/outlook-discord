import os
import re
import time
import requests
from datetime import datetime
from imap_tools import MailBox, AND, MailMessageFlags
from bs4 import BeautifulSoup

# ------------------ ENV ------------------
def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"❌ Missing env var: {name}. Set it in Heroku: heroku config:set {name}=... -a <your-app>")
        raise SystemExit(1)
    return val

EMAIL = require_env("EMAIL")                       # e.g. your Gmail address
EMAIL_PASSWORD = require_env("PASSWORD")           # Gmail App Password (16 chars)
DISCORD_WEBHOOK = require_env("DISCORD_WEBHOOK")   # Discord webhook URL
ROLE_ID = os.getenv("DISCORD_ROLE_ID", "1413784173570818080")

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds
ALLOWED_SENDER = (
    "entalabador@mymail.mapua.edu.ph",
    "cardinal_edge@mapua.edu.ph"
) # only forward from this address


# ------------------ HELPERS ------------------
def html_to_discord_text(html_fragment):
    """Convert HTML to clean text with preserved newlines for Discord."""
    soup = BeautifulSoup(str(html_fragment), "html.parser")

    # Turn <br> and <p> into newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_before("\n")
        p.insert_after("\n")

    text = soup.get_text()

    # Clean up spacing
    text = re.sub(r"\n\s*\n", "\n\n", text)  # collapse multiple blank lines
    text = re.sub(r"[ \t]+", " ", text)      # collapse spaces
    return text.strip()


def parse_email_content(msg):
    """Extract course info, announcement body, and link from email HTML."""
    html_content = msg.html or ""
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract course code & name
    course_block = soup.find("span", string=lambda t: t and "_" in t)
    course_code = course_block.get_text(strip=True) if course_block else "Unknown Course"

    course_name_span = course_block.find_next("span") if course_block else None
    course_name = course_name_span.get_text(strip=True) if course_name_span else ""

    # Extract announcement body (formatted text)
    desc_div = soup.find(id=lambda x: x and "user-defined-description" in x)
    if desc_div:
        body = html_to_discord_text(desc_div)
    else:
        body = html_to_discord_text(soup)

    body = body[:4000]  # Discord embed description limit

    # Extract "View" link
    view_link_tag = soup.find("a", string=lambda t: t and "View" in t)
    link = view_link_tag["href"] if view_link_tag else None

    return f"{course_code} - {course_name}", body, link


def send_to_discord(course_title, body, link):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "content": f"<@&{ROLE_ID}>",  # mention role dynamically
        "embeds": [
            {
                "title": course_title,
                "url": link,
                "description": body,
                "color": 5814783,
                "footer": {
                    "text": f"Sent on {timestamp}"
                }
            }
        ]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload)
    if r.status_code != 204:
        print("⚠️ Discord webhook error:", r.status_code, r.text)
        print("Payload sent:", payload)
    else:
        print(f"✅ Sent to Discord: {course_title}")


def check_mail():
    """Check Gmail for new emails and forward as embeds to Discord."""
    with MailBox(IMAP_SERVER).login(EMAIL, EMAIL_PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            sender = msg.from_.strip().lower()
            if any(sender.endswith(allowed.lower()) for allowed in ALLOWED_SENDER):
                course_title, body, link = parse_email_content(msg)
                send_to_discord(course_title, body, link)
                # only mark as seen after sending successfully
                mailbox.flag(msg.uid, MailMessageFlags.SEEN, True)


if __name__ == "__main__":
    print("Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", repr(e))
        time.sleep(CHECK_INTERVAL)
