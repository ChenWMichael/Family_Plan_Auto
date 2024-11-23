import sqlite3

db_path = r"C:\Users\chenw\Discord_Bots\Family_Plan_Auto\data.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Recreate the users table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        duration INTEGER NOT NULL,
        cost REAL NOT NULL,
        paid BOOLEAN DEFAULT 0,
        reminder_sent BOOLEAN DEFAULT 0
    );
""")

# Recreate the plan_cost table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS plan_cost (
        id INTEGER PRIMARY KEY,
        monthly_cost REAL NOT NULL,
        effective_date TEXT NOT NULL
    );
""")

# Insert initial plan cost
cursor.execute(
    "INSERT OR IGNORE INTO plan_cost (id, monthly_cost, effective_date) VALUES (1, 20.00, '2024-01-01');")

conn.commit()
conn.close()
print("Database recreated successfully.")
