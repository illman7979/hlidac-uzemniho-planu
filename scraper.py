import io
import json
import os
import re
import smtplib
import unicodedata
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


BOARD_URL = (
    "https://www.mudk.cz/redakce/index.php"
    "?clanek=122590"
    "&xuser=124174245768101576"
    "&lanG=cs"
    "&slozka=122262"
    "&xsekce=122589"
)

STATE_FILE = Path("known_items.json")

REQUEST_TIMEOUT = 30
MAX_PDF_SIZE = 15 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_ATTACHMENTS_PER_ITEM = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; "
        "UzemniPlanMonitor/1.0; "
        "+https://github.com/)"
    )
}

# Zaměřeno pouze na územní plánování.
# Záměrně zde není samotné spojení "veřejná vyhláška"
# ani samotné "opatření obecné povahy", protože by hlídač
# zachytával velké množství dopravních oznámení.
KEYWORDS = [
    "územní plán",
    "územního plánu",
    "změna územního plánu",
    "změny územního plánu",
    "návrh územního plánu",
    "návrhu územního plánu",
    "územně plánovací dokumentace",
    "územně plánovací",
    "zpráva o uplatňování",
    "zadání změny",
    "pořizování změny",
    "veřejné projednání návrhu změny",
    "opakované veřejné projednání",
    "vyhodnocení vlivů na udržitelný rozvoj území",
    "Zveřejnění schváleného",
]

session = requests.Session()
session.headers.update(HEADERS)


def normalize_text(value):
    """Sjednotí mezery, velikost písmen a podobu Unicode znaků."""
    if not value:
        return ""

    value = unicodedata.normalize("NFKC", value)
    value = value.casefold()
    value = re.sub(r"\s+", " ", value)

    return value.strip()


NORMALIZED_KEYWORDS = [normalize_text(keyword) for keyword in KEYWORDS]


def find_keywords(text):
    """Vrátí klíčová slova nalezená v zadaném textu."""
    normalized = normalize_text(text)

    return sorted(
        {
            original
            for original, normalized_keyword in zip(
                KEYWORDS,
                NORMALIZED_KEYWORDS
            )
            if normalized_keyword in normalized
        }
    )


def load_state():
    if not STATE_FILE.exists():
        return set()

    try:
        content = STATE_FILE.read_text(encoding="utf-8")
        data = json.loads(content)

        return {str(item) for item in data}

    except (json.JSONDecodeError, OSError) as error:
        print(f"VAROVANI: Stav se nepodarilo nacist: {error}")
        return set()


def save_state(claim_ids):
    STATE_FILE.write_text(
        json.dumps(
            sorted(claim_ids, key=int),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_html_soup(url):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    # Web úřední desky používá UTF-8.
    response.encoding = "utf-8"

    return BeautifulSoup(response.text, "html.parser")


def extract_claim_id(url):
    match = re.search(r"[?&]detail_claim=(\d+)", url)

    if match:
        return match.group(1)

    return None


def get_board_items():
    """Najde položky zobrazené na úvodní stránce úřední desky."""
    soup = get_html_soup(BOARD_URL)
    items = {}

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")

        if "detail_claim=" not in href:
            continue

        full_url = urljoin(BOARD_URL, href)
        claim_id = extract_claim_id(full_url)

        if not claim_id:
            continue

        title = link.get_text(" ", strip=True)

        if not title:
            title = f"Oznámení ID {claim_id}"

        items[claim_id] = {
            "id": claim_id,
            "title": title,
            "url": full_url,
        }

    return items


def extract_pdf_text(pdf_url):
    """Stáhne PDF a pokusí se z něj získat strojově čitelný text."""
    try:
        response = session.get(
            pdf_url,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()

        content_length = int(
            response.headers.get("Content-Length", "0") or "0"
        )

        if content_length > MAX_PDF_SIZE:
            print(
                f"  PDF preskoceno, je prilis velke: {pdf_url}"
            )
            return ""

        pdf_data = response.content

        if len(pdf_data) > MAX_PDF_SIZE:
            print(
                f"  PDF preskoceno, je prilis velke: {pdf_url}"
            )
            return ""

        reader = PdfReader(io.BytesIO(pdf_data))
        extracted_pages = []

        for page_number, page in enumerate(reader.pages):
            if page_number >= MAX_PDF_PAGES:
                break

            try:
                extracted_pages.append(page.extract_text() or "")
            except Exception as error:
                print(
                    "  Text stranky PDF se nepodarilo precist: "
                    f"{error}"
                )

        return "\n".join(extracted_pages)

    except Exception as error:
        print(f"  PDF se nepodarilo zpracovat: {error}")
        return ""


def inspect_item(item):
    """
    Prohledá název, detail oznámení, názvy příloh
    a text ve strojově čitelných PDF.
    """
    print(f"Kontroluji nove oznameni {item['id']}: {item['title']}")

    soup = get_html_soup(item["url"])

    # Odstranění prvků, které netvoří vlastní obsah oznámení.
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    detail_text = soup.get_text("\n", strip=True)

    searchable_parts = [
        item["title"],
        detail_text,
    ]

    attachments = []
    seen_attachment_urls = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href:
            continue

        attachment_url = urljoin(item["url"], href)
        attachment_name = link.get_text(" ", strip=True)

        lower_url = attachment_url.lower()

        is_pdf = (
            lower_url.endswith(".pdf")
            or ".pdf?" in lower_url
            or "pdf" in lower_url
        )

        if not is_pdf:
            continue

        if attachment_url in seen_attachment_urls:
            continue

        seen_attachment_urls.add(attachment_url)

        attachments.append(
            {
                "name": attachment_name or "PDF příloha",
                "url": attachment_url,
            }
        )

        searchable_parts.append(attachment_name)

        if len(attachments) >= MAX_ATTACHMENTS_PER_ITEM:
            break

    # Nejdřív kontrola názvu, detailu a názvů příloh.
    combined_text = "\n".join(searchable_parts)
    matched_keywords = set(find_keywords(combined_text))

    # Pokud zatím nic nenajdeme, prohledáme také text PDF.
    # Díky tomu nestahujeme PDF zbytečně, když je shoda už v názvu.
    if not matched_keywords:
        for attachment in attachments:
            print(f"  Kontroluji PDF: {attachment['name']}")

            pdf_text = extract_pdf_text(attachment["url"])
            matched_keywords.update(find_keywords(pdf_text))

            if matched_keywords:
                break

    return {
        **item,
        "keywords": sorted(matched_keywords),
        "attachments": attachments,
    }


def send_email(matches):
    sections = []

    for item in matches:
        section = [
            item["title"],
            f"Odkaz: {item['url']}",
            f"ID oznámení: {item['id']}",
            "Nalezené výrazy: " + ", ".join(item["keywords"]),
        ]

        if item["attachments"]:
            section.append("Přílohy:")

            for attachment in item["attachments"]:
                section.append(
                    f"- {attachment['name']}: {attachment['url']}"
                )

        sections.append("\n".join(section))

    body = (
        "Na úřední desce města Dvůr Králové nad Labem "
        "bylo nalezeno nové oznámení související "
        "s územním plánováním.\n\n"
        + "\n\n"
        + ("\n\n" + ("-" * 60) + "\n\n").join(sections)
        + "\n\n"
        + "Hlavní úřední deska:\n"
        + BOARD_URL
    )

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = (
        f"Dvůr Králové: nové oznámení ÚP ({len(matches)})"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    message["From"] = os.environ["EMAIL_USER"]
    message["To"] = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            os.environ["EMAIL_USER"],
            os.environ["EMAIL_PASSWORD"],
        )
        

def send_status_email(board_items, known_ids, new_ids):
    body = (
        "Pravidelná kontrola proběhla úspěšně.\n\n"
        f"Datum a čas: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"Počet položek na desce: {len(board_items)}\n"
        f"Známých položek: {len(known_ids)}\n"
        f"Nových položek ke kontrole: {len(new_ids)}\n\n"
        "Výsledek: nebyly nalezeny žádné nové relevantní dokumenty.\n\n"
        "Hlídač územního plánu běží správně."
    )

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = (
        f"Dvůr Králové: kontrola OK "
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    message["From"] = os.environ["EMAIL_USER"]

    print("Posilam na:", os.environ["EMAIL_TO"])
    
    message["To"] = os.environ["EMAIL_TO"]

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            os.environ["EMAIL_USER"],
            os.environ["EMAIL_PASSWORD"],
        )
        smtp.send_message(message)
        print("SMTP: stavovy email skutecne odeslan")


def main():
    known_ids = load_state()
    board_items = get_board_items()

    current_ids = set(board_items)
    new_ids = current_ids - known_ids

    print(f"Polozek na desce: {len(board_items)}")
    print(f"Jiz znamych ID: {len(known_ids)}")
    print(f"Novych ID ke kontrole: {len(new_ids)}")

    relevant_items = []
    successfully_processed_ids = set()

    for claim_id in sorted(new_ids, key=int, reverse=True):
        item = board_items[claim_id]

        try:
            inspected_item = inspect_item(item)
            successfully_processed_ids.add(claim_id)

            if inspected_item["keywords"]:
                relevant_items.append(inspected_item)
                print(
                    "  RELEVANTNI: "
                    + ", ".join(inspected_item["keywords"])
                )
            else:
                print("  Bez shody.")

        except Exception as error:
            # ID se při chybě neuloží. Příští běh ho zkusí znovu.
            print(
                f"CHYBA pri kontrole ID {claim_id}: {error}"
            )

    if relevant_items:
        send_email(relevant_items)
        print(f"Odeslano relevantnich polozek: {len(relevant_items)}")
    else:
        send_status_email(board_items,known_ids,new_ids)
        print("Odeslan stavovy email.")

    # Uložíme pouze položky, jejichž zpracování proběhlo úspěšně.
    known_ids.update(successfully_processed_ids)
    save_state(known_ids)

    print(
        "Uspesne zpracovanych novych ID: "
        f"{len(successfully_processed_ids)}"
    )


if __name__ == "__main__":
    main()
