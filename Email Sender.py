import os
import sys
import time
import random
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import pandas as pd
from dotenv import load_dotenv

# --- LOAD CONFIGURATION ---
load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

EXCEL_FILE = "emails for script.xlsx"
BROCHURE_FILE = "Uniformers Brochure.pdf"

# Warmup Batch & Pacing
DAILY_LIMIT = 25                # Conservative initial batch
MIN_DELAY_SECONDS = 75          # 1m 15s delay minimum
MAX_DELAY_SECONDS = 150         # 2m 30s delay maximum

# --- TEMPLATE POOLS ---
SUBJECT_TEMPLATES = [
    "Custom uniforms & corporate wear for {company}",
    "Uniform and workwear manufacturing for {company}",
    "Custom apparel solutions — {company}",
    "Quick question regarding uniform requirements at {company}",
    "Corporate uniforms & custom apparel for {company}",
    "Custom staff uniforms and merchandise for {company}",
    "High-quality corporate apparel supply for {company}",
    "Workwear and custom uniforms for {company}",
    "Reliable uniform manufacturing partner for {company}",
    "Custom apparel & uniform inquiry for {company}"
]

OPENING_HOOKS = [
    "I hope your week is off to a great start.",
    "Hope you are having a productive week.",
    "I hope this note finds you well.",
    "I'm reaching out directly regarding your team apparel.",
    "I came across {company} and wanted to introduce our manufacturing services.",
    "Hope everything is going well on your end.",
    "I'm contacting you directly from our UAE manufacturing facility.",
    "Hope you're having a smooth week ahead.",
    "Reaching out with a quick introduction regarding workwear.",
    "I hope your week is going well so far."
]

def get_first_name(full_name):
    """Extract clean first name and strip common titles (H.E., Dr., Sheikh, etc.)."""
    if pd.isna(full_name) or not str(full_name).strip():
        return "there"
    
    clean_str = str(full_name).strip()
    
    # Remove common corporate/governmental honorifics
    titles_pattern = r'^(H\.E\.|HE|Dr\.|Dr|Sheikh|Shk\.|Eng\.|Mr\.|Mrs\.|Ms\.)\s+'
    clean_str = re.sub(titles_pattern, '', clean_str, flags=re.IGNORECASE).strip()
    
    parts = clean_str.split()
    if not parts:
        return "there"
    
    return parts[0].title()

def create_email_content(contact_person, company_name):
    first_name = get_first_name(contact_person)
    
    if pd.isna(company_name) or not str(company_name).strip():
        company_clean = "your company"
    else:
        company_clean = str(company_name).strip()

    subject_raw = random.choice(SUBJECT_TEMPLATES)
    subject = subject_raw.format(company=company_clean)
    
    opening_raw = random.choice(OPENING_HOOKS)
    opening_line = opening_raw.format(company=company_clean)

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6;">
        <p>Hi {first_name},</p>
        
        <p>{opening_line}</p>
        
        <p>I am reaching out from <strong>Uniformers</strong> here in the UAE. We specialize in custom uniform manufacturing and corporate apparel—including high-quality polo shirts, safety overalls, schoolwear, custom promotional merchandise, towels, and healthcare uniforms.</p>
        
        <p>Whether you need to upgrade current staff uniforms, fulfill bulk corporate orders, or develop a custom branded apparel line, we manage the complete process:</p>
        <ul>
          <li><strong>Design & Fabric Consultation</strong> (concept to finished product)</li>
          <li><strong>High Quality & Competitive Bulk Pricing</strong></li>
          <li><strong>Fast Local UAE Delivery</strong> with reliable turnaround times</li>
        </ul>
        
        <p>I’ve attached our digital company brochure for your review.</p>
        
        <p>Would you be open to a brief chat or WhatsApp message to discuss how we can support your next apparel order?</p>
        
        <br>
        <p>Best regards,</p>
        <p>
          <strong>Abdullah Kamran</strong><br>
          <span style="color: #555555;">Uniformers — Custom Uniform Solutions</span><br>
          <strong>Email:</strong> {SENDER_EMAIL}<br>
          <strong>Website:</strong> <a href="https://www.uniformers.ae">www.uniformers.ae</a><br>
          <em>Umm Al Quwain / Dubai, UAE</em>
        </p>
        <hr style="border: none; border-top: 1px solid #cccccc; margin-top: 20px;">
        <p style="font-size: 11px; color: #777777;">
          If you are not the right contact for procurement or prefer not to receive updates, reply 'Unsubscribe' to be removed immediately.
        </p>
      </body>
    </html>
    """
    return subject, html_body

def run_outreach():
    if not os.path.exists(EXCEL_FILE):
        print(f"Error: {EXCEL_FILE} not found in workspace.")
        return

    df = pd.read_excel(EXCEL_FILE)

    if "Sent Status" not in df.columns:
        df["Sent Status"] = "Pending"

    pending_leads = df[(df["Sent Status"] == "Pending") & (df["EMAIL"].notna())]

    if pending_leads.empty:
        print("No pending leads found to send!")
        return

    batch = pending_leads.head(DAILY_LIMIT)
    print(f"Found {len(pending_leads)} total pending leads.")
    print(f"Starting warmup batch for today: {len(batch)} emails.\n")

    confirm = input("Type 'yes' to start sending: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    print(f"Connecting to SMTP server at {SMTP_HOST}:{SMTP_PORT}...")
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        print("Authenticated successfully!\n")
    except Exception as e:
        print(f"SMTP Connection Failed: {e}")
        return

    sent_today = 0

    try:
        for idx, row in batch.iterrows():
            recipient = str(row["EMAIL"]).strip()
            contact = row.get("CONTACT PERSON", "")
            company = row.get("NAME OF THE COMPANY", "")

            subject, html_body = create_email_content(contact, company)

            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            if os.path.exists(BROCHURE_FILE):
                with open(BROCHURE_FILE, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(BROCHURE_FILE))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(BROCHURE_FILE)}"'
                msg.attach(part)

            try:
                server.send_message(msg)
                sent_today += 1
                df.at[idx, "Sent Status"] = "Sent"
                print(f"[{sent_today}/{len(batch)}] Sent -> {recipient} | Subject: '{subject}'")
            except Exception as send_err:
                df.at[idx, "Sent Status"] = f"Failed ({type(send_err).__name__})"
                print(f"[{sent_today+1}/{len(batch)}] Failed sending to {recipient}: {send_err}")

            # Save progress live so interruptions don't lose data
            df.to_excel(EXCEL_FILE, index=False)

            if sent_today < len(batch):
                wait_time = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                print(f"   Pacing: waiting {int(wait_time)}s before next contact...")
                time.sleep(wait_time)

    finally:
        server.quit()
        print(f"\nBatch complete! Sent: {sent_today} emails.")
        print(f"Progress recorded in {EXCEL_FILE}")

if __name__ == "__main__":
    run_outreach()