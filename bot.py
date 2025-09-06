import os
import re
import time
import requests
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# ------------------ ENV VARS ------------------
def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"❌ Missing env var: {name}. Set it in Heroku: heroku config:set {name}=... -a <your-app>")
        raise SystemExit(1)
    return val

EMAIL = require_env("GMAIL_EMAIL")                 # e.g. generalderp07@gmail.com
PASSWORD = require_env("GMAIL_APP_PASSWORD")       # 16-char Gmail App Password (no spaces)
DISCORD_WEBHOOK_URL = require_env("DISCORD_WEBHOOK_URL")  # full webhook URL
ROLE_ID = os.getenv("DISCORD_ROLE_ID", "1413784173570818080")  # your role id

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds
# allow either the Outlook forwarder or the original Blackboard sender if it ever passes through
ALLOWED_SENDERS = {"entalabador@mymail.mapua.edu.ph", "cardinal_edge@mapua.edu.ph"}
SUBJECT_KEYWORDS = ["due soon", "announcement"]

# ------------------ HTML PARSING ------------------
def collapse_ws(text: str, limit: int = 1000) -> str:
    """Collapse whitespace/newlines and trim length."""
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]

def parse_email_html_for_details(html: str, subject_fallback: str = "") -> dict:
    """
    Try to extract a Blackboard-style 'box':
      - a main header (e.g., 'Assignment due soon' / 'New announcement')
      - a course or subheader (e.g., 'UNDERSTANDING THE SELF')
      - a due line ('Due Thursday, ...')
      - a primary 'View' / 'Open' link
      - a safe preview of the HTML as plaintext
    Works defensively for other HTML formats as well.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Headings: prefer h1/h2/h3
    header = None
    course = None
    subheader = None
    for tag in soup.find_all(["h1", "h2", "h3"]):
        t = (tag.get_text(strip=True) or "").strip()
        if not t:
            continue
        if not header:
            header = t
            continue
        # heuristics: often the all-caps item is the course
        if not course and t.isupper() and 4 <= len(t) <= 80:
            course = t
        elif not subheader:
            subheader = t

    # If no header from headings, try strong/b tags as fallback
    if not header:
        strong = soup.find(["strong", "b"])
        if strong:
            header = strong.get_text(strip=True)

    # Due line (first text node containing 'Due' / 'deadline')
    due = None
    due_node = soup.find(string=lambda s: isinstance(s, str) and bool(re.search(r"\b(due|deadline)\b", s, re.I)))
    if due_node:
        due = due_node.strip()

    # Primary "button" link
    button = soup.find("a", string=lambda s: isinstance(s, str) and bool(re.search(r"\b(view|open|announcement|assignment|submit)\b", s, re.I)))
    button_text, button_link = None, None
    if button and button.get("href"):
        button_link = button["href"]
        button_text = (button.get_text(strip=True) or "Open")
    else:
        # fallback: first link in the email
        first_a = soup.find("a", href=True)
        if first_a:
            button_link = first_a["href"]
            button_text = (first_a.get_text(strip=True) or "Open")

    # Plaintext preview from HTML
    preview = collapse_ws(soup.get_text(separator="\n", strip=True))

    return {
        "header": header or subject_fallback or "(No title)",
        "course": course,
        "subheader": subheader,
        "due": due,
        "button_text": button_text,
        "button_link": button_link,
        "preview": preview,
    }

# ------------------ DISCORD ------------------
def send_embed_to_discord(sender: str, subject: str, details: dict):
    """
    Build a Discord embed that resembles the box:
      - Mention role (NOT in the title)
      - Title: "New Email from <sender>"
      - Description: Subject, header, subheader/course, due, and a link button
    """
    # Build description
    lines = []
    if subject:
        lines.append(f"**Subject:** {subject}")
    if details.get("header"):
        lines.append(f"\n**{details['header']}**")
    if details.get("subheader"):
        lines.append(details["subheader"])
    if details.get("course") and details.get("course") != details.get("subheader"):
        lines.append(details["course"])
    if details.get("due"):
        lines.append(f"📅 **{details['due']}**")

    # clickable link
    if details.get("button_link"):
        btn_text = details.get("button_text") or "Open"
        lines.append(f"\n[🔗 {btn_text}]({details['button_link']})")

    # If we still have very little, include a short preview
    if len("\n".join(lines)) < 60 and details.get("preview"):
        lines.append(f"\n{details['preview']}")

    description = collapse_ws("\n".join(lines), limit=1500)

    payload = {
        "content": f"<@&{ROLE_ID}>",   # ✅ role mention OUTSIDE the title
        "embeds": [
            {
                "title": f"📩 New Email from {sender}",
                "description": description,
                "color": 0xF1C40F,   # nice yellow accent
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

# ------------------ MAIL CHECK ------------------
def should_forward(sender_email: str, subject: str) -> bool:
    if not sender_email:
        return False
    sender_email = sender_email.lower()
    if sender_email not in {s.lower() for s in ALLOWED_SENDERS}:
        return False
    if not subject:
        return False
    lower_subj = subject.lower()
    return any(w in lower_subj for w in SUBJECT_KEYWORDS)

def check_mail():
    """Check Gmail for new matching emails and send to Discord."""
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, "INBOX") as mailbox:
        # mark_seen=True so we don't re-send the same message every loop
        for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
            sender = (msg.from_ or "").strip()
            subject = (msg.subject or "").strip()

            # Uncomment for debugging to see every email that arrives
            # print("📬 Incoming:", sender, "|", subject)

            if should_forward(sender, subject):
                details = (
                    parse_email_html_for_details(msg.html or "", subject_fallback=subject)
                    if (msg.html and msg.html.strip())
                    else {"header": subject, "preview": (msg.text or "").strip()}
                )
                send_embed_to_discord(sender, subject, details)
            else:
                # Uncomment to see skipped items
                # print("⏭️ Skipped:", sender, "|", subject)
                pass

# ------------------ MAIN LOOP ------------------
if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", repr(e))
        time.sleep(CHECK_INTERVAL)
