import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE_FILE = "state.json"

URL = "https://www.mudk.cz/cs/radnice/uzemni-planovani/"

KEYWORDS = [
    "územní plán",
    "změna územního plánu",
    "veřejné projednání",
    "opatření obecné povahy",
]

def load_state():
    if Path(STATE_FILE).exists():
        return set(json.loads(Path(STATE_FILE).read_text(encoding="utf-8")))
    return set()

def save_state(items):
    Path(STATE_FILE).write_text(
        json.dumps(list(items), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

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

response = requests.get(URL, timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

known = load_state()
current = set()

text = soup.get_text("\n")

for line in text.splitlines():
    line = line.strip()

    if not line:
        continue

    if any(keyword.lower() in line.lower() for keyword in KEYWORDS):
        current.add(line)

new_items = current - known

if new_items:
    body = (
        "Byla nalezena nová zmínka o územním plánování.\n\n"
        + "\n\n".join(sorted(new_items))
        + f"\n\nZdroj:\n{URL}"
    )

    send_email(
        "Dvůr Králové - změna územního plánu",
        body
    )

save_state(current)

print(f"Nalezeno {len(current)} položek")
print(f"Nových {len(new_items)} položek")
