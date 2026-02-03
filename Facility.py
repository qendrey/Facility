import streamlit as st
import pandas as pd
import datetime
import uuid
import hashlib
import sqlite3
from io import BytesIO

# ==========================================
# 1. DATABASE SETUP (PERSISTENCE)
# ==========================================
def init_db():
    conn = sqlite3.connect('facility.db', check_same_thread=False)
    c = conn.cursor()
    
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    name TEXT,
                    email TEXT,
                    dept TEXT,
                    hod_email TEXT,
                    force_reset INTEGER
                )''')
    
    # Requests Table
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    user_key TEXT,
                    requester_name TEXT,
                    department TEXT,
                    approver_email TEXT,
                    category TEXT,
                    item TEXT,
                    status TEXT,
                    amount REAL,
                    initial_cost REAL,
                    vendor TEXT,
                    invoice_img BLOB,
                    sac_note TEXT,
                    date TEXT
                )''')
    
    # Audit Trail
    c.execute('''CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    user TEXT,
                    action TEXT,
                    details TEXT
                )''')

    # Payments Table
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
                    payment_id TEXT PRIMARY KEY,
                    req_id TEXT,
                    amount REAL,
                    status TEXT,
                    vendor TEXT
                )''')

    # --- Create Default Superuser if not exists ---
    c.execute("SELECT * FROM users WHERE username = 'super'")
    if not c.fetchone():
        # Password is "123" -> hash
        p_hash = hashlib.sha256(str.encode("123")).hexdigest()
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)", 
                  ('super', p_hash, 'Superuser', 'IT Admin', 'it@co.com', 'IT', '', 0))
        conn.commit()

    return conn

conn = init_db()

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
st.set_page_config(page_title="Facility 365 Portal", layout="wide", page_icon="🏢")

def make_hash(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hash(password, hashed_text):
    return make_hash(password) == hashed_text

def run_query(query, params=(), fetch=False):
    c = conn.cursor()
    c.execute(query, params)
    if fetch:
        return c.fetchall()
    conn.commit()

def log_action(user, action, details):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_query("INSERT INTO audit (timestamp, user, action, details) VALUES (?,?,?,?)", (ts, user, action, details))

def get_user(username):
    data = run_query("SELECT * FROM users WHERE username = ?", (username,), fetch=True)
    if data:
        # Map tuple to dict
        u = data[0]
        return {"username": u[0], "password": u[1], "role": u[2], "name": u[3], "email": u[4], "dept": u[5], "hod_email": u[6], "force_reset": u[7]}
    return None

# --- STATE MANAGEMENT ---
if 'cart' not in st.session_state: st.session_state.cart = []
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_role' not in st.session_state: st.session_state.user_role = ""
if 'current_user_key' not in st.session_state: st.session_state.current_user_key = ""
if 'user_data' not in st.session_state: st.session_state.user_data = {}

# --- CONSTANTS ---
STATIONARY_ITEMS = sorted(["05A Toner", "A4 Paper", "Biro", "Staplers", "Notepads", "File Folders"])
CATEGORY_OPTIONS = {
    "Facility": ["Door Repair", "AC Repair", "Electrical", "Plumbing", "Generator"],
    "Furniture": ["Chair Repair", "Table Repair", "New Chair"],
    "Communication": ["CUG Issue", "Airtime Request", "Bulk SMS Recharge", "Internet Issue"],
    "Stationary": STATIONARY_ITEMS,
    "Others": []
}

# ==========================================
# 3. CORE LOGIC
# ==========================================

def process_cart_submission(user_dict):
    if not st.session_state.cart: return
    
    # 1. Stationary
    stationary = [i for i in st.session_state.cart if i['type'] == "Stationary"]
    if stationary:
        desc = ", ".join([f"{i['item']} ({i['qty']})" for i in stationary])
        rid = str(uuid.uuid4())[:8]
        date_str = str(datetime.date.today())
        
        run_query('''INSERT INTO requests (id, user_key, requester_name, department, approver_email, category, item, status, amount, initial_cost, vendor, sac_note, date)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', 
                  (rid, user_dict['username'], user_dict['name'], user_dict['dept'], user_dict['hod_email'], 
                   "Stationary", desc, "Pending Admin", 0.0, 0.0, "Store", "", date_str))
        log_action(user_dict['name'], "Request", f"Stationary #{rid}")

    # 2. Others
    others = [i for i in st.session_state.cart if i['type'] != "Stationary"]
    for i in others:
        rid = str(uuid.uuid4())[:8]
        date_str = str(datetime.date.today())
        
        # Determine Routing
        status = "Pending Dept HOD"
        if i['type'] == "Communication" and i['item'] == "CUG Issue": status = "Pending Admin"
        if i['type'] == "Stationary": status = "Pending Admin" # Safety catch

        run_query('''INSERT INTO requests (id, user_key, requester_name, department, approver_email, category, item, status, amount, initial_cost, vendor, sac_note, date)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', 
                  (rid, user_dict['username'], user_dict['name'], user_dict['dept'], user_dict['hod_email'], 
                   i['type'], i['item'], status, 0.0, 0.0, "Pending", "", date_str))
        log_action(user_dict['name'], "Request", f"{i['type']} #{rid}")
    
    st.session_state.cart = []

def login_function():
    st.markdown("## 🔐 Facility 365 Login")
    with st.form("login_form"):
        u = st.text_input("Username").lower()
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            user = get_user(u)
            if user and check_hash(p, user['password']):
                st.session_state.logged_in = True
                st.session_state.user_role = user['role']
                st.session_state.user_name = user['name']
                st.session_state.user_email = user['email']
                st.session_state.current_user_key = u
                st.session_state.user_data = user
                log_action(user['name'], "Login", "Success")
                st.rerun()
            else: st.error("Invalid Credentials")

def change_password_flow():
    st.warning("⚠️ **Security Alert:** You are using a temporary password.")
    with st.form("reset_pw"):
        p1 = st.text_input("New Password", type="password")
        p2 = st.text_input("Confirm New Password", type="password")
        if st.form_submit_button("Update Password"):
            if p1 == p2 and len(p1) > 0:
                new_hash = make_hash(p1)
                run_query("UPDATE users SET password = ?, force_reset = 0 WHERE username = ?", (new_hash, st.session_state.current_user_key))
                st.success("Updated! Redirecting..."); st.session_state.user_data['force_reset'] = 0; st.rerun()
            else: st.error("Passwords mismatch.")

# ==========================================
# 4. DASHBOARD LOGIC
# ==========================================

def get_db_df(table_name="requests"):
    cols = ["id", "user_key", "requester_name", "department", "approver_email", "category", "item", "status", "amount", "initial_cost", "vendor", "invoice_img", "sac_note", "date"]
    data = run_query(f"SELECT * FROM {table_name}", fetch=True)
    return pd.DataFrame(data, columns=cols)

def view_staff_portal(user):
    st.header(f"📝 {user['name']} | {user['dept']}")
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            cat = st.selectbox("Category", list(CATEGORY_OPTIONS.keys()))
            sel, qty = "", 1
            if cat == "Stationary":
                sel = st.selectbox("Item", CATEGORY_OPTIONS["Stationary"]); qty = st.number_input("Qty", 1, value=1)
            elif cat == "Others": sel = st.text_input("Description")
            else: sel = st.selectbox("Issue", CATEGORY_OPTIONS[cat])
            if st.button("Add") and sel: 
                st.session_state.cart.append({"type": cat, "item": sel, "qty": qty}); st.success("Added")
    with c2:
        if st.session_state.cart:
            st.table(pd.DataFrame(st.session_state.cart))
            if st.button("🚀 Submit"): process_cart_submission(user); st.success("Sent"); st.rerun()
    
    st.divider(); st.subheader("History")
    data = run_query("SELECT date, category, item, status FROM requests WHERE user_key = ?", (user['username'],), fetch=True)
    if data: st.dataframe(pd.DataFrame(data, columns=["Date", "Category", "Item", "Status"]), use_container_width=True)

def view_admin_dashboard():
    st.title("🛠️ Admin")
    t1, t2 = st.tabs(["Tasks", "Analysis"])
    with t1:
        # Fetch Pending Admin
        reqs = run_query("SELECT id, item, requester_name, category, amount FROM requests WHERE status = 'Pending Admin'", fetch=True)
        if not reqs: st.info("No tasks.")
        for r in reqs:
            rid, item, name, cat, amt = r
            with st.container(border=True):
                st.write(f"**{item}** ({name})")
                if cat == "Stationary":
                    if st.button("Issue", key=f"s_{rid}"): 
                        run_query("UPDATE requests SET status='Completed (Fulfilled)' WHERE id=?", (rid,)); st.rerun()
                elif item == "CUG Issue":
                    if st.button("Resolve (No Cost)", key=f"cug_{rid}"):
                        run_query("UPDATE requests SET status='Completed (Resolved)' WHERE id=?", (rid,)); st.rerun()
                
                if cat != "Stationary":
                    with st.form(key=f"f_{rid}"):
                        v = st.text_input("Vendor")
                        c = st.number_input("Cost (₦)", step=1000.0)
                        img = st.file_uploader("Invoice")
                        if st.form_submit_button("Submit"):
                            if v and c > 0 and img:
                                ib = img.getvalue()
                                run_query("UPDATE requests SET vendor=?, amount=?, initial_cost=?, invoice_img=?, status='Pending SS HOD' WHERE id=?", (v, c, c, ib, rid))
                                st.rerun()
    with t2:
        df = get_db_df()
        if not df.empty: st.dataframe(df[["date","category","item","requester_name","vendor","amount","status"]], use_container_width=True)

def view_approver_dashboard(role, status_trigger, next_status, label):
    st.header(f"{label} Dashboard")
    # Fetch requests matching status
    reqs = run_query(f"SELECT * FROM requests WHERE status = '{status_trigger}'", fetch=True)
    if not reqs: st.info("No pending approvals.")
    
    cols = ["id", "user_key", "requester_name", "department", "approver_email", "category", "item", "status", "amount", "initial_cost", "vendor", "invoice_img", "sac_note", "date"]
    
    for r_raw in reqs:
        # Convert tuple to dict
        r = dict(zip(cols, r_raw))
        
        with st.expander(f"{r['item']} - ₦{r['amount']:,.2f}"):
            if r['invoice_img']: st.image(BytesIO(r['invoice_img']), width=300)
            st.write(f"Vendor: {r['vendor']}")
            if r['sac_note']: st.info(f"SAC Note: {r['sac_note']}")
            
            c1, c2 = st.columns(2)
            if c1.button("Approve", key=f"y_{r['id']}"):
                # GMD Special Logic
                if role == "GMD":
                     run_query("UPDATE requests SET status='Approved' WHERE id=?", (r['id'],))
                     run_query("INSERT INTO payments (payment_id, req_id, amount, status, vendor) VALUES (?,?,?,?,?)", 
                               (str(uuid.uuid4())[:8], r['id'], r['amount'], "Ready for Accounts", r['vendor']))
                else:
                    run_query(f"UPDATE requests SET status='{next_status}' WHERE id=?", (r['id'],))
                st.rerun()
            if c2.button("Decline", key=f"n_{r['id']}"):
                run_query("UPDATE requests SET status='Declined' WHERE id=?", (r['id'],)); st.rerun()

def view_sac_dashboard():
    st.header("⚖️ SAC Dashboard")
    t1, t2 = st.tabs(["Reviews", "Reports"])
    
    with t1:
        reqs = run_query("SELECT * FROM requests WHERE status='Pending SAC'", fetch=True)
        cols = ["id", "user_key", "requester_name", "department", "approver_email", "category", "item", "status", "amount", "initial_cost", "vendor", "invoice_img", "sac_note", "date"]
        
        for r_raw in reqs:
            r = dict(zip(cols, r_raw))
            with st.container(border=True):
                c1, c2 = st.columns([1,2])
                with c1: 
                    if r['invoice_img']: st.image(BytesIO(r['invoice_img']), use_column_width=True)
                with c2:
                    st.write(f"**{r['item']}** | Vendor: {r['vendor']}")
                    st.write(f"Admin Quote: ₦{r['amount']:,.2f}")
                    
                    new_cost = st.number_input("Negotiated Cost", value=r['amount'], key=f"sac_c_{r['id']}")
                    note = st.text_area("Note", key=f"sac_n_{r['id']}")
                    
                    if st.button("Validate", key=f"sac_v_{r['id']}"):
                        run_query("UPDATE requests SET amount=?, sac_note=?, status='Pending ED' WHERE id=?", (new_cost, note, r['id']))
                        st.rerun()
    with t2:
        # Savings Report
        data = run_query("SELECT date, item, vendor, initial_cost, amount, sac_note FROM requests WHERE initial_cost > amount AND status IN ('Approved','Paid','Ready for Accounts','Pending ED','Pending GMD')", fetch=True)
        if data:
            df = pd.DataFrame(data, columns=["Date", "Item", "Vendor", "Initial", "Final", "Note"])
            df['Savings'] = df['Initial'] - df['Final']
            st.metric("Total Savings", f"₦{df['Savings'].sum():,.2f}")
            st.dataframe(df, use_container_width=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode('utf-8'), "savings.csv", "text/csv")

def view_hod_dashboard():
    u = st.session_state.user_data
    st.header("Dept HOD")
    t1, t2 = st.tabs(["Approvals", "Spend"])
    with t1:
        # HOD Specific: Only requests for their dept where they are approver
        reqs = run_query("SELECT id, item, requester_name, amount FROM requests WHERE status='Pending Dept HOD' AND approver_email=?", (u['email'],), fetch=True)
        for r in reqs:
            with st.container(border=True):
                st.write(f"Request: {r[1]} by {r[2]}")
                c1, c2 = st.columns(2)
                if c1.button("Approve", key=f"h_y_{r[0]}"): 
                    run_query("UPDATE requests SET status='Pending Admin' WHERE id=?", (r[0],)); st.rerun()
                if c2.button("Decline", key=f"h_n_{r[0]}"): 
                    run_query("UPDATE requests SET status='Declined' WHERE id=?", (r[0],)); st.rerun()
    with t2:
        data = run_query("SELECT date, item, vendor, amount FROM requests WHERE department=? AND status IN ('Approved','Paid')", (u['dept'],), fetch=True)
        if data: st.dataframe(pd.DataFrame(data, columns=["Date", "Item", "Vendor", "Amount"]), use_container_width=True)

def view_superuser():
    st.title("🛡️ Superuser")
    with st.form("add_user"):
        c1, c2 = st.columns(2)
        u = c1.text_input("Username").lower()
        p = c2.text_input("Temp Pass")
        n = c1.text_input("Name")
        e = c2.text_input("Email")
        r = c1.selectbox("Role", ["Staff", "Dept HOD", "Admin", "SS HOD", "SAC", "ED", "GMD", "Accounts"])
        d = c2.text_input("Dept")
        h = c1.text_input("HOD Email")
        if st.form_submit_button("Create") and u and p:
            ph = make_hash(p)
            try:
                run_query("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)", (u, ph, r, n, e, d, h, 1))
                st.success("Created!"); st.rerun()
            except: st.error("Username exists")
    
    st.divider()
    users = run_query("SELECT username, role, name, dept FROM users", fetch=True)
    st.dataframe(pd.DataFrame(users, columns=["User", "Role", "Name", "Dept"]), use_container_width=True)

def view_accounts():
    st.header("💰 Accounts")
    # Join payments with requests to get Invoice Image
    # payment: payment_id, req_id, amount, status, vendor
    payments = run_query("SELECT p.payment_id, p.amount, p.vendor, r.item, r.invoice_img FROM payments p JOIN requests r ON p.req_id = r.id WHERE p.status='Ready for Accounts'", fetch=True)
    
    for p in payments:
        pid, amt, vend, item, img = p
        with st.container(border=True):
            c1, c2 = st.columns([1,2])
            with c1: 
                if img: st.image(BytesIO(img), width=150)
            with c2:
                st.info(f"Pay ₦{amt:,.2f} to {vend} ({item})")
                if st.button("Mark Paid", key=f"p_{pid}"):
                    run_query("UPDATE payments SET status='Paid' WHERE payment_id=?", (pid,)); st.rerun()

# ==========================================
# 5. MAIN ROUTER
# ==========================================
def main():
    if not st.session_state.logged_in:
        login_function()
        st.info("Default Superuser: `super` / `123`")
    else:
        user = st.session_state.user_data
        
        # Reload user data to check for force_reset flag updates
        current_u_data = get_user(st.session_state.current_user_key)
        
        if current_u_data['force_reset'] == 1:
            change_password_flow()
        else:
            with st.sidebar:
                st.write(f"👤 **{user['name']}**")
                st.caption(f"Role: {user['role']}")
                if st.button("Logout"): 
                    st.session_state.logged_in = False; st.rerun()
            
            role = user['role']
            if role == "Staff": view_staff_portal(user)
            elif role == "Dept HOD": view_hod_dashboard()
            elif role == "Admin": view_admin_dashboard()
            elif role == "SS HOD": view_approver_dashboard(role, "Pending SS HOD", "Pending SAC", "SS HOD")
            elif role == "SAC": view_sac_dashboard()
            elif role == "ED": view_approver_dashboard(role, "Pending ED", "Pending GMD", "ED")
            elif role == "GMD": view_approver_dashboard(role, "Pending GMD", "Approved", "GMD")
            elif role == "Accounts": view_accounts()
            elif role == "Superuser": view_superuser()

if __name__ == "__main__":
    main()