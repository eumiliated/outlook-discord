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
    """
    Parses the email content. 
    If it detects the 'Your updates' list format, it creates a bulleted list.
    Otherwise, it falls back to the standard announcement format.
    """
    html_content = msg.html or ""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # --- CHECK FOR "YOUR UPDATES" DIGEST FORMAT ---
    # We look for the specific header "Your updates" to trigger this specific formatting
    if soup.find(string=re.compile("Your updates", re.IGNORECASE)):
        header = "🔔 Blackboard Updates"
        description_lines = []
        
        # 1. Find all lines that say "added" or "updated" (these are the status indicators)
        #    The structure in the image is: <Link>Title</Link> ... "added" ... <br> Course Name
        items = soup.find_all(string=re.compile(r"\b(added|updated)\b", re.IGNORECASE))

        for item_status in items:
            # The "item_status" is just the text node "added". We need to look around it.
            
            # A. Find the Title & Link (It is usually the link immediately BEFORE the "added" text)
            # We search backwards from the "added" text to find the closest <a> tag
            link_tag = item_status.find_previous("a")
            
            if not link_tag:
                continue

            title = link_tag.get_text(strip=True)
            url = link_tag.get("href", "#") # use # if no link found
            
            # B. Find the Course Name (It is usually the text immediately AFTER the "added" text)
            # We look for the next distinct block of text.
            # Depending on email formatting, it might be in the next 'div', 'span', or just the next text node.
            course_name = "Unknown Course"
            
            # Try to find the container of the current link/status, then look at the next container
            current_container = link_tag.parent
            next_element = current_container.find_next_sibling()
            
            if next_element:
                course_name = next_element.get_text(strip=True)
            
            # C. Format the line for Discord
            # Result: • [Quiz 1](link) added
            #          _LOGIC AND CRITICAL THINKING_
            line = f"• [**{title}**]({url}) {item_status.strip()}\n   _{course_name}_"
            description_lines.append(line)

        # Combine all lines. If empty, fallback to basic text.
        if description_lines:
            full_body = "\n\n".join(description_lines)
            return header, full_body, "https://mapua.blackboard.com"

    # --- FALLBACK: STANDARD ANNOUNCEMENT FORMAT ---
    # (This runs if the email is NOT a "Your updates" digest)
    
    # Extract course code & name
    course_block = soup.find("span", string=lambda t: t and "_" in t)
    course_code = course_block.get_text(strip=True) if course_block else "Mapúa Blackboard"

    course_name_span = course_block.find_next("span") if course_block else None
    course_name = course_name_span.get_text(strip=True) if course_name_span else ""
    
    full_title = f"{course_code} - {course_name}" if course_name else course_code

    # Extract announcement body
    desc_div = soup.find(id=lambda x: x and "user-defined-description" in x)
    if desc_div:
        body = html_to_discord_text(desc_div)
    else:
        body = html_to_discord_text(soup)
        # Clean up the "Your updates" header if it accidentally fell through to here
        body = body.replace("Your updates", "").strip()

    body = body[:4000]

    # Extract "View" link
    view_link_tag = soup.find("a", string=lambda t: t and "View" in t)
    link = view_link_tag["href"] if view_link_tag else "https://mapua.blackboard.com"

    return full_title, body, link



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
