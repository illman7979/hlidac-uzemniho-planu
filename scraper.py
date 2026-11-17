import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.mudk.cz"
UD_URL = "https://www.mudk.cz/redakce/index.php?clanek=122590&xuser=124174245768101576&lanG=cs&slozka=122262&xsekce=122589"

STATE_FILE = "known_items.json"

KEYWORDS = [
    "územní plán",
    "změna územního plánu",
    "veřejné projednání",
    "veřejná vyhláška",
    "opatření obecné povahy",
    "zpráva o uplatňování",
    "územně plánovací",
    "Zveřejnění schváleného",
]


def load_state():
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_state(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(data)), f, ensure_ascii=False, indent=2)


def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = os.environ["EMAIL_USER"]
    msg["To"] = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            os.environ["EMAIL_USER"],
            os.environ["EMAIL_PASSWORD"]
        )
        smtp.send_message(msg)


known = load_state()

response = requests.get(UD_URL, timeout=30)
response.raise_for_status()

# Web vrací text v UTF-8, ale requests může zvolit chybné kódování.
response.encoding = "utf-8"

soup = BeautifulSoup(response.text, "html.parser")

found_ids = set()
matches = []

for link in soup.find_all("a", href=True):

    href = link["href"]

    if "detail_claim=" not in href:
        continue

    m = re.search(r"detail_claim=(\d+)", href)
    if not m:
        continue

    claim_id = m.group(1)

    title = link.get_text(" ", strip=True)

    full_url = href
    if href.startswith("/"):
        full_url = BASE_URL + href
    elif not href.startswith("http"):
        full_url = BASE_URL + "/" + href.lstrip("/")

    found_ids.add(claim_id)

    text_for_check = title.lower()

    if any(k.lower() in text_for_check for k in KEYWORDS):
        if claim_id not in known:
            matches.append(
                {
                    "id": claim_id,
                    "title": title,
                    "url": full_url,
                }
            )

if matches:

    body_lines = []

    for item in matches:
        body_lines.append(
            f"{item['title']}\n{item['url']}\nID: {item['id']}"
        )

    body = (
        "Byla nalezena nová položka na úřední desce.\n\n"
        + "\n\n".join(body_lines)
    )

    send_email(
        "Dvůr Králové - nové oznámení ÚP",
        body
    )

for link in soup.find_all("a", href=True):
    if "detail_claim=" in link["href"]:
        print("POLOZKA:", link.get_text(" ", strip=True))

known.update(found_ids)
save_state(known)

print(f"Nalezeno oznámení: {len(found_ids)}")
print(f"Nové relevantní položky: {len(matches)}")
