import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import random

# Configuration
DB_FILE = 'submissions.db'
TABLE_NAME = 'data_submissions'

clients = ['TechNova Solutions', 'Global Retail Inc', 'Apex Healthcare', 'FinStream Bank', 'EcoEnergy Corp']
brms = ['Alice Johnson', 'Bob Smith', 'Charlie Davis', 'Diana Prince']
lobs = ['IT Services', 'Customer Experience', 'Operations', 'Strategic Finance', 'Marketing']
users = ['admin', 'user1', 'user2']

data_templates = [
    {"a": "High", "b": "$50,000", "c": "In Progress", "d": "No blockers"},
    {"a": "Medium", "b": "$12,000", "c": "Completed", "d": "Positive feedback"},
    {"a": "Low", "b": "$5,000", "c": "On Hold", "d": "Waiting for approval"},
    {"a": "Critical", "b": "$120,000", "c": "Delayed", "d": "Resource shortage"},
    {"a": "Low", "b": "$2,500", "c": "Planned", "d": "Initial phase"},
]

def clear_existing_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"DELETE FROM {TABLE_NAME}")
    # Reset autoincrement
    c.execute("DELETE FROM sqlite_sequence WHERE name=?", (TABLE_NAME,))
    conn.commit()
    conn.close()
    print("🗑️ Existing local data cleared.")

def generate_mock_data(num_records=25, append=False):
    if not append:
        clear_existing_data()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            client TEXT, brm TEXT, lob TEXT,
            data_a TEXT, data_b TEXT, data_c TEXT, data_d TEXT,
            submitted_by TEXT
        )
    ''')

    print(f"Generating {num_records} mock records...")
    
    for i in range(num_records):
        days_ago = random.randint(0, 30)
        hours_ago = random.randint(0, 23)
        ts = (datetime.now() - timedelta(days=days_ago, hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
        
        client = random.choice(clients)
        brm = random.choice(brms)
        lob = random.choice(lobs)
        template = random.choice(data_templates)
        user = random.choice(users)
        
        c.execute(f'''
            INSERT INTO {TABLE_NAME} (timestamp, client, brm, lob, data_a, data_b, data_c, data_d, submitted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts, client, brm, lob, template["a"], template["b"], template["c"], template["d"], user))

    conn.commit()
    conn.close()
    print(f"✅ {num_records} mock records successfully inserted into {DB_FILE}!")

if __name__ == "__main__":
    import sys
    # Default to clearing and generating 25 records
    # Use 'append' as argument to keep existing data
    is_append = 'append' in sys.argv
    generate_mock_data(num_records=25, append=is_append)
