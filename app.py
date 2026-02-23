import imaplib, email, pdfplumber, io, hashlib, sqlite3, pikepdf, json
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

@app.route('/sync')
def sync():
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")
    # Fetch all from Axis
    _, data = mail.search(None, '(FROM "statements@axis.bank.in")')
    mail_ids = data[0].split()
    
    # 🚨 LIMIT TO LAST 10 STATEMENTS
    for m_id in mail_ids[-10:]:
        _, msg_data = mail.fetch(m_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        for part in msg.walk():
            if part.get_filename() and part.get_filename().lower().endswith('.pdf'):
                unlocked = decrypt_pdf(part.get_payload(decode=True))
                if unlocked:
                    with pdfplumber.open(io.BytesIO(unlocked)) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                df = pd.DataFrame(table[1:], columns=table[0])
                                if 'Withdrawals' in df.columns:
                                    save_to_db(df)
    mail.logout()
    return redirect(url_for('index'))

def save_to_db(df):
    conn = sqlite3.connect('finances.db')
    for _, row in df.iterrows():
        try:
            date, desc = str(row.get('Txn Date','')), str(row.get('Transaction',''))
            w, d = str(row.get('Withdrawals','')).replace(',',''), str(row.get('Deposits','')).replace(',','')
            if not date or 'Balance' in desc: continue
            amt = float(w) if w and w.strip() and w != 'None' else float(d) if d and d.strip() and d != 'None' else 0
            t_type = "Debit" if w and w.strip() and w != 'None' else "Credit"
            if amt == 0: continue
            h = hashlib.md5(f"{date}{desc}{amt}".encode()).hexdigest()
            conn.execute('INSERT OR IGNORE INTO transactions (date, description, amount, type, unique_hash) VALUES (?,?,?,?,?)', 
                         (date, desc, amt, t_type, h))
        except: continue
    conn.commit()
    conn.close()

@app.route('/')
def index():
    selected_month = request.args.get('month', 'All')
    conn = sqlite3.connect('finances.db')
    df = pd.read_sql_query("SELECT * FROM transactions", conn)
    conn.close()

    if df.empty: return render_template('index.html', transactions=[], months=[], selected_month='All', graph_json=None, summary={})

    df['date_dt'] = pd.to_datetime(df['date'], dayfirst=True)
    df = df.sort_values('date_dt')
    df['month_year'] = df['date_dt'].dt.strftime('%b %Y')
    
    months = sorted(df['month_year'].unique().tolist(), key=lambda x: pd.to_datetime(x, format='%b %Y'), reverse=True)
    disp_df = df if selected_month == 'All' else df[df['month_year'] == selected_month]

    # --- SUMMARY CALCULATIONS ---
    summary = {
        'income': disp_df[disp_df['type'] == 'Credit']['amount'].sum(),
        'expense': disp_df[disp_df['type'] == 'Debit']['amount'].sum()
    }

    # --- PLOTLY FIX: GREEN/RED & PROPER HOVER ---
    fig = px.line(disp_df, x='date_dt', y='amount', color='type',
                  markers=True, title=f"Activity: {selected_month}",
                  color_discrete_map={'Debit': '#dc2626', 'Credit': '#16a34a'}, # RED and GREEN
                  custom_data=['description', 'type'])

    fig.update_traces(
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Amount: ₹%{y:,.2f}<br>Type: %{customdata[1]}<br>Desc: %{customdata[0]}<extra></extra>"
    )
    
    fig.update_layout(hovermode="x unified", template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    
    graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return render_template('index.html', transactions=disp_df.sort_values('date_dt', ascending=False).to_dict('records'), 
                           months=months, selected_month=selected_month, graph_json=graph_json, summary=summary)

if __name__ == '__main__':
    app.run(debug=True)