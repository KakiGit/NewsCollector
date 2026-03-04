"""Robot Framework test library for NewsCollector system tests."""

import os
import subprocess
import time
from urllib.parse import urlparse, unquote

import psycopg
import requests
import yaml
from robot.api import logger
from robot.api.deco import keyword
from playwright.sync_api import sync_playwright


def load_db_config():
    """Load database configuration from config.yaml."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            if config and 'storage' in config and 'database_url' in config['storage']:
                return config['storage']['database_url']
    return None


class NewsCollectorLibrary:
    """Library for NewsCollector system tests."""

    def __init__(self):
        self.db_conn = None
        self.server_process = None
        self.base_url = os.environ.get("NEWSCOLLECTOR_TEST_BASE_URL", "http://localhost:8000")

        # Try to load database config from config.yaml first
        db_url = load_db_config()
        if db_url:
            parsed = urlparse(db_url)
            self.db_host = parsed.hostname
            self.db_port = parsed.port
            self.db_name = parsed.path.lstrip('/')
            self.db_user = parsed.username
            self.db_password = unquote(parsed.password) if parsed.password else None
        else:
            # Default values when config is not available
            self.db_host = "localhost"
            self.db_port = 5432
            self.db_name = "newscollector"
            self.db_user = "newscollector"
            self.db_password = "localdevpass"

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
    def start_web_server_on_port(self, port: int = 8090):
        """Start the web server on a specific port."""
        env = os.environ.copy()
        env["NEWSCOLLECTOR_TEST_BASE_URL"] = f"http://localhost:{port}"
        self.base_url = f"http://localhost:{port}"

        # Start the server process
        self.server_process = subprocess.Popen(
            ["python3", "-m", "newscollector", "serve", "--port", str(port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(f"Started web server on port {port} with PID {self.server_process.pid}")

        # Wait for server to be ready
        return self.wait_for_server_ready(max_retries=30)

    @keyword
    def stop_web_server(self):
        """Stop the web server process."""
        if hasattr(self, 'server_process') and self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            logger.info("Web server stopped")
            self.server_process = None

    @keyword
    def get_api(self, endpoint: str, params: dict = None):
        """Make a GET request to the API and return the response."""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, params=params)
        return response


class PlaywrightLibrary:
    """Library for Robot Framework UI tests using Playwright."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        self.base_url = os.environ.get("NEWSCOLLECTOR_TEST_BASE_URL", "http://localhost:8090")

    @keyword
    def open_browser(self, browser_type: str = "chromium", headless: bool = True):
        """Open a browser instance using Playwright.

        Args:
            browser_type: One of chromium, firefox, or webkit
            headless: Whether to run browser in headless mode
        """
        self.playwright = sync_playwright().start()
        browser_launcher = getattr(self.playwright, browser_type)
        self.browser = browser_launcher.launch(headless=headless)
        self.page = self.browser.new_page()
        logger.info(f"Opened {browser_type} browser (headless={headless})")

    @keyword
    def close_browser(self):
        """Close the browser instance."""
        if self.page:
            self.page.close()
            self.page = None
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
        logger.info("Closed browser")

    @keyword
    def go_to_url(self, url: str = None):
        """Navigate to a URL.

        Args:
            url: URL to navigate to. If None, uses base_url from config.
        """
        target = url or self.base_url
        self.page.goto(target)
        logger.info(f"Navigated to {target}")

    @keyword
    def click_element(self, selector: str):
        """Click an element by CSS selector or text.

        Args:
            selector: CSS selector or text to click
        """
        self.page.click(selector)
        logger.info(f"Clicked element: {selector}")

    @keyword
    def fill_input(self, selector: str, value: str):
        """Fill an input field.

        Args:
            selector: CSS selector for the input
            value: Value to fill
        """
        self.page.fill(selector, value)
        logger.info(f"Filled input {selector} with: {value}")

    @keyword
    def select_option(self, selector: str, value: str):
        """Select an option from a dropdown.

        Args:
            selector: CSS selector for the select element
            value: Value to select
        """
        self.page.select_option(selector, value)
        logger.info(f"Selected option {value} in {selector}")

    @keyword
    def get_text(self, selector: str) -> str:
        """Get text content of an element.

        Args:
            selector: CSS selector for the element

        Returns:
            Text content of the element
        """
        return self.page.locator(selector).text_content()

    @keyword
    def get_element_count(self, selector: str) -> int:
        """Get count of elements matching a selector.

        Args:
            selector: CSS selector

        Returns:
            Number of matching elements
        """
        return self.page.locator(selector).count()

    @keyword
    def element_should_be_visible(self, selector: str):
        """Assert that an element is visible.

        Args:
            selector: CSS selector for the element
        """
        assert self.page.locator(selector).is_visible(), f"Element {selector} should be visible"

    @keyword
    def element_should_contain(self, selector: str, text: str):
        """Assert that an element contains specific text.

        Args:
            selector: CSS selector for the element
            text: Expected text content
        """
        content = self.page.locator(selector).text_content()
        assert text in content, f"Element {selector} should contain '{text}', got '{content}'"

    @keyword
    def wait_for_selector(self, selector: str, timeout: int = 5000):
        """Wait for an element to appear.

        Args:
            selector: CSS selector for the element
            timeout: Timeout in milliseconds
        """
        self.page.wait_for_selector(selector, timeout=timeout)
        logger.info(f"Element {selector} is available")

    @keyword
    def wait_for_load_state(self, state: str = "networkidle"):
        """Wait for page to load.

        Args:
            state: One of load, domcontentloaded, networkidle
        """
        self.page.wait_for_load_state(state)
        logger.info(f"Page loaded: {state}")

    @keyword
    def get_page_title(self) -> str:
        """Get the page title.

        Returns:
            Page title
        """
        return self.page.title()

    @keyword
    def screenshot(self, path: str = None):
        """Take a screenshot.

        Args:
            path: Path to save screenshot. If None, saves to screenshot.png
        """
        self.page.screenshot(path=path or "screenshot.png")
        logger.info(f"Screenshot saved to {path or 'screenshot.png'}")


# Create singleton instance for Playwright
_playwright_instance = PlaywrightLibrary()


# Module-level keywords for Playwright
@keyword
def open_browser(browser_type: str = "chromium", headless: bool = True):
    """Keyword wrapper for open_browser."""
    return _playwright_instance.open_browser(browser_type, headless)


@keyword
def close_browser():
    """Keyword wrapper for close_browser."""
    return _playwright_instance.close_browser()


@keyword
def go_to_url(url: str = None):
    """Keyword wrapper for go_to_url."""
    return _playwright_instance.go_to_url(url)


@keyword
def click_element(selector: str):
    """Keyword wrapper for click_element."""
    return _playwright_instance.click_element(selector)


@keyword
def fill_input(selector: str, value: str):
    """Keyword wrapper for fill_input."""
    return _playwright_instance.fill_input(selector, value)


@keyword
def select_option(selector: str, value: str):
    """Keyword wrapper for select_option."""
    return _playwright_instance.select_option(selector, value)


@keyword
def get_text(selector: str):
    """Keyword wrapper for get_text."""
    return _playwright_instance.get_text(selector)


@keyword
def get_element_count(selector: str):
    """Keyword wrapper for get_element_count."""
    return _playwright_instance.get_element_count(selector)


@keyword
def element_should_be_visible(selector: str):
    """Keyword wrapper for element_should_be_visible."""
    return _playwright_instance.element_should_be_visible(selector)


@keyword
def element_should_contain(selector: str, text: str):
    """Keyword wrapper for element_should_contain."""
    return _playwright_instance.element_should_contain(selector, text)


@keyword
def wait_for_selector(selector: str, timeout: int = 5000):
    """Keyword wrapper for wait_for_selector."""
    return _playwright_instance.wait_for_selector(selector, timeout)


@keyword
def wait_for_load_state(state: str = "networkidle"):
    """Keyword wrapper for wait_for_load_state."""
    return _playwright_instance.wait_for_load_state(state)


@keyword
def get_page_title():
    """Keyword wrapper for get_page_title."""
    return _playwright_instance.get_page_title()


@keyword
def screenshot(path: str = None):
    """Keyword wrapper for screenshot."""
    return _playwright_instance.screenshot(path)


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
def start_web_server_on_port(port: int = 8090):
    """Keyword wrapper for start_web_server_on_port."""
    return _instance.start_web_server_on_port(port)


@keyword
def stop_web_server():
    """Keyword wrapper for stop_web_server."""
    return _instance.stop_web_server()


@keyword
def get_api(endpoint: str, params: dict = None):
    """Keyword wrapper for get_api."""
    return _instance.get_api(endpoint, params)
