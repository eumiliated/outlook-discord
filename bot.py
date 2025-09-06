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

GMAIL_EMAIL = require_env("GMAIL_EMAIL")                 # e.g. generalderp07@gmail.com
GMAIL_APP_PASSWORD = require_env("GMAIL_APP_PASSWORD")   # 16-char Gmail App Password
DISCORD_WEBHOOK_URL = require_env("DISCORD_WEBHOOK_URL") # full webhook URL
ROLE_ID = os.getenv("DISCORD_ROLE_ID", "1413784173570818080")

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds
ALLOWED_SENDERS = {"entalabador@mymail.mapua.edu.ph", "cardinal_edge@mapua.edu.ph"}

# ------------------ HELPERS ------------------
def collapse_ws(text: str, limit: int = 1500) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]

def extract_announcement(html: str) -> dict:
    """
    Pulls out the 'box' contents from Blackboard-like emails:
      header (e.g., 'Assignment due soon' / 'New announcement')
      due line (starts with 'Due')
      main body text (paragraphs near the header or overall body)
      primary button link (View/Open)
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Remove non-content
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Try to get a prominent header
    header = None
    header_tag = None
    for tag in soup.find_all(["h1", "h2", "h3", "strong", "b"]):
        t = (tag.get_text(strip=True) or "").strip()
        if not t:
            continue
        if re.search(r"(announcement|assignment|due soon)", t, re.I):
            header = t
            header_tag = tag
            break
    if not header:
        # Fallback: first heading-ish text
        for tag in soup.find_all(["h1", "h2", "h3"]):
            t = (tag.get_text(strip=True) or "").strip()
            if t:
                header = t
                header_tag = tag
                break

    # Due line
    due = None
    due_node = soup.find(string=lambda s: isinstance(s, str) and "due" in s.lower())
    if due_node:
        due = due_node.strip()

    # Button link
    button_text, button_link = None, None
    btn = soup.find("a", string=lambda s: isinstance(s, str) and re.search(r"(view|open|announcement|assignment|submit)", s, re.I))
    if btn and btn.get("href"):
        button_link = btn["href"]
        button_text = (btn.get_text(strip=True) or "Open")
    else:
        first_a = soup.find("a", href=True)
        if first_a:
            button_link = first_a["href"]
            button_text = (first_a.get_text(strip=True) or "Open")

    # Body: prefer paragraphs near the header; else collect top-level paragraphs
    body_chunks = []
    if header_tag:
        # collect next few sibling paragraphs/divs
        sib = header_tag.parent
        # walk a bit up to get a reasonable container
        for _ in range(2):
            if sib and sib.parent and len(sib.get_text(" ", strip=True)) < 80:
                sib = sib.parent
        if sib:
            paras = sib.find_all(["p", "div", "span"], recursive=True)
            for p in paras:
                txt = p.get_text(" ", strip=True)
                if not txt:
                    continue
                # skip boilerplate
                if re.search(r"Blackboard|Manage your notification settings", txt, re.I):
                    continue
                if len(txt) < 3:
                    continue
                body_chunks.append(txt)
    if not body_chunks:
        # fallback: any reasonable paragraphs
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if txt and not re.search(r"Blackboard|Manage your notification settings", txt, re.I):
                body_chunks.append(txt)

    body_text = collapse_ws("\n".join(body_chunks), limit=1500)
    return {
        "header": header,
        "due": due,
        "body": body_text,
        "button_text": button_text,
        "button_link": button_link,
    }

def send_embed(sender: str, details: dict):
    """
    Title = 'From: <sender>'
    Body  = header (if any), due (if any), then main body text, plus link at bottom.
    Role mention goes in 'content' (outside the title).
    """
    lines = []
    if details.get("header"):
        lines.append(f"**{details['header']}**")
    if details.get("due"):
        lines.append(f"📅 {details['due']}")
    if details.get("body"):
        if lines:
            lines.append("")  # blank line before body
        lines.append(details["body"])
    if details.get("button_link"):
        btn_text = details.get("button_text") or "Open"
        lines.append(f"\n[🔗 {btn_text}]({details['button_link']})")

    description = collapse_ws("\n".join(lines), limit=1800)

    payload = {
        "content": f"<@&{ROLE_ID}>",   # ✅ role mention (not in title)
        "embeds": [
            {
                "title": f"From: {sender}",
                "description": description if description else "(No content)",
                "color": 0xF1C40F,
            }
        ]
    }

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
        if r.status_code not in (200, 204):
            print("⚠️ Discord webhook error:", r.status_code, r.text[:300])
        else:
            print("✅ Sent to Discord")
    except Exception as e:
        print("⚠️ Discord post failed:", repr(e))

def should_forward(sender_email: str, subject: str) -> bool:
    if not sender_email:
        return False
    if sender_email.lower() not in {s.lower() for s in ALLOWED_SENDERS}:
        return False
    if not subject:
        return False
    lower_subj = subject.lower()
    return any(w in lower_subj for w in SUBJECT_KEYWORDS)

def check_mail():
    with MailBox(IMAP_SERVER).login(GMAIL_EMAIL, GMAIL_APP_PASSWORD, "INBOX") as mailbox:
        for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
            sender = (msg.from_ or "").strip()
            subject = (msg.subject or "").strip()

            if should_forward(sender, subject):
                if msg.html and msg.html.strip():
                    details = extract_announcement(msg.html)
                else:
                    # plain text fallback
                    details = {"header": None, "due": None, "body": collapse_ws(msg.text or "", 1500), "button_text": None, "button_link": None}
                send_embed(sender, details)

# ------------------ MAIN LOOP ------------------
if __name__ == "__main__":
    print("✅ Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("❌ Error:", repr(e))
        time.sleep(CHECK_INTERVAL)
