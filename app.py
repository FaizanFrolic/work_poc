import streamlit as st
import pandas as pd
import sqlite3
import bcrypt
import os
import uuid
import json
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO
from streamlit_gsheets import GSheetsConnection

# Configuration
DB_FILE = 'submissions.db'
TABLE_NAME = 'data_submissions'
USER_TABLE = 'users'
AUDIT_LOG_TABLE = 'audit_logs'

# --- Database Management ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Data submissions table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            client TEXT, brm TEXT, lob TEXT,
            data_a TEXT, data_b TEXT, data_c TEXT, data_d TEXT,
            submitted_by TEXT
        )
    ''')
    # Users table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {USER_TABLE} (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            role TEXT,
            session_token TEXT,
            token_expiry TEXT
        )
    ''')
    # Audit Logs table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {AUDIT_LOG_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            record_id INTEGER,
            action TEXT,
            changed_by TEXT,
            old_values TEXT,
            new_values TEXT
        )
    ''')

    # Migration: Add columns if they don't exist
    c.execute(f"PRAGMA table_info({USER_TABLE})")
    columns = [info[1] for info in c.fetchall()]
    if "session_token" not in columns:
        c.execute(f"ALTER TABLE {USER_TABLE} ADD COLUMN session_token TEXT")
    if "token_expiry" not in columns:
        c.execute(f"ALTER TABLE {USER_TABLE} ADD COLUMN token_expiry TEXT")

    c.execute(f"PRAGMA table_info({TABLE_NAME})")
    sub_columns = [info[1] for info in c.fetchall()]
    if "submitted_by" not in sub_columns:
        c.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN submitted_by TEXT")
    
    # Create default admin user if none exist
    c.execute(f"SELECT COUNT(*) FROM {USER_TABLE}")
    if c.fetchone()[0] == 0:
        hashed = bcrypt.hashpw("password123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        c.execute(f"INSERT INTO {USER_TABLE} (username, password_hash, role) VALUES (?, ?, ?)", 
                  ("admin", hashed, "admin"))
    
    conn.commit()
    conn.close()

def display_sync_manager():
    st.header("🔄 Cloud Sync Manager")
    
    # 0. Cache Clearing Button
    if st.button("🔄 Force Refresh from Cloud"):
        st.cache_data.clear()
        st.rerun()

    try:
        # 1. Load Local Data
        conn = sqlite3.connect(DB_FILE)
        df_local = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", conn)
        conn.close()

        # 2. Load Cloud Data (ttl=0 for live fetch)
        gs_conn = st.connection("gsheets", type=GSheetsConnection)
        df_cloud = gs_conn.read(worksheet="Submissions", ttl=0)
        
        # --- ROBUSTNESS CLEANUP ---
        # A. Drop completely empty rows/columns from Cloud
        df_cloud = df_cloud.dropna(how='all').dropna(axis=1, how='all')
        
        # B. Standardize Column Names (Force lowercase)
        df_local.columns = [c.lower() for c in df_local.columns]
        if not df_cloud.empty:
            df_cloud.columns = [c.lower() for c in df_cloud.columns]
        
        # C. Force ID Type Consistency
        if not df_local.empty: df_local['id'] = pd.to_numeric(df_local['id'], errors='coerce').fillna(0).astype(int)
        if not df_cloud.empty: df_cloud['id'] = pd.to_numeric(df_cloud['id'], errors='coerce').fillna(0).astype(int)
        # --------------------------

        # --- DEEP COMPARISON ---
        local_ids = set(df_local['id']) if not df_local.empty else set()
        cloud_ids = set(df_cloud['id']) if not df_cloud.empty else set()

        missing_in_cloud = df_local[~df_local['id'].isin(cloud_ids)] if not df_local.empty else pd.DataFrame()
        missing_in_local = df_cloud[~df_cloud['id'].isin(local_ids)] if not df_cloud.empty else pd.DataFrame()

        # Check for data mismatches where IDs match
        content_mismatch = pd.DataFrame()
        if not df_local.empty and not df_cloud.empty:
            merged = pd.merge(df_local, df_cloud, on='id', suffixes=('_local', '_cloud'), how='inner')
            # Compare a few key columns (client, brm, lob)
            for col in ['client', 'brm', 'lob']:
                if col in merged.columns or f"{col}_local" in merged.columns:
                    mask = merged[f"{col}_local"].astype(str) != merged[f"{col}_cloud"].astype(str)
                    if mask.any():
                        content_mismatch = merged[mask]
                        break

        row_counts_match = len(df_local) == len(df_cloud)
        is_synced = len(missing_in_cloud) == 0 and len(missing_in_local) == 0 and len(content_mismatch) == 0 and row_counts_match
        
        # 3. Status Header
        status_col, metric_col1, metric_col2 = st.columns([1, 2, 2])
        with status_col:
            if is_synced:
                st.markdown("### Status\n# 🟢")
                st.caption("Perfectly Synced")
            else:
                st.markdown("### Status\n# 🔴")
                st.caption("Mismatch Detected")
        
        with metric_col1:
            st.metric("Local Records", len(df_local))
        with metric_col2:
            st.metric("Cloud Records", len(df_cloud))

        st.divider()

        # 4. Detailed Diff Sections
        if not is_synced:
            if not row_counts_match:
                st.error(f"❌ Row count mismatch! Local: {len(df_local)} | Cloud: {len(df_cloud)}")
            
            if not missing_in_cloud.empty:
                st.warning(f"⚠️ {len(missing_in_cloud)} records exist locally but are missing from Cloud.")
                st.dataframe(missing_in_cloud[['id', 'client', 'timestamp']], use_container_width=True)
            
            if not missing_in_local.empty:
                st.error(f"⚠️ {len(missing_in_local)} records exist in Cloud but are missing locally.")
                st.dataframe(missing_in_local[['id', 'client', 'timestamp']], use_container_width=True)
                
            if not content_mismatch.empty:
                st.info(f"⚠️ {len(content_mismatch)} records have different data but same ID.")
                st.dataframe(content_mismatch, use_container_width=True)
        else:
            st.success("Everything is perfectly matched!")

        st.divider()

        # 5. Action Buttons
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📤 Push to Cloud")
            if st.button("Push Local → Cloud", type="primary", use_container_width=True):
                confirm_push_dialog()
        
        with c2:
            st.subheader("📥 Pull to Local")
            if st.button("Pull Cloud → Local", type="secondary", use_container_width=True):
                confirm_pull_dialog()

    except Exception as e:
        st.error(f"Sync Manager Error: {e}")

# --- Google Sheets Integration ---
def recover_from_gsheet():
    """Pulls data from Google Sheets and populates SQLite."""
    try:
        gs_conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Recover Submissions
        df_submissions = gs_conn.read(worksheet="Submissions")
        if not df_submissions.empty:
            conn = sqlite3.connect(DB_FILE)
            # Replace local table with cloud data
            df_submissions.to_sql(TABLE_NAME, conn, if_exists='replace', index=False)
            conn.close()
        
        # Recover Audit Logs
        try:
            df_audit = gs_conn.read(worksheet="AuditLogs")
            if not df_audit.empty:
                conn = sqlite3.connect(DB_FILE)
                df_audit.to_sql(AUDIT_LOG_TABLE, conn, if_exists='replace', index=False)
                conn.close()
        except: pass 
            
        return True
    except Exception as e:
        st.error(f"Cloud Recovery Error: {e}")
        return False

def sync_to_gsheet():
    """Syncs the entire SQLite table and Audit Logs to Google Sheets."""
    try:
        conn = sqlite3.connect(DB_FILE)
        df_submissions = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", conn)
        df_audit = pd.read_sql_query(f"SELECT * FROM {AUDIT_LOG_TABLE}", conn)
        conn.close()
        
        gs_conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Sync Submissions (Required)
        if not df_submissions.empty:
            gs_conn.update(worksheet="Submissions", data=df_submissions)
        
        # Sync Audit Logs (Optional)
        if not df_audit.empty:
            try:
                gs_conn.update(worksheet="AuditLogs", data=df_audit)
            except Exception:
                pass 
            
        return True
    except Exception as e:
        st.sidebar.error(f"Cloud Sync Error: {e}")
        return False
    return True

def log_action(record_id, action, old_values=None, new_values=None):
    """Helper to log actions in the audit_logs table."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f'''
            INSERT INTO {AUDIT_LOG_TABLE} (timestamp, record_id, action, changed_by, old_values, new_values)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            record_id,
            action,
            st.session_state.get("username", "System"),
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Logging error: {e}")

# --- User Management Logic ---
def delete_user(username):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"DELETE FROM {USER_TABLE} WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def update_user_role(username, new_role):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"UPDATE {USER_TABLE} SET role = ? WHERE username = ?", (new_role, username))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def reset_user_password(username, new_password):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        c.execute(f"UPDATE {USER_TABLE} SET password_hash = ? WHERE username = ?", (hashed, username))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

# --- Dialogs ---
@st.dialog("🔑 Reset User Password")
def reset_password_dialog(username):
    st.write(f"Resetting password for: **{username}**")
    new_pwd = st.text_input("New Password", type="password")
    confirm_pwd = st.text_input("Confirm New Password", type="password")
    if st.button("Set New Password"):
        if new_pwd != confirm_pwd:
            st.error("Passwords do not match.")
        else:
            if reset_user_password(username, new_pwd):
                st.success(f"Password for {username} updated!")
                st.rerun()

@st.dialog("🗑️ Delete User")
def delete_user_dialog(username):
    st.warning(f"Are you sure you want to PERMANENTLY delete user **{username}**?")
    if st.button("Confirm Delete User", type="primary"):
        if delete_user(username):
            st.success(f"User {username} deleted.")
            st.rerun()

# --- UI Components ---
def display_user_management():
    st.header("👤 User Management Console")
    try:
        conn = sqlite3.connect(DB_FILE)
        df_users = pd.read_sql_query(f"SELECT username, role, token_expiry FROM {USER_TABLE}", conn)
        conn.close()

        st.write(f"Total Users: {len(df_users)}")
        
        # Display as a table-like structure for better control
        h_col1, h_col2, h_col3 = st.columns([2, 1, 2])
        with h_col1: st.markdown("**Username**")
        with h_col2: st.markdown("**Role**")
        with h_col3: st.markdown("**Actions**")
        st.divider()

        for _, row in df_users.iterrows():
            r_col1, r_col2, r_col3 = st.columns([2, 1, 2])
            with r_col1: st.write(row['username'])
            with r_col2: 
                new_role = st.selectbox("Role", ["user", "admin"], index=0 if row['role'] == "user" else 1, key=f"role_{row['username']}")
                if new_role != row['role']:
                    if update_user_role(row['username'], new_role):
                        st.success(f"Updated {row['username']} to {new_role}!")
                        st.rerun()

            with r_col3:
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("🔑 Reset", key=f"reset_{row['username']}"):
                        reset_password_dialog(row['username'])
                with btn_col2:
                    # Prevent admin from deleting themselves
                    if row['username'] != st.session_state["username"]:
                        if st.button("🗑️ Del", key=f"del_user_{row['username']}"):
                            delete_user_dialog(row['username'])
                    else:
                        st.caption("(Self - Protected)")
            st.divider()

    except Exception as e:
        st.error(f"User management error: {e}")

# --- Authentication Logic ---
def verify_login(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"SELECT password_hash, role FROM {USER_TABLE} WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    if result and bcrypt.checkpw(password.encode('utf-8'), result[0].encode('utf-8')):
        return result[1]
    return None

def create_session(username):
    """Generates a token, saves to DB, and puts it in the URL."""
    token = str(uuid.uuid4())
    expiry = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE {USER_TABLE} SET session_token = ?, token_expiry = ? WHERE username = ?", (token, expiry, username))
    conn.commit()
    conn.close()
    st.query_params["s"] = token
    return token

def check_session_from_url():
    """Checks the URL for a 's' parameter and logs the user back in if valid."""
    token = st.query_params.get("s")
    if token:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"SELECT username, role, token_expiry FROM {USER_TABLE} WHERE session_token = ?", (token,))
        result = c.fetchone()
        conn.close()
        
        if result:
            username, role, expiry = result
            if datetime.now() < datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S"):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.session_state["role"] = role
                return True
    return False

def login_screen():
    st.title("🔐 Secure Portal Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            role = verify_login(username, password)
            if role:
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.session_state["role"] = role
                create_session(username)
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid username or password.")

# --- App Features ---
def save_to_db(data):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f'''
            INSERT INTO {TABLE_NAME} (timestamp, client, brm, lob, data_a, data_b, data_c, data_d, submitted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data["Timestamp"], data["Client"], data["BRM"], data["LOB"], 
            data["DataA"], data["DataB"], data["DataC"], data["DataD"],
            st.session_state["username"]
        ))
        record_id = c.lastrowid
        conn.commit()
        conn.close()
        
        log_action(record_id, "INSERT", new_values=data)
        sync_to_gsheet() 
        return True
    except Exception as e:
        st.error(f"Database error: {e}")
        return False

def update_db(record_id, data):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = ?", (record_id,))
        old_row = c.fetchone()
        old_values = dict(zip([d[0] for d in c.description], old_row)) if old_row else None
        
        c.execute(f'''
            UPDATE {TABLE_NAME}
            SET client = ?, brm = ?, lob = ?, data_a = ?, data_b = ?, data_c = ?, data_d = ?
            WHERE id = ?
        ''', (data["client"], data["brm"], data["lob"], data["data_a"], data["data_b"], data["data_c"], data["data_d"], record_id))
        conn.commit()
        conn.close()
        
        log_action(record_id, "UPDATE", old_values=old_values, new_values=data)
        sync_to_gsheet() 
        return True
    except Exception as e:
        st.error(f"Database error: {e}")
        return False

def delete_from_db(record_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = ?", (record_id,))
        old_row = c.fetchone()
        old_values = dict(zip([d[0] for d in c.description], old_row)) if old_row else None
        
        c.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (record_id,))
        conn.commit()
        conn.close()
        
        log_action(record_id, "DELETE", old_values=old_values)
        sync_to_gsheet() 
        return True
    except Exception as e:
        st.error(f"Database error: {e}")
        return False

def get_data_as_excel(username, role):
    try:
        conn = sqlite3.connect(DB_FILE)
        if role == "admin":
            query = f"SELECT * FROM {TABLE_NAME}"
            params = ()
        else:
            query = f"SELECT * FROM {TABLE_NAME} WHERE submitted_by = ?"
            params = (username,)

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Submissions')
        return output.getvalue()
    except Exception: return None


# --- Dialogs ---
@st.dialog("📤 Confirm Push to Cloud")
def confirm_push_dialog():
    st.warning("⚠️ This will OVERWRITE the Google Sheet with your local database. This cannot be undone.")
    password = st.text_input("Enter your Admin Password to confirm", type="password")
    if st.button("Confirm & Overwrite Cloud"):
        if verify_login(st.session_state["username"], password):
            if sync_to_gsheet():
                st.success("Cloud updated successfully!")
                st.rerun()
        else:
            st.error("Invalid password. Action cancelled.")

@st.dialog("📥 Confirm Pull from Cloud")
def confirm_pull_dialog():
    st.error("🛑 This will DELETE all local data and rebuild your database from the Google Sheet.")
    password = st.text_input("Enter your Admin Password to confirm", type="password")
    if st.button("Confirm & Rebuild Local DB"):
        if verify_login(st.session_state["username"], password):
            if recover_from_gsheet():
                st.success("Local database rebuilt!")
                st.rerun()
        else:
            st.error("Invalid password. Action cancelled.")

@st.dialog("📋 Submission Details", width="large")
def view_details_dialog(row):
    st.markdown(f"### Record #{row['id']}")
    col_a, col_b, col_c = st.columns(3)
    with col_a: st.metric("Client", row['client'])
    with col_b: st.metric("BRM", row['brm'])
    with col_c: st.metric("LOB", row['lob'])
    
    st.divider()
    st.markdown("#### 🔍 Detailed Data Fields")
    
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**DataA**")
        st.info(row['data_a'] if row['data_a'] else "N/A")
        st.markdown("**DataB**")
        st.info(row['data_b'] if row['data_b'] else "N/A")
    with d2:
        st.markdown("**DataC**")
        st.info(row['data_c'] if row['data_c'] else "N/A")
        st.markdown("**DataD**")
        st.info(row['data_d'] if row['data_d'] else "N/A")
    
    st.divider()
    st.caption(f"Submitted by: {row['submitted_by'] if row['submitted_by'] else 'Legacy'} | Timestamp: {row['timestamp']}")

@st.dialog("✏️ Edit Submission")
def edit_submission_dialog(row):
    with st.form("edit_form"):
        col1, col2 = st.columns(2)
        with col1:
            client = st.text_input("Client", value=row['client'])
            brm = st.text_input("BRM", value=row['brm'])
        with col2:
            lob = st.text_input("LOB", value=row['lob'])
        
        st.markdown("### Details")
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            data_a = st.text_input("DataA", value=row['data_a'])
            data_b = st.text_input("DataB", value=row['data_b'])
        with d_col2:
            data_c = st.text_input("DataC", value=row['data_c'])
            data_d = st.text_input("DataD", value=row['data_d'])
            
        if st.form_submit_button("Update Data"):
            updated_data = {
                "client": client, "brm": brm, "lob": lob,
                "data_a": data_a, "data_b": data_b, "data_c": data_c, "data_d": data_d
            }
            if update_db(row['id'], updated_data):
                st.success("Updated successfully!")
                st.rerun()

@st.dialog("🗑️ Delete Submission")
def delete_submission_dialog(row_id):
    st.warning(f"Are you sure you want to delete record #{row_id}?")
    if st.button("Confirm Delete"):
        if delete_from_db(row_id):
            st.success("Deleted successfully!")
            st.rerun()

@st.dialog("➕ Add New User")
def add_user_dialog():
    with st.form("add_user_form"):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        new_role = st.selectbox("Role", ["user", "admin"])
        
        if st.form_submit_button("Create User"):
            if not new_username or not new_password:
                st.error("Username and password are required.")
            else:
                try:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    c.execute(f"INSERT INTO {USER_TABLE} (username, password_hash, role) VALUES (?, ?, ?)", 
                              (new_username, hashed, new_role))
                    conn.commit()
                    conn.close()
                    st.success(f"User '{new_username}' created successfully!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Username already exists.")
                except Exception as e:
                    st.error(f"Error: {e}")

# --- UI Components ---
def display_dashboard():
    st.header("📊 Interactive Dashboard")
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", conn)
        conn.close()
        
        if df.empty:
            st.info("No data available for dashboard.")
            return

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Submissions", len(df))
        m2.metric("Unique Clients", df['client'].nunique())
        m3.metric("Unique LOBs", df['lob'].nunique())
        
        st.divider()
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Submissions by LOB")
            fig_lob = px.pie(df, names='lob', hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig_lob, use_container_width=True)
            
        with col2:
            st.subheader("Top Clients")
            client_counts = df['client'].value_counts().reset_index()
            client_counts.columns = ['Client', 'Count']
            fig_client = px.bar(client_counts.head(10), x='Client', y='Count', color='Count', color_continuous_scale='Viridis')
            st.plotly_chart(fig_client, use_container_width=True)
            
        st.subheader("Submissions Over Time")
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        date_counts = df['date'].value_counts().sort_index().reset_index()
        date_counts.columns = ['Date', 'Submissions']
        fig_time = px.line(date_counts, x='Date', y='Submissions', markers=True)
        st.plotly_chart(fig_time, use_container_width=True)

    except Exception as e:
        st.error(f"Dashboard error: {e}")

def display_audit_logs():
    st.header("🕵️ Audit Logs")
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query(f"SELECT * FROM {AUDIT_LOG_TABLE} ORDER BY id DESC", conn)
        conn.close()
        
        if df.empty:
            st.info("No audit logs found.")
            return

        search_id = st.text_input("Search by Record ID")
        if search_id:
            df = df[df['record_id'].astype(str) == search_id]

        st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Audit Log error: {e}")

# --- Main App Interface ---
def main():
    st.set_page_config(page_title="Secure Data Portal", layout="wide", initial_sidebar_state="collapsed")
    init_db()
    
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
        check_session_from_url()

    if not st.session_state["authenticated"]:
        login_screen()
        return

    # --- Sidebar ---
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        st.caption(f"Role: {st.session_state['role']}")
        
        if st.button("🚪 Logout"):
            st.session_state["authenticated"] = False
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute(f"UPDATE {USER_TABLE} SET session_token = NULL WHERE username = ?", (st.session_state["username"],))
            conn.commit()
            conn.close()
            st.query_params.clear()
            st.rerun()
            
        st.divider()
        if st.session_state["role"] == "admin":
            if st.button("➕ Add New User"): add_user_dialog()
            if st.button("☁️ Manual Cloud Sync"):
                if sync_to_gsheet(): st.success("Cloud Backup Successful!")
                else: st.error("Cloud Backup Failed.")
        
        excel_data = get_data_as_excel(st.session_state["username"], st.session_state["role"])
        if excel_data:
            st.download_button(label="📥 Download Excel Report", data=excel_data, file_name="export.xlsx")

    # --- Main Content with Tabs ---
    tab_list = ["📝 Submission Form", "🔍 View Submissions", "📊 Dashboard", "🕵️ Audit Logs"]
    if st.session_state["role"] == "admin":
        tab_list.append("🔄 Sync Manager")
        tab_list.append("👤 User Management")

    tabs = st.tabs(tab_list)
    with tabs[0]:
        st.title("Data Submission Form")
        with st.form("data_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                client, brm = st.text_input("Client"), st.text_input("BRM")
            with col2:
                lob = st.text_input("LOB")
            with st.container(border=True):
                st.markdown("### Details")
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    data_a, data_b = st.text_input("DataA"), st.text_input("DataB")
                with d_col2:
                    data_c, data_d = st.text_input("DataC"), st.text_input("DataD")
            
            if st.form_submit_button("Submit Data"):
                if not client: st.warning("Client is required.")
                else:
                    form_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Client": client, "BRM": brm, "LOB": lob,
                        "DataA": data_a, "DataB": data_b, "DataC": data_c, "DataD": data_d
                    }
                    if save_to_db(form_data):
                        st.success("Successfully saved!")
                        st.rerun()

    with tabs[1]:
        st.title("Submissions Viewer")
        try:
            conn = sqlite3.connect(DB_FILE)
            if st.session_state["role"] == "admin":
                query = f"SELECT * FROM {TABLE_NAME} ORDER BY id DESC"
                params = ()
            else:
                query = f"SELECT * FROM {TABLE_NAME} WHERE submitted_by = ? ORDER BY id DESC"
                params = (st.session_state["username"],)
            
            df_all = pd.read_sql_query(query, conn, params=params)
            conn.close()
            
            if not df_all.empty:
                f_col1, f_col2 = st.columns(2)
                with f_col1: filter_client = st.text_input("Search Client", key="search_client")
                with f_col2: filter_brm = st.text_input("Search BRM", key="search_brm")

                df_filtered = df_all.copy()
                if filter_client:
                    df_filtered = df_filtered[df_filtered['client'].str.contains(filter_client, case=False, na=False)]
                if filter_brm:
                    df_filtered = df_filtered[df_filtered['brm'].str.contains(filter_brm, case=False, na=False)]

                st.write(f"Found {len(df_filtered)} records")
                
                h_col1, h_col2, h_col3, h_col4 = st.columns([2.5, 2.5, 1.5, 1.5])
                with h_col1: st.markdown("**Client**")
                with h_col2: st.markdown("**BRM**")
                with h_col3: st.markdown("**LOB**")
                with h_col4: st.markdown("**Actions**")
                st.divider()

                for _, row in df_filtered.iterrows():
                    r_col1, r_col2, r_col3, r_col4 = st.columns([2.5, 2.5, 1.5, 1.5])
                    with r_col1: st.write(row['client'])
                    with r_col2: st.write(row['brm'])
                    with r_col3: st.write(row['lob'])
                    with r_col4:
                        btn_col1, btn_col2, btn_col3 = st.columns(3)
                        with btn_col1:
                            if st.button("👁️", key=f"view_{row['id']}"): view_details_dialog(row)
                        with btn_col2:
                            if st.button("✏️", key=f"edit_{row['id']}"): edit_submission_dialog(row)
                        with btn_col3:
                            if st.button("🗑️", key=f"del_{row['id']}"): delete_submission_dialog(row['id'])
                    st.divider()
            else:
                st.info("No data found.")
        except Exception as e:
            st.error(f"Viewer Error: {e}")

    with tabs[2]:
        display_dashboard()

    with tabs[3]:
        if st.session_state["role"] == "admin":
            display_audit_logs()
        else:
            st.warning("Only administrators can view audit logs.")

    if st.session_state["role"] == "admin":
        with tabs[4]:
            display_sync_manager()
        with tabs[5]:
            display_user_management()

if __name__ == "__main__":
    main()
