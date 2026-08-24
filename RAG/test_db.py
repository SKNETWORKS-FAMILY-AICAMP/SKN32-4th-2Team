import mysql.connector
from mysql.connector import Error
from config import Config

def test_db():
    try:
        connection = mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        
        cursor = connection.cursor(dictionary=True)
        
        # 테이블 존재 확인
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        print("Tables:", tables)
        
        # document 테이블 데이터 확인
        cursor.execute("SELECT * FROM document")
        documents = cursor.fetchall()
        print(f"Document count: {len(documents)}")
        print("Documents:", documents)
        
        # 수동으로 하나의 데이터 삽입 테스트
        test_insert = """
            INSERT INTO document (original_file_name, stored_file_name, file_path, is_loaded, loaded_at)
            VALUES ('test.pdf', 'test.pdf', 'res/pdf/test.pdf', 1, NOW())
        """
        cursor.execute(test_insert)
        connection.commit()
        print("Test insert successful")
        
        # 다시 확인
        cursor.execute("SELECT * FROM document")
        documents = cursor.fetchall()
        print(f"After insert - Document count: {len(documents)}")
        
        cursor.close()
        connection.close()
        
    except Error as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_db()
