import imaplib, email, pdfplumber, io, hashlib, sqlite3, pikepdf, json, datetime
from flask import Flask, render_template, redirect, url_for, request
import pandas as pd
import plotly.express as px
import plotly.utils

app = Flask(__name__)

# --- CONFIG ---
EMAIL_USER = "harleen.johal31@gmail.com"
EMAIL_PASS = "ndeg qykp nxrw jgtr"
PDF_PASSWORD = "HARL3112"

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
    print("🔍 Starting Deep Sync for 2025-2026...")
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")
    
    # Broaden the search: Look for ALL emails from Axis since Jan 1st 2025
    search_criteria = '(FROM "statements@axis.bank.in" SINCE "01-Jan-2025")'
    _, data = mail.search(None, search_criteria)
    mail_ids = data[0].split()
    
    print(f"📧 Found {len(mail_ids)} potential statements. Processing...")

    for m_id in mail_ids:
        _, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        for part in msg.walk():
            if part.get_filename() and part.get_filename().lower().endswith('.pdf'):
                print(f"📄 Downloading: {part.get_filename()}")
                unlocked = decrypt_pdf(part.get_payload(decode=True))
                if unlocked:
                    with pdfplumber.open(io.BytesIO(unlocked)) as pdf:
                        for page in pdf.pages:
                            # Axis 2025 PDFs sometimes use different table structures
                            # We extract ALL tables found on the page
                            tables = page.extract_tables()
                            for table in tables:
                                if table and len(table) > 1:
                                    df_temp = pd.DataFrame(table[1:], columns=table[0])
                                    save_to_db(df_temp)
    
    mail.logout()
    print("✅ Sync Complete. Check the sidebar for new months.")
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

    fig = px.line(disp_df, x='date_dt', y='amount', color='type', markers=True,
                  color_discrete_map={'Debit': '#ef4444', 'Credit': '#10b981'},
                  custom_data=['description', 'type'])

    fig.update_traces(hovertemplate="<b>%{x|%d %b %Y}</b><br>₹%{y:,.2f}<br>%{customdata[0]}<extra></extra>")
    fig.update_layout(hovermode="x unified", template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    
    return render_template('index.html', 
                           transactions=disp_df.sort_values('date_dt', ascending=False).to_dict('records'), 
                           months=months, selected_month=selected_month, 
                           graph_json=json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder), 
                           summary=summary)

if __name__ == '__main__':
    app.run(debug=True)