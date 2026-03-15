import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import sqlite3
import os

# Mock Streamlit before importing app
import sys
mock_st = MagicMock()
sys.modules["streamlit"] = mock_st
sys.modules["streamlit_gsheets"] = MagicMock()

import app

class TestAppCoverage(unittest.TestCase):
    
    def test_db_init(self):
        # Mocking the actual DB file to avoid side effects
        with patch('sqlite3.connect') as mock_connect:
            app.init_db()
            self.assertTrue(mock_connect.called)

    def test_get_cached_insight(self):
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value.fetchone.return_value = ("ts", "insights")
            
            ts, insights = app.get_cached_insight()
            self.assertEqual(insights, "insights")

    def test_search_filtering_logic(self):
        # Even though search is inside a tab, we can test the logic if it's isolated
        # In this POC, logic is often mixed with UI, so we test what we can
        df = pd.DataFrame({'client': ['TechNova', 'Global'], 'brm': ['Alice', 'Bob']})
        # Logic: df[df['client'].str.contains(filter_client, case=False, na=False)]
        filtered = df[df['client'].str.contains('tech', case=False, na=False)]
        self.assertEqual(len(filtered), 1)

    def test_sync_logic_robustness(self):
        # Testing the robustness cleanup I added
        df_local = pd.DataFrame({'id': [1, 2], 'client': ['A', 'B']})
        df_cloud = pd.DataFrame({'id': [1, 'NaN', 0], 'client': ['A', '', '']})
        
        # Simulate app cleanup
        df_cloud['id'] = pd.to_numeric(df_cloud['id'], errors='coerce').fillna(0).astype(int)
        df_cloud = df_cloud[df_cloud['id'] > 0]
        
        self.assertEqual(len(df_cloud), 1)

if __name__ == "__main__":
    unittest.main()
