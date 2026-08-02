"""Legacy entry point for a current valuation snapshot."""

import os
import sys
import sqlite3
import pandas as pd

sys.path.append(os.path.dirname(__file__))
from ashare_factor_pipeline import DB_PATH


class MungerStockScreener:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def screen_wonderful_companies(self, min_roe=15.0, max_pe=60.0):
        """Return a valuation filter without claiming fundamental quality."""
        with self.get_connection() as conn:
            query = """
            SELECT symbol, name, price, pe_ttm, pb, total_mv, circ_mv 
            FROM stock_basic 
            WHERE pe_ttm > 0 AND pe_ttm <= ? AND pb > 0
                  AND total_mv >= 10000000000
                  AND UPPER(name) NOT LIKE '%ST%'
                  AND name NOT LIKE '%退%'
            ORDER BY total_mv DESC
            """
            result = pd.read_sql_query(query, conn, params=(max_pe,))
        result["fundamental_status"] = "UNKNOWN"
        result["data_scope"] = "CURRENT_VALUATION_SNAPSHOT"
        return result


if __name__ == "__main__":
    screener = MungerStockScreener()
    good_stocks = screener.screen_wonderful_companies()
