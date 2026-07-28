"""
test_database_summary.py
========================
Unit tests for Task 1 & DB helper functions in database.py
"""

import unittest
from unittest.mock import MagicMock, patch
import database


class TestDatabaseSummary(unittest.TestCase):
    @patch("database.get_db_connection")
    @patch("database.db_pool")
    def test_save_product_summary_executes_upsert(self, mock_pool, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = database.save_product_summary(
            product_id="PROD001",
            summary_text="Great lens cleaning kit.",
            rating_distribution='{"5": 4}',
            review_version="v1_abc",
        )

        self.assertTrue(res)
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO reviews.product_summaries", args[0])
        self.assertEqual(args[1], ("PROD001", "Great lens cleaning kit.", '{"5": 4}', "v1_abc"))
        mock_conn.commit.assert_called_once()
        mock_pool.putconn.assert_called_once_with(mock_conn)

    @patch("database.get_db_connection")
    @patch("database.db_pool")
    def test_fetch_product_summary_from_db_returns_dict(self, mock_pool, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "PROD001",
            "Great lens cleaning kit.",
            '{"5": 4}',
            "v1_abc",
            "2026-07-27 12:00:00",
        )
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        data = database.fetch_product_summary_from_db("PROD001")

        self.assertIsNotNone(data)
        self.assertEqual(data["product_id"], "PROD001")
        self.assertEqual(data["summary_text"], "Great lens cleaning kit.")
        self.assertEqual(data["rating_distribution"], '{"5": 4}')
        self.assertEqual(data["review_version"], "v1_abc")

    @patch("database.get_db_connection")
    @patch("database.db_pool")
    def test_fetch_product_summary_from_db_returns_none_when_empty(self, mock_pool, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        data = database.fetch_product_summary_from_db("NONEXISTENT")
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
