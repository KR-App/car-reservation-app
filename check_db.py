import sqlite3
conn = sqlite3.connect("car_reservations.db")
cur = conn.cursor()
cur.execute("SELECT * FROM reservations")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
