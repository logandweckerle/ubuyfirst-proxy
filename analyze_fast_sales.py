"""Analyze fast sales data for training opportunities."""
import sqlite3
import json
from pathlib import Path

db_path = Path(__file__).parent / "item_tracking.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=== FAST SALES BY CATEGORY ===")
cursor.execute("""
    SELECT category, COUNT(*), AVG(price), AVG(time_to_sell_minutes)
    FROM tracked_items
    WHERE is_fast_sale = 1 AND category != ''
    GROUP BY category
    ORDER BY COUNT(*) DESC
    LIMIT 15
""")
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]} sales, avg ${row[2]:.0f}, avg {row[3]:.1f} min")

print("\n=== FAST SALES BY RECOMMENDATION ===")
cursor.execute("""
    SELECT recommendation, COUNT(*)
    FROM tracked_items
    WHERE is_fast_sale = 1
    GROUP BY recommendation
    ORDER BY COUNT(*) DESC
""")
for row in cursor.fetchall():
    print(f"{row[0] or '(none)'}: {row[1]}")

print("\n=== HOW MANY FAST SALES HAVE FULL DATA? ===")
cursor.execute("""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN analysis_result_json IS NOT NULL THEN 1 ELSE 0 END) as with_analysis,
        SUM(CASE WHEN original_data_json IS NOT NULL THEN 1 ELSE 0 END) as with_original
    FROM tracked_items
    WHERE is_fast_sale = 1
""")
row = cursor.fetchone()
print(f"Total fast sales: {row[0]}")
print(f"With analysis data: {row[1]} ({100*row[1]/row[0]:.1f}%)")
print(f"With original data: {row[2]} ({100*row[2]/row[0]:.1f}%)")

print("\n=== SAMPLE FAST SALES (PASS recommendations that sold fast = MISSED OPPORTUNITIES) ===")
cursor.execute("""
    SELECT title, price, category, recommendation, time_to_sell_minutes, seller_name
    FROM tracked_items
    WHERE is_fast_sale = 1
    AND recommendation LIKE '%PASS%'
    ORDER BY sold_time DESC
    LIMIT 15
""")
for row in cursor.fetchall():
    title = (row[0] or "")[:55].replace("+", " ")
    rec = row[3] or "?"
    seller = (row[5] or "")[:20].replace("+", " ")
    print(f"${row[1]:.0f} | {row[2]} | {row[4]:.1f}m | {seller}")
    print(f"  {title}")

print("\n=== GOLD/SILVER FAST SALES WE PASSED ON ===")
cursor.execute("""
    SELECT title, price, category, time_to_sell_minutes, seller_name
    FROM tracked_items
    WHERE is_fast_sale = 1
    AND category IN ('gold', 'silver')
    AND (recommendation LIKE '%PASS%' OR recommendation IS NULL)
    ORDER BY sold_time DESC
    LIMIT 20
""")
count = 0
for row in cursor.fetchall():
    count += 1
    title = (row[0] or "")[:55].replace("+", " ")
    seller = (row[4] or "")[:20].replace("+", " ")
    print(f"${row[1]:.0f} | {row[2]} | {row[3]:.1f}m | {seller}")
    print(f"  {title}")
print(f"\nTotal gold/silver PASS that sold fast: {count}")

conn.close()
