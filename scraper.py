import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.mudk.cz/cs/radnice/uzemni-planovani/"

KEYWORDS = [
    "územní plán",
    "změna",
    "veřejné projednání",
    "opatření obecné povahy",
]

STATE_FILE = "known_items.json"


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


response = requests.get(URL, timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

text = soup.get_text("\n")

found = set()

for line in text.splitlines():
    line = line.strip()

    if not line:
        continue

    if any(k.lower() in line.lower() for k in KEYWORDS):
        found.add(line)


known = load_state()

new_items = found - known

if new_items:
    body = (
        "Byly nalezeny nové položky týkající se územního plánování:\n\n"
        + "\n".join(sorted(new_items))
        + "\n\nZdroj:\n"
        + URL
    )

    send_email(
        "Dvůr Králové - nové územní plánování",
        body
    )

known.update(found)

save_state(known)

print(f"Nalezeno: {len(found)}")
print(f"Nových: {len(new_items)}")
