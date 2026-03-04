import sqlite3

con = sqlite3.connect(r"instance\app.db")
cur = con.cursor()

cur.execute("""
DELETE FROM job
WHERE title IS NULL OR trim(title) = ''
""")
con.commit()
print("✅ Removidas:", cur.rowcount)
con.close()
