import os

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()


class Database:
    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = os.getenv("DB_PORT", "5432")
        self.database = os.getenv("DB_NAME", "parksight")
        self.user = os.getenv("DB_USER", "postgres")
        self.password = os.getenv("DB_PASSWORD")

    def get_connection(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
        )

    def initialize(self):
        connection = self.get_connection()

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS occupancy_history (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        capacity INTEGER NOT NULL,
                        occupied INTEGER NOT NULL,
                        available INTEGER NOT NULL
                    );
                """)

            connection.commit()

        finally:
            connection.close()

    def save_occupancy(self, capacity, occupied, available):
        connection = self.get_connection()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO occupancy_history
                    (capacity, occupied, available)
                    VALUES (%s, %s, %s);
                    """,
                    (capacity, occupied, available),
                )

            connection.commit()

        finally:
            connection.close()

    def get_history(self, limit=100):
        connection = self.get_connection()

        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, timestamp, capacity, occupied, available
                    FROM occupancy_history
                    ORDER BY timestamp DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )

                return cursor.fetchall()

        finally:
            connection.close()