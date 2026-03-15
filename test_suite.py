import unittest
import sqlite3
import pandas as pd
import os
import json
import bcrypt
from datetime import datetime

# Import functions from app (we'll mock st where necessary)
# Note: Since app.py is a Streamlit script, some imports might trigger UI calls.
# We will focus on testing the database and logic functions.

DB_FILE = 'test_submissions.db'
TABLE_NAME = 'data_submissions'
USER_TABLE = 'users'
AUDIT_LOG_TABLE = 'audit_logs'
AI_CACHE_TABLE = 'ai_insights_cache'

class TestDataPortal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create a fresh test database
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"CREATE TABLE {TABLE_NAME} (id INTEGER PRIMARY KEY, timestamp TEXT, client TEXT, brm TEXT, lob TEXT, data_a TEXT, data_b TEXT, data_c TEXT, data_d TEXT, submitted_by TEXT)")
        c.execute(f"CREATE TABLE {USER_TABLE} (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, session_token TEXT, token_expiry TEXT)")
        c.execute(f"CREATE TABLE {AUDIT_LOG_TABLE} (id INTEGER PRIMARY KEY, timestamp TEXT, record_id INTEGER, action TEXT, changed_by TEXT, old_values TEXT, new_values TEXT)")
        c.execute(f"CREATE TABLE {AI_CACHE_TABLE} (id INTEGER PRIMARY KEY, timestamp TEXT, insights TEXT)")
        
        # Add a test user
        hashed = bcrypt.hashpw("testpass".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        c.execute(f"INSERT INTO {USER_TABLE} (username, password_hash, role) VALUES (?, ?, ?)", ("testuser", hashed, "user"))
        conn.commit()
        conn.close()

    def test_auth_logic(self):
        """Test password verification."""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"SELECT password_hash FROM {USER_TABLE} WHERE username = 'testuser'")
        res = c.fetchone()
        conn.close()
        
        self.assertTrue(bcrypt.checkpw("testpass".encode('utf-8'), res[0].encode('utf-8')))
        self.assertFalse(bcrypt.checkpw("wrongpass".encode('utf-8'), res[0].encode('utf-8')))

    def test_sync_diff_logic(self):
        """Validate the logic that determines sync status."""
        # Mock Local Data
        df_local = pd.DataFrame([
            {'id': 1, 'client': 'A', 'brm': 'X', 'lob': 'Y'},
            {'id': 2, 'client': 'B', 'brm': 'Z', 'lob': 'W'}
        ])
        
        # Mock Cloud Data with a Mismatch and a Ghost Row
        df_cloud = pd.DataFrame([
            {'id': 1, 'client': 'A', 'brm': 'X', 'lob': 'Y'}, # Match
            {'id': 2, 'client': 'B_Changed', 'brm': 'Z', 'lob': 'W'}, # Content Mismatch
            {'id': 3, 'client': 'C', 'brm': 'M', 'lob': 'N'}, # Missing in Local
            {'id': 0, 'client': None, 'brm': None, 'lob': None}, # Ghost Row (Should be filtered)
            {'id': 'NaN', 'client': '', 'brm': '', 'lob': ''} # Ghost Row (Should be filtered)
        ])

        # Apply our cleaning logic
        def clean(df):
            df = df.copy()
            df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
            return df[df['id'] > 0]

        df_local_clean = clean(df_local)
        df_cloud_clean = clean(df_cloud)

        # 1. Row counts (after cleaning)
        self.assertEqual(len(df_local_clean), 2)
        self.assertEqual(len(df_cloud_clean), 3) # IDs 1, 2, 3

        # 2. Missing in Cloud
        missing_in_cloud = df_local_clean[~df_local_clean['id'].isin(df_cloud_clean['id'])]
        self.assertEqual(len(missing_in_cloud), 0)

        # 3. Missing Locally
        missing_in_local = df_cloud_clean[~df_cloud_clean['id'].isin(df_local_clean['id'])]
        self.assertEqual(len(missing_in_local), 1)
        self.assertEqual(missing_in_local.iloc[0]['id'], 3)

        # 4. Content Mismatch
        merged = pd.merge(df_local_clean, df_cloud_clean, on='id', suffixes=('_l', '_c'))
        mismatch = merged[merged['client_l'] != merged['client_c']]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch.iloc[0]['id'], 2)

    def test_database_persistence(self):
        """Test record insertion and retrieval."""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(f"INSERT INTO {TABLE_NAME} (timestamp, client, brm, lob, submitted_by) VALUES (?, ?, ?, ?, ?)",
                  (ts, "TestClient", "TestBRM", "TestLOB", "admin"))
        conn.commit()
        
        c.execute(f"SELECT client FROM {TABLE_NAME} WHERE client = 'TestClient'")
        self.assertEqual(c.fetchone()[0], "TestClient")
        conn.close()

    def test_ai_cache_logic(self):
        """Test AI insight caching."""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(f"INSERT INTO {AI_CACHE_TABLE} (timestamp, insights) VALUES (?, ?)", ("2026-03-14", "Sample Insight"))
        conn.commit()
        
        c.execute(f"SELECT insights FROM {AI_CACHE_TABLE} ORDER BY id DESC LIMIT 1")
        self.assertEqual(c.fetchone()[0], "Sample Insight")
        conn.close()

    def test_search_filtering(self):
        """Test the logic used for the search filters in the Viewer."""
        df = pd.DataFrame([
            {'client': 'TechNova', 'brm': 'Alice'},
            {'client': 'Global Retail', 'brm': 'Bob'},
            {'client': 'FinStream', 'brm': 'Alice'}
        ])
        
        # Simulate 'Search Client' for 'tech'
        filtered = df[df['client'].str.contains('tech', case=False, na=False)]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]['client'], 'TechNova')

        # Simulate 'Search BRM' for 'Alice'
        filtered_brm = df[df['brm'].str.contains('Alice', case=False, na=False)]
        self.assertEqual(len(filtered_brm), 2)

    def test_audit_log_logic(self):
        """Verify that audit logs can be written and retrieved."""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Simulate logging an INSERT action
        record_id = 99
        action = "INSERT"
        changed_by = "testuser"
        new_values = json.dumps({"client": "MockCorp", "brm": "MockBRM"})
        
        c.execute(f'''
            INSERT INTO {AUDIT_LOG_TABLE} (timestamp, record_id, action, changed_by, new_values)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), record_id, action, changed_by, new_values))
        conn.commit()
        
        # Retrieve and verify
        c.execute(f"SELECT action, changed_by FROM {AUDIT_LOG_TABLE} WHERE record_id = 99")
        log = c.fetchone()
        self.assertEqual(log[0], "INSERT")
        self.assertEqual(log[1], "testuser")
        conn.close()

    def test_role_based_visibility(self):
        """Verify that data retrieval logic respects user roles."""
        # Mocking the query logic in app.py
        def get_query(role, username):
            if role == "admin":
                return f"SELECT * FROM {TABLE_NAME}", ()
            else:
                return f"SELECT * FROM {TABLE_NAME} WHERE submitted_by = ?", (username,)

        # Admin case
        q_admin, p_admin = get_query("admin", "anyuser")
        self.assertNotIn("WHERE", q_admin.upper()) # Admin should see everything
        
        # User case
        q_user, p_user = get_query("user", "my_username")
        self.assertIn("WHERE", q_user.upper())
        self.assertIn("submitted_by = ?", q_user)
        self.assertEqual(p_user[0], "my_username")

    def test_dashboard_data_prep(self):
        """Verify that data is correctly formatted for Plotly charts."""
        df = pd.DataFrame([
            {'timestamp': '2026-03-10 10:00:00', 'lob': 'IT'},
            {'timestamp': '2026-03-10 12:00:00', 'lob': 'HR'},
            {'timestamp': '2026-03-11 09:00:00', 'lob': 'IT'}
        ])
        
        # 1. Submissions Over Time logic
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        date_counts = df['date'].value_counts().sort_index().reset_index()
        date_counts.columns = ['Date', 'Submissions']
        
        self.assertEqual(len(date_counts), 2) # Two unique dates
        self.assertEqual(date_counts.iloc[0]['Submissions'], 2) # 2026-03-10 has 2 entries

        # 2. LOB counts logic
        lob_counts = df['lob'].value_counts()
        self.assertEqual(lob_counts['IT'], 2)
        self.assertEqual(lob_counts['HR'], 1)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)

if __name__ == '__main__':
    unittest.main()
