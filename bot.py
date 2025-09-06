import os
import re
import time
import requests
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# ------------------ ENV ------------------
def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"❌ Missing env var: {name}. Set it in Heroku: heroku config:set {name}=... -a <your-app>")
        raise SystemExit(1)
    return val

EMAIL = require_env("EMAIL")                       # e.g. your Gmail address
EMAIL_PASSWORD = require_env("EMAIL_PASSWORD")     # Gmail App Password (16 chars)
DISCORD_WEBHOOK = require_env("DISCORD_WEBHOOK")   # Discord webhook URL
ROLE_ID = os.getenv("DISCORD_ROLE_ID", "1413784173570818080")

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds
ALLOWED_SENDER = "entalabador@mymail.mapua.edu.ph"  # only forward from this address

# ------------------ HELPERS ------------------
def s(val) -> str:
    """Safe string (never None)."""
    try:
        return str(val) if val is not None else ""
    except Exception:
        return ""

def collapse_ws(text: str, limit: int = 1800) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]

def guess_course(soup: BeautifulSoup, header_text: str | None) -> str | None:
    """
    Heuristics to find a course name like:
    'GED101_B30_1T2526 UNDERSTANDING THE SELF'
    Prefer all-uppercase heading/strong lines that aren't the header.
    """
    header_text_norm = (header_text or "").strip().upper()
    candidates = []

    # Gather text from headings/strong/b near the top
    for tag in soup.find_all(["h1", "h2", "h3", "strong", "b"]):
        t = (tag.get_text(" ", strip=True) or "").strip()
        if not t:
            continue
        t_norm = t.upper()
        if t_norm == header_text_norm:
            continue
        if len(t) >= 6 and (t_norm == t or re.search(r"[A-Z]{3,}\d|_", t_norm)):
            candidates.append(t)

    # Also scan the first ~20 non-empty lines for an uppercase-ish course line
    lines = []
    full_text = soup.get_text("\n", strip=True)
    for line in full_text.splitlines()[:20]:
        line = line.strip()
        if not line or line.upper() == header_text_norm:
            continue
        if len(line) >= 6 and (line.isupper() or re.search(r"[A-Z]{3,}\d|_", line)):
            candidates.append(line)

    # Filter out obvious boilerplate
    filtered = [
        c for c in candidates
        if not re.search(r"BLACKBOARD|NOTIFICATION|MANAGE YOUR NOTIFICATION|DO NOT REPLY", c, re.I)
    ]

    # Return the longest plausible candidate
    return max(filtered, key=len) if filtered else None

def extract_details(html_content: str, text_content: str):
    """
    Extract:
      - header (announcement/due soon) -> becomes embed title
      - link (View/Open) -> makes title clickable
      - course -> first line in description
      - body -> rest of the announcement text
    """
    html = s(html_content)
    text = s(text_content)

    header = None
    link = None
    course = None
    body = None

    if html.strip():
        soup = BeautifulSoup(html, "html.parser")

        # Remove scripts/styles
        for t in soup(["script", "style"]):
            t.decompose()

        # 1) Header: prefer headings with keywords; else first heading; else bold
        header_tag = None
        for tag in soup.find_all(["h1", "h2", "h3"]):
            t = (tag.get_text(" ", strip=True) or "").strip()
            if not t:
                continue
            if re.search(r"(announcement|due|assignment)", t, re.I):
                header = t
                header_tag = tag
                break
        if not header:
            # fallback: first heading
            first_h = soup.find(["h1", "h2", "h3"])
            if first_h:
                header = first_h.get_text(" ", strip=True)
                header_tag = first_h
        if not header:
            # fallback: strong/b with keywords
            strong = soup.find(["strong", "b"], string=lambda s_: isinstance(s_, str) and re.search(r"(announcement|due|assignment)", s_, re.I))
            if strong:
                header = strong.get_text(" ", strip=True)
                header_tag = strong

        # 2) Link: explicit View/Open; else first href
        btn = soup.find("a", string=lambda s_: isinstance(s_, str) and re.search(r"(view|open|announcement|assignment|submit)", s_, re.I))
        if btn and btn.get("href"):
            link = btn["href"]
        else:
            first_a = soup.find("a", href=True)
            if first_a:
                link = first_a["href"]

        # 3) Course: guess using heuristics (skip header text)
        course = guess_course(soup, header)

        # 4) Body: collect paragraphs near header; else general paragraphs
        chunks = []
        if header_tag:
            container = header_tag.parent or soup
            # climb up a little if header wrapper is too tiny
            for _ in range(2):
                if container and container.parent and len(container.get_text(" ", strip=True)) < 80:
                    container = container.parent
            for p in container.find_all(["p", "div", "span"], recursive=True):
                t = (p.get_text(" ", strip=True) or "").strip()
                if not t:
                    continue
                if re.search(r"Blackboard|Manage your notification settings|Do not reply", t, re.I):
                    continue
                chunks.append(t)
        if not chunks:
            for p in soup.find_all("p"):
                t = (p.get_text(" ", strip=True) or "").strip()
                if t and not re.search(r"Blackboard|Manage your notification settings|Do not reply", t, re.I):
                    chunks.append(t)

        body = collapse_ws("\n".join(chunks), limit=1800)

    else:
        # Plain-text fallback
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        header = lines[0] if lines else "(No title)"
        body = collapse_ws("\n".join(lines[1:]), limit=1800)
        link = None
        course = None

    # Final fallbacks
    if not header:
        header = "(Announcement)"
    if not body:
        body = "(No content)"

    # Trim to Discord limits
    header = header[:256]  # Discord embed title limit
    return header, link, course, body

# ------------------ DISCORD ------------------
def send_embed(header: str, link: str | None, course: str | None, body: str):
    """
    - Embed title = header (clickable if link exists)
    - First line of description = course (as a subheader)
    - Rest of description = body text
    - Role mention in content
    """
    description_lines = []
    if course:
        description_lines.append(f"**{course}**")
    if body:
        if description_lines:
            description_lines.append("")  # blank line before body
        description_lines.append(body)

    embed = {
        "title": header,
        "description": collapse_ws("\n".join(description_lines), limit=4096),
        "color": 0xF1C40F,
    }
    if link:
        embed["url"] = link  # makes title clickable

    payload = {
        "content": f"<@&{ROLE_ID}>",  # role mention outside the embed
        "embeds": [embed],
    }

    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
        if r.status_code not in (200, 204):
            print("⚠️ Discord webhook error:", r.status_code, r.text[:300])
        else:
            print("✅ Sent to Discord:", header)
    except Exception as e:
        print("⚠️ Discord post failed:", repr(e))

def check_mail():
    with MailBox(IMAP_SERVER).login(EMAIL, EMAIL_PASSWORD, "INBOX") as mailbox:
        for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
            try:
                sender = s(msg.from_).lower()
                if sender != ALLOWED_SENDER.lower():
                    continue

                header, link, course, body = extract_details(s(msg.html), s(msg.text))
                send_embed(header, link, course, body)

            except Exception as e:
                print("Message handling error:", repr(e))

if __name__ == "__main__":
    print("Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", repr(e))
        time.sleep(CHECK_INTERVAL)