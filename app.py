import imaplib, email, pdfplumber, io, hashlib, sqlite3, pikepdf, json, datetime
from flask import Flask, render_template, redirect, url_for, request
import pandas as pd
import plotly.express as px
import plotly.utils
import os
from dotenv import load_dotenv


app = Flask(__name__)


load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
PDF_PASSWORD = os.getenv("PDF_PASSWORD")
def decrypt_pdf(pdf_bytes):
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes), password=PDF_PASSWORD) as pdf:
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except: return None

def save_to_db(df):
    conn = sqlite3.connect('finances.db')
    # Normalize columns
    df.columns = [str(c).strip() for c in df.columns]
    possible_date_cols = ['Txn Date', 'Date', 'Transaction Date']
    date_col = next((c for c in possible_date_cols if c in df.columns), None)
    
    if not date_col:
        conn.close()
        return

    for _, row in df.iterrows():
        try:
            date = str(row[date_col]).strip()
            desc = str(row.get('Transaction', row.get('Narration', ''))).strip()
            w = str(row.get('Withdrawals', row.get('Debit', '0'))).replace(',', '').strip()
            d = str(row.get('Deposits', row.get('Credit', '0'))).replace(',', '').strip()
            
            if not date or 'balance' in desc.lower() or len(date) < 5:
                continue
            
            # Clean numerical values
            amt_w = float(w) if w and w.replace('.','',1).isdigit() else 0
            amt_d = float(d) if d and d.replace('.','',1).isdigit() else 0
            
            amt = amt_w if amt_w > 0 else amt_d
            t_type = "Debit" if amt_w > 0 else "Credit"
            
            if amt == 0: continue
            
            h = hashlib.md5(f"{date}{desc}{amt}".encode()).hexdigest()
            conn.execute('''INSERT OR IGNORE INTO transactions 
                            (date, description, amount, type, unique_hash) 
                            VALUES (?,?,?,?,?)''', (date, desc, amt, t_type, h))
        except: continue
    conn.commit()
    conn.close()

@app.route('/sync')
def sync():
    print("🔍 FORCING Deep Sync for all history (Multiple Senders)...")
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")
    
    # NEW SEARCH: Use OR logic to find both .bank.in AND .com addresses
    # This ensures we catch Dec 2025, Nov 2025, etc.
    search_criteria = 'OR (FROM "statements@axis.bank.in") (FROM "statements@axisbank.com")'
    status, data = mail.search(None, search_criteria)
    
    if status != 'OK':
        print("❌ Gmail search failed.")
        return redirect(url_for('index'))

    mail_ids = data[0].split()
    print(f"📧 Gmail found {len(mail_ids)} total emails across both Axis addresses.")

    for m_id in mail_ids:
        status, msg_data = mail.fetch(m_id, "(RFC822)")
        if status != 'OK': continue
        
        msg = email.message_from_bytes(msg_data[0][1])
        print(f"📬 Processing: {msg['Subject']}")

        for part in msg.walk():
            if part.get_filename() and part.get_filename().lower().endswith('.pdf'):
                filename = part.get_filename()
                print(f"📎 Found Attachment: {filename}")
                
                unlocked = decrypt_pdf(part.get_payload(decode=True))
                if unlocked:
                    with pdfplumber.open(io.BytesIO(unlocked)) as pdf:
                        for page in pdf.pages:
                            tables = page.extract_tables()
                            for table in tables:
                                if table and len(table) > 1:
                                    df_temp = pd.DataFrame(table[1:], columns=table[0])
                                    save_to_db(df_temp)
                else:
                    print(f"⚠️ Decryption failed for {filename}")
    
    mail.logout()
    print("✅ Deep Sync Attempt Finished.")
    return redirect(url_for('index'))


@app.route('/')
def index():
    selected_month = request.args.get('month', 'All')
    conn = sqlite3.connect('finances.db')
    df = pd.read_sql_query("SELECT * FROM transactions", conn)
    conn.close()

    if df.empty:
        return render_template('index.html', transactions=[], months=[], selected_month='All', graph_json=None, summary={})

    df['date_dt'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['date_dt']).sort_values('date_dt')
    df['month_year'] = df['date_dt'].dt.strftime('%b %Y')
    
    months = sorted(df['month_year'].unique().tolist(), 
                    key=lambda x: pd.to_datetime(x, format='%b %Y'), reverse=True)

    disp_df = df if selected_month == 'All' else df[df['month_year'] == selected_month]

    summary = {
        'income': disp_df[disp_df['type'] == 'Credit']['amount'].sum(),
        'expense': disp_df[disp_df['type'] == 'Debit']['amount'].sum()
    }

 # Update this section inside the index() function
    fig = px.line(disp_df, 
                  x='date_dt', 
                  y='amount', 
                  color='type', 
                  markers=True,
                  color_discrete_map={'Debit': '#ef4444', 'Credit': '#10b981'},
                  custom_data=['description', 'type', 'amount']) # Added amount to custom data

    # Refined hovertemplate to show Date, Amount (formatted), and the Narration
    fig.update_traces(
        hovertemplate="<br>".join([
            "<b>%{x|%d %b %Y}</b>",
            "Amount: ₹%{customdata[2]:,.2f}",
            "Type: %{customdata[1]}",
            "Details: %{customdata[0]}",
            "<extra></extra>"
        ])
    )

    fig.update_layout(
        hovermode="closest", # Changed to closest for better individual point inspection
        template="plotly_white", 
        margin=dict(l=0, r=0, t=40, b=0),
        yaxis_title="Transaction Amount (₹)",
        xaxis_title="Date"
    )
    
    return render_template('index.html', 
                           transactions=disp_df.sort_values('date_dt', ascending=False).to_dict('records'), 
                           months=months, selected_month=selected_month, 
                           graph_json=json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder), 
                           summary=summary)

if __name__ == '__main__':
    app.run(debug=True)