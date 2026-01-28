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
        print(f"❌ Missing env var: {name}.")
        raise SystemExit(1)
    return val

EMAIL = require_env("EMAIL")
EMAIL_PASSWORD = require_env("PASSWORD")
DISCORD_WEBHOOK = require_env("DISCORD_WEBHOOK")

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60
ALLOWED_SENDER = (
    "entalabador@mymail.mapua.edu.ph",
    "cardinal_edge@mapua.edu.ph"
)

# ------------------ HELPERS ------------------
def html_to_discord_text(html_fragment):
    """Convert HTML to clean text with preserved newlines."""
    soup = BeautifulSoup(str(html_fragment), "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_before("\n")
        p.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def parse_email_content(msg):
    """
    Parses the email.
    Uses 'Top-Down' scanning to strictly respect category headers.
    """
    html_content = msg.html or ""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # ---------------------------------------------------------
    # SCENARIO A: "Your Updates" Digest (Multiple Embeds)
    # ---------------------------------------------------------
    if soup.find(string=re.compile("Your updates", re.IGNORECASE)):
        print("Creating Digest Payload...")
        
        # 1. Header Message
        now_str = datetime.now().strftime("%A, %B %d")
        message_content = f"# **{now_str}**"
        
        # 2. Define Categories (Headers to look for)
        known_headers = [
            "Assessments", "Assignments", "Tests", "Quizzes", 
            "Other new content", "Content", "Course Content", 
            "Announcements", "Grades", "Calendar", "Blogs"
        ]
        
        categorized_items = {}
        current_category = "General Updates" # Default start category

        # 3. TOP-DOWN SCANNING (The Fix)
        # We iterate over all semantic elements to respect the order
        all_elements = soup.find_all(['a', 'div', 'span', 'h1', 'h2', 'h3', 'b', 'strong'])
        
        for el in all_elements:
            text = el.get_text(strip=True)
            if not text:
                continue

            # CHECK: Is this a Category Header?
            # We match exactly one of the known headers (ignoring case)
            if any(h.lower() == text.lower() for h in known_headers):
                current_category = text # Switch the 'active' category
                continue # Move to next element

            # CHECK: Is this an Update Item?
            # We look for "added" or "updated" in the text node immediately following this element
            # OR if this element itself is an <a> tag followed by "added"
            if el.name == 'a':
                # Check siblings/text for status
                status_text = el.find_next_sibling(string=True)
                if not status_text:
                    # Sometimes it's inside a parent's text
                    status_text = el.parent.get_text()
                
                if status_text and re.search(r"\b(added|updated)\b", status_text, re.IGNORECASE):
                    # LINEAR FORMAT FIX:
                    # Collapse newlines/spaces: "Quiz\n1" -> "Quiz 1"
                    title = " ".join(el.get_text().split())
                    url = el.get("href", "#")
                    status = "added" if "added" in status_text.lower() else "updated"
                    
                    # Create the bullet point
                    line = f"• [**{title}**]({url}) {status}"
                    
                    # Add to the CURRENT active category
                    if current_category not in categorized_items:
                        categorized_items[current_category] = []
                    
                    # Avoid duplicates
                    if line not in categorized_items[current_category]:
                        categorized_items[current_category].append(line)

        # 4. Build Embeds
        embeds_list = []
        if not categorized_items:
            # Fallback if top-down failed (empty list)
            return None 

        for category, lines in categorized_items.items():
            full_desc = "\n\n".join(lines)
            
            if len(full_desc) > 4000:
                full_desc = full_desc[:3900] + "\n...(truncated)"

            embed = {
                "title": f"📂 {category}",
                "description": full_desc,
                "color": 5814783,
                "url": "https://mapua.blackboard.com"
            }
            embeds_list.append(embed)

        return {
            "content": message_content,
            "embeds": embeds_list
        }

    # ---------------------------------------------------------
    # SCENARIO B: Standard Announcement (Fallback)
    # ---------------------------------------------------------
    course_block = soup.find("span", string=lambda t: t and "_" in t)
    course_code = course_block.get_text(strip=True) if course_block else "Mapúa Blackboard"
    course_name_span = course_block.find_next("span") if course_block else None
    course_name = course_name_span.get_text(strip=True) if course_name_span else ""
    full_title = f"{course_code} - {course_name}" if course_name else course_code

    desc_div = soup.find(id=lambda x: x and "user-defined-description" in x)
    if desc_div:
        body = html_to_discord_text(desc_div)
    else:
        body = html_to_discord_text(soup)
        body = body.replace("Your updates", "").strip()

    view_link_tag = soup.find("a", string=lambda t: t and "View" in t)
    link = view_link_tag["href"] if view_link_tag else "https://mapua.blackboard.com"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "content": "",
        "embeds": [{
            "title": full_title,
            "url": link,
            "description": body[:4000],
            "color": 5814783,
            "footer": {"text": f"Sent on {timestamp}"}
        }]
    }

def send_to_discord(payload):
    r = requests.post(DISCORD_WEBHOOK, json=payload)
    if r.status_code != 204:
        print("⚠️ Discord webhook error:", r.status_code, r.text)
    else:
        print("✅ Sent to Discord successfully.")

def check_mail():
    with MailBox(IMAP_SERVER).login(EMAIL, EMAIL_PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            sender = msg.from_.strip().lower()
            if any(sender.endswith(allowed.lower()) for allowed in ALLOWED_SENDER):
                discord_payload = parse_email_content(msg)
                # Only send if payload is valid and has embeds
                if discord_payload and discord_payload.get("embeds"):
                    send_to_discord(discord_payload)
                    mailbox.flag(msg.uid, MailMessageFlags.SEEN, True)

if __name__ == "__main__":
    print("Email → Discord notifier started.")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", repr(e))
        time.sleep(CHECK_INTERVAL)