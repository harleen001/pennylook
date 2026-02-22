import imaplib, email, pdfplumber, io, hashlib, sqlite3, pikepdf
from flask import Flask, render_template, redirect, url_for
import pandas as pd

app = Flask(__name__)

# --- CONFIGURATION ---
EMAIL_USER = "harleen.johal31@gmail.com"
EMAIL_PASS = "ndeg qykp nxrw jgtr"
PDF_PASSWORD = "HARL3112" # e.g., "HARL3101" 

def init_db():
    """Checks for the DB and creates the table if it's not there"""
    conn = sqlite3.connect('finances.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            type TEXT,
            unique_hash TEXT UNIQUE
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ Database check complete. Table is ready.")

def decrypt_pdf(pdf_bytes):
    """Unlocks the Axis Bank PDF using pikepdf"""
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes), password=PDF_PASSWORD) as pdf:
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except Exception as e:
        print(f"Decryption failed: {e}")
        return None

def fetch_axis_emails():
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    # Specifically search for Axis Bank statements
    status, data = mail.search(None, '(FROM "statements@axis.bank.in")')
    
    new_data = []
    for m_id in data[0].split():
        _, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        
        for part in msg.walk():
            if part.get_filename() and part.get_filename().endswith('.pdf'):
                raw_pdf = part.get_payload(decode=True)
                # UNLOCK THE PDF
                unlocked_pdf = decrypt_pdf(raw_pdf)
                
                if unlocked_pdf:
                    with pdfplumber.open(io.BytesIO(unlocked_pdf)) as pdf:
                        # Your screenshot shows headers: Txn Date, Transaction, Withdrawals, Deposits
                        table = pdf.pages[0].extract_table()
                        df = pd.DataFrame(table[1:], columns=table[0])
                        process_and_save(df)
    mail.logout()

def process_and_save(df):
    conn = sqlite3.connect('finances.db')
    cursor = conn.cursor()
    
    for _, row in df.iterrows():
        # Map Axis columns to our Database
        date = row.get('Txn Date')
        desc = row.get('Transaction')
        
        # Determine amount and type
        withdrawal = str(row.get('Withdrawals', '0')).replace(',', '').strip()
        deposit = str(row.get('Deposits', '0')).replace(',', '').strip()
        
        amt = float(withdrawal) if withdrawal and withdrawal != '' else float(deposit) if deposit else 0
        t_type = "Debit" if withdrawal else "Credit"

        if not date or not desc: continue

        t_hash = hashlib.md5(f"{date}{desc}{amt}".encode()).hexdigest()
        
        try:
            cursor.execute('INSERT INTO transactions (date, description, amount, type, unique_hash) VALUES (?,?,?,?,?)', 
                           (date, desc, amt, t_type, t_hash))
        except: continue
            
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect('finances.db')
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY id DESC", conn)
    conn.close()
    return render_template('index.html', transactions=df.to_dict(orient='records'))

@app.route('/sync')
def sync():
    fetch_axis_emails()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)