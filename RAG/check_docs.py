import mysql.connector
from config import Config

conn = mysql.connector.connect(
    host=Config.DB_HOST,
    port=Config.DB_PORT,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
    database=Config.DB_NAME,
)
cur = conn.cursor(dictionary=True)

cur.execute("SELECT COUNT(*) as cnt FROM document")
print("Total:", cur.fetchone())

cur.execute(
    """
    SELECT COUNT(*) as cnt FROM document
    WHERE is_deleted = FALSE
      AND (stored_file_name LIKE 'doc_%' OR stored_file_name LIKE 'common_%')
    """
)
print("Filtered:", cur.fetchone())

cur.execute(
    "SELECT doc_id, original_file_name, stored_file_name, is_deleted FROM document LIMIT 10"
)
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
