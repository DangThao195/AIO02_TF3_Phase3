import sqlite3, os
p = os.path.join('server-test','shopping.db')
print('exists', os.path.exists(p))
conn = sqlite3.connect(p)
cur = conn.cursor()
print(cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
print(cur.execute("SELECT COUNT(*) FROM products").fetchone())
print(cur.execute("SELECT id, name, categories, price_units FROM products LIMIT 5").fetchall())
conn.close()
