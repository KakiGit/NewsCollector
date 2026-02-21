# Python 3.12 + Playwright with Chromium (for Instagram, RedNote, Douyin scraping)
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

# Copy application
COPY config/ config/
COPY newscollector/ newscollector/

EXPOSE 8000

# Default: run web UI (bind to 0.0.0.0 so it's reachable from the host).
# Override to run CLI, e.g.:
#   docker run ... python -m newscollector collect --all
#   docker run ... python -m newscollector list-platforms
CMD ["python", "-m", "newscollector", "serve", "--host", "0.0.0.0"]
