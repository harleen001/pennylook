import imaplib
import email
import pdfplumber
import pandas as pd
import io
import sqlite3
import hashlib

# ==========================================
# 1. CONFIGURATION
# ==========================================
EMAIL_USER = "your_email@gmail.com"
EMAIL_PASS = "xxxx xxxx xxxx xxxx"  # Your 16-character App Password
IMAP_URL = 'imap.gmail.com'
DB_NAME = 'finances.db'

# ==========================================
# 2. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            category TEXT DEFAULT 'Uncategorized',
            unique_hash TEXT UNIQUE
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ Database Initialized.")

# ==========================================
# 3. EXTRACTION & STORAGE LOGIC
# ==========================================
def save_to_db(df):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added_count = 0

    for _, row in df.iterrows():
        # 1. Clean data: Remove commas from amounts and handle whitespace
        try:
            clean_date = str(row.get('Date', '')).strip()
            # In your screenshot, 'Narration' is the description
            clean_desc = str(row.get('Narration', row.get('Description', ''))).strip()
            # Convert amount to float (handles "1,200.00" -> 1200.0)
            raw_amt = str(row.get('Amount', '0')).replace(',', '')
            clean_amt = float(raw_amt)

            # 2. Create a Unique Hash (Prevents duplicates)
            raw_string = f"{clean_date}{clean_desc}{clean_amt}"
            t_hash = hashlib.md5(raw_string.encode()).hexdigest()

            cursor.execute('''
                INSERT INTO transactions (date, description, amount, unique_hash)
                VALUES (?, ?, ?, ?)
            ''', (clean_date, clean_desc, clean_amt, t_hash))
            added_count += 1
        except (sqlite3.IntegrityError, ValueError):
            # Skips if hash exists (duplicate) or if data is empty/header row
            continue

    conn.commit()
    conn.close()
    print(f"🚀 Success: {added_count} new transactions saved to Ledgr.")

def run_ledgr_bot():
    print("🔍 Searching for new statements in Gmail...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_URL)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        # Search for unread emails with "Statement" in subject
        status, data = mail.search(None, '(UNSEEN SUBJECT "Statement")')
        mail_ids = data[0].split()

        if not mail_ids:
            print("📭 No new unread statements found.")
            return

        for m_id in mail_ids:
            _, msg_data = mail.fetch(m_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    for part in msg.walk():
                        if part.get_filename() and part.get_filename().lower().endswith('.pdf'):
                            print(f"📥 Processing attachment: {part.get_filename()}")
                            pdf_bytes = part.get_payload(decode=True)
                            
                            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                                # Extract all pages
                                all_data = []
                                for page in pdf.pages:
                                    table = page.extract_table()
                                    if table:
                                        all_data.extend(table)
                                
                                if all_data:
                                    # Create DataFrame using first row as headers
                                    df = pd.DataFrame(all_data[1:], columns=all_data[0])
                                    save_to_db(df)

        mail.logout()
    except Exception as e:
        print(f"🚨 Error: {e}")

# ==========================================
# 4. RUN THE PROGRAM
# ==========================================
if __name__ == "__main__":
    init_db()        # Step 1: Create DB
    run_ledgr_bot()  # Step 2: Extract & Save