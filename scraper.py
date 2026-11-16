import os
import smtplib
from email.mime.text import MIMEText

subject = "Test hlídače územního plánu - nove 2"
body = """
Pokud čtete tento e-mail, GitHub Actions fungují správně.

Další krok bude napojení na úřední desku Dvora Králové.
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = subject
msg["From"] = os.environ["EMAIL_USER"]
msg["To"] = os.environ["michal.havle@centrum.cz"]

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
    smtp.login(
        os.environ["EMAIL_USER"],
        os.environ["EMAIL_PASSWORD"]
    )
    smtp.send_message(msg)

print("Testovací email odeslán")
