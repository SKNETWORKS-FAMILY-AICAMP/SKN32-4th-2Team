import mysql.connector
from mysql.connector import Error
from config import Config
import os

def insert_sample_data():
    try:
        connection = mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        
        cursor = connection.cursor()
        
        # SQL 파일 경로
        data_file = os.path.join(os.path.dirname(__file__), 'sql', 'rag_document.sql')
        
        if os.path.exists(data_file):
            with open(data_file, 'r', encoding='utf-8') as f:
                sql_script = f.read()
                
            # 여러 INSERT 문을 분리해서 실행
            statements = sql_script.split(';')
            for statement in statements:
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    try:
                        cursor.execute(statement)
                        connection.commit()
                    except Error as e:
                        print(f"Warning: {e}")
                        connection.rollback()
            print("Sample data inserted successfully")
            
            # 확인
            cursor.execute("SELECT COUNT(*) FROM document")
            count = cursor.fetchone()[0]
            print(f"Total documents: {count}")
            
        else:
            print(f"SQL file not found: {data_file}")
        
        cursor.close()
        connection.close()
        
    except Error as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    insert_sample_data()
