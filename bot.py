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
        print(f"❌ Missing env var: {name}. Set it in Heroku.")
        raise SystemExit(1)
    return val

EMAIL = require_env("EMAIL")
EMAIL_PASSWORD = require_env("PASSWORD")
DISCORD_WEBHOOK = require_env("DISCORD_WEBHOOK")
# ROLE_ID removed

# ------------------ CONFIG ------------------
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL = 60  # seconds
ALLOWED_SENDER = (
    "entalabador@mymail.mapua.edu.ph",
    "cardinal_edge@mapua.edu.ph"
)

# ------------------ HELPERS ------------------
def html_to_discord_text(html_fragment):
    """Convert HTML to clean text with preserved newlines for Discord."""
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
    Parses the email and builds the FULL Discord payload (content + list of embeds).
    """
    html_content = msg.html or ""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # ---------------------------------------------------------
    # SCENARIO A: "Your Updates" Digest (Multiple Embeds)
    # ---------------------------------------------------------
    if soup.find(string=re.compile("Your updates", re.IGNORECASE)):
        print("Creating Digest Payload...")
        
        # 1. Prepare the Main Message (Just the Header, no mention)
        now_str = datetime.now().strftime("%A, %B %d") # e.g. Wednesday, January 28
        message_content = f"# 📅 **Updates for {now_str}**"
        
        # 2. Define Categories to look for
        known_headers = ["Assessments", "Other new content", "Announcements", "Grades", "Calendar"]
        categorized_items = {} 

        # 3. Find all items and sort them
        items = soup.find_all(string=re.compile(r"\b(added|updated)\b", re.IGNORECASE))
        
        for item_status in items:
            # --- Extract Info ---
            link_tag = item_status.find_previous("a")
            if not link_tag: continue

            title = link_tag.get_text(strip=True).replace("\n", " ")
            url = link_tag.get("href", "#")
            
            # Find Course Name
            course_name = "Unknown Course"
            current_container = link_tag.parent
            next_text = current_container.find_next(string=lambda t: t and t.strip() and t != item_status)
            if next_text:
                course_name = next_text.strip()

            # --- Determine Category ---
            header_node = link_tag.find_previous(string=re.compile("|".join(known_headers), re.IGNORECASE))
            category = header_node.strip() if header_node else "General Updates"
            
            # --- Format Line ---
            line = f"• [**{title}**]({url}) {item_status.strip()}\n   _{course_name}_"
            
            if category not in categorized_items:
                categorized_items[category] = []
            categorized_items[category].append(line)

        # 4. Build Embeds List
        embeds_list = []
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

        embeds_list.sort(key=lambda x: x['title'])

        return {
            "content": message_content,
            "embeds": embeds_list
        }

    # ---------------------------------------------------------
    # SCENARIO B: Standard Announcement (Single Embed)
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
        "content": "",  # Empty content (no mention)
        "embeds": [{
            "title": full_title,
            "url": link,
            "description": body[:4000],
            "color": 5814783,
            "footer": {"text": f"Sent on {timestamp}"}
        }]
    }

def send_to_discord(payload):
    """Sends the pre-built payload to Discord."""
    r = requests.post(DISCORD_WEBHOOK, json=payload)
    if r.status_code != 204:
        print("⚠️ Discord webhook error:", r.status_code, r.text)
    else:
        print("✅ Sent to Discord successfully.")

def check_mail():
    """Check Gmail for new emails and forward to Discord."""
    with MailBox(IMAP_SERVER).login(EMAIL, EMAIL_PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            sender = msg.from_.strip().lower()
            if any(sender.endswith(allowed.lower()) for allowed in ALLOWED_SENDER):
                discord_payload = parse_email_content(msg)
                if discord_payload["embeds"]:
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