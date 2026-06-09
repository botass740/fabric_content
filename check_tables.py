import sqlite3
conn = sqlite3.connect('data/app.sqlite3')
print([table[0] for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
conn.close()