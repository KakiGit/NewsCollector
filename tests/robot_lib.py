"""Robot Framework test library for NewsCollector system tests."""

import os
import time

import psycopg
import requests
from robot.api import logger
from robot.api.deco import keyword


class NewsCollectorLibrary:
    """Library for NewsCollector system tests."""

    def __init__(self):
        self.db_conn = None
        self.base_url = os.environ.get("NEWSCOLLECTOR_TEST_BASE_URL", "http://localhost:8000")
        self.db_host = os.environ.get("NEWSCOLLECTOR_TEST_DB_HOST", "localhost")
        self.db_port = int(os.environ.get("NEWSCOLLECTOR_TEST_DB_PORT", "5432"))
        self.db_name = os.environ.get("NEWSCOLLECTOR_TEST_DB_NAME", "newscollector")
        self.db_user = os.environ.get("NEWSCOLLECTOR_TEST_DB_USER", "newscollector")
        self.db_password = os.environ.get("NEWSCOLLECTOR_TEST_DB_PASSWORD", "localdevpass")

    @keyword
    def connect_to_database(self):
        """Connect to the PostgreSQL database."""
        try:
            dsn = f"host={self.db_host} port={self.db_port} dbname={self.db_name} user={self.db_user} password={self.db_password}"
            self.db_conn = psycopg.connect(dsn)
            logger.info(f"Connected to database {self.db_name} on {self.db_host}:{self.db_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    @keyword
    def execute_sql(self, sql_query: str):
        """Execute a SQL query and return results."""
        if not self.db_conn:
            self.connect_to_database()

        cursor = self.db_conn.cursor()
        cursor.execute(sql_query)

        # Check if query returns results (SELECT) or just executes (INSERT/UPDATE/DELETE)
        try:
            results = cursor.fetchall()
            # If it's a SELECT with results, return them
            if results:
                column_names = [desc[0] for desc in cursor.description]
                return [dict(zip(column_names, row)) for row in results]
            # For INSERT/UPDATE/DELETE or SELECT without results
            self.db_conn.commit()
            return cursor.rowcount
        except psycopg.ProgrammingError:
            # No results to fetch (e.g., INSERT, UPDATE, DELETE)
            self.db_conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()

    @keyword
    def close_database_connection(self):
        """Close the database connection."""
        if self.db_conn:
            self.db_conn.close()
            self.db_conn = None
            logger.info("Database connection closed")

    @keyword
    def wait_for_server_ready(self, max_retries: int = 30):
        """Wait for the web server to be ready."""
        for i in range(max_retries):
            try:
                response = requests.get(f"{self.base_url}/", timeout=2)
                if response.status_code == 200:
                    logger.info(f"Server is ready at {self.base_url}")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        raise AssertionError(f"Server did not become ready within {max_retries} seconds")

    @keyword
    def start_web_server(self):
        """Start the web server in background (for external use)."""
        # This is typically handled externally, but we provide a check
        return self.wait_for_server_ready(max_retries=5)

    @keyword
    def get_api(self, endpoint: str, params: dict = None):
        """Make a GET request to the API and return the response."""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, params=params)
        return response


# Create a singleton instance for Robot Framework to use
_instance = NewsCollectorLibrary()


# Module-level keywords that use the singleton instance
@keyword
def connect_to_database():
    """Keyword wrapper for connect_to_database."""
    return _instance.connect_to_database()


@keyword
def execute_sql_query(sql: str):
    """Keyword wrapper for execute_sql."""
    return _instance.execute_sql(sql)


@keyword
def close_database_connection():
    """Keyword wrapper for close_database_connection."""
    return _instance.close_database_connection()


@keyword
def wait_for_server_ready(max_retries: int = 30):
    """Keyword wrapper for wait_for_server_ready."""
    return _instance.wait_for_server_ready(max_retries)


@keyword
def start_web_server():
    """Keyword wrapper for start_web_server."""
    return _instance.start_web_server()


@keyword
def get_api(endpoint: str, params: dict = None):
    """Keyword wrapper for get_api."""
    return _instance.get_api(endpoint, params)
