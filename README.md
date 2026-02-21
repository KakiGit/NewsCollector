# NewsCollector

A Python CLI tool that collects trending news, topics, and events from major news publishers and social media platforms worldwide.

## Supported Platforms

| Platform    | Method             | Auth Required       |
|-------------|--------------------|---------------------|
| News (RSS)  | RSS feeds          | No                  |
| X/Twitter   | X API v2           | Yes (bearer token)  |
| Instagram   | Web scraping       | No (fragile)        |
| RedNote     | Web scraping       | No                  |
| TikTok      | Web scraping       | No                  |
| Weibo       | Public API         | No                  |
| YouTube     | YouTube Data API   | Yes (API key)       |
| Bilibili    | Public API         | No                  |
| Douyin      | Web scraping       | No                  |

## News Sources by Region

- **Europe**: BBC, Reuters, Le Monde, Der Spiegel, El País, ANSA, NOS
- **USA**: CNN, AP News, NPR, New York Times
- **China**: Xinhua, CGTN, South China Morning Post
- **Japan**: NHK World, The Japan Times
- **South Korea**: Yonhap, The Korea Herald
- **India**: Times of India, NDTV, The Hindu
- **Vietnam**: VnExpress, Tuoi Tre News

## Installation

```bash
pip install -r requirements.txt

# Install Playwright browsers (needed for Instagram, RedNote, Douyin scraping)
playwright install chromium
```

## Configuration

Copy the example config and fill in your API keys:

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` with your API keys:

| Platform | Required For | Where to Get |
|----------|--------------|--------------|
| Twitter/X | Trending topics | [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard) |
| YouTube | Trending videos | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| RedNote | RedNote posts | Browser cookies (see config.example.yaml for instructions) |
| AI (optional) | Summaries & labels | OpenAI, MiniMax, Together, or any OpenAI-compatible API |

Configure PostgreSQL storage by setting `storage.database_url` in `config/config.yaml`
or exporting `NEWSCOLLECTOR_DATABASE_URL`.

### AI-First Collection (Optional)

When `ai.ai_base_url`, `ai.ai_model`, and `ai.ai_api_key` are set:

- `rednote`, `tiktok`, and `douyin` try AI-first extraction from platform page HTML.
- If AI extraction returns too few valid items, collectors fall back to existing selector/API logic.
- For collected items with URLs, the collector fetches linked page text and uses AI to summarize/label from page content first.
- If page fetch or AI page summarization fails, it falls back to title/description summarization.

Useful AI toggles in `config/config.yaml`:

- `ai_platform_collection_enabled`
- `ai_platform_min_items_before_fallback`
- `ai_platform_extract_max_items`
- `ai_page_summary_enabled`
- `ai_html_char_limit`, `ai_extract_html_prompt_char_limit`
- `ai_page_html_char_limit`, `ai_page_char_limit`

## Usage

### News Collection

```bash
# Collect from all platforms
python -m newscollector collect --all

# Collect from a specific platform
python -m newscollector collect --platform twitter
python -m newscollector collect --platform news_rss --region europe

# Collect from multiple platforms
python -m newscollector collect --platform twitter --platform youtube --platform weibo

# Filter by topic (e.g. 'financial' for business/finance-only)
python -m newscollector collect --platform news_rss --topic financial

# List available platforms and regions
python -m newscollector list-platforms
```

### Daily Verdicts

```bash
# Generate daily verdicts from collected items (requires AI configuration)
python -m newscollector verdict
python -m newscollector verdict --date 2025-01-15
python -m newscollector verdict --platform twitter --region usa
```

### Web UI

```bash
# Start the web UI to browse collected news items
python -m newscollector serve
python -m newscollector serve --port 8080 --host 0.0.0.0
```

### Financial Reports

```bash
# Collect financial reports for top companies using yfinance
python -m newscollector collect-reports
python -m newscollector collect-reports --region us_300
python -m newscollector collect-reports --region us_300 --region china_300
python -m newscollector collect-reports --delay 0.3

# Collect historical financial data (last N quarters for trend analysis)
python -m newscollector collect-history
python -m newscollector collect-history --region us_300 --periods 8

# Evaluate/re-evaluate financial reports with AI (requires AI configuration)
python -m newscollector evaluate-reports
python -m newscollector evaluate-reports --region us_300 --ticker AAPL
python -m newscollector evaluate-reports --only-missing

# Clean up broken/empty financial reports
python -m newscollector clean-reports
python -m newscollector clean-reports --refetch  # Re-fetch data before removing

# Update company names in config/companies.yaml from yfinance
python -m newscollector update-companies
python -m newscollector update-companies --region us_300 --remove-invalid

# List available regions for financial report collection
python -m newscollector list-regions
```

### Common Options

```bash
# All commands support these common options:
--config, -c       Path to config.yaml file (default: config/config.yaml)
--output, -o       Output directory for JSON files
--verbose, -v      Enable verbose logging
```

## Scripts

### Local Development

| Script | Description |
|--------|-------------|
| `scripts/local-start.sh` | Start NewsCollector locally for testing. Auto-detects podman, docker, or direct host execution. |
| `scripts/local-test.sh` | Run test suite to verify local deployment is working correctly. |
| `scripts/stop.sh` | Stop the NewsCollector service on a remote server. |

### Remote Deployment

| Script | Description |
|--------|-------------|
| `scripts/setup.sh` | Initial setup for remote server. Creates directory structure and sample config. |
| `scripts/deploy.sh` | Deploy NewsCollector container to a remote machine via SSH. Builds image locally and transfers it. |
| `scripts/start.sh` | Start the NewsCollector service on a remote server. |
| `scripts/stop.sh` | Stop the NewsCollector service on a remote server. |
| `scripts/import-data.sh` | Import data to NewsCollector on a remote server via SSH. Supports collected items, reports, and verdicts. |

### Script Usage Examples

```bash
# Local development
./scripts/local-start.sh              # Start with podman/docker (auto-detected)
./scripts/local-start.sh --with-db    # Include PostgreSQL
./scripts/local-start.sh --clean      # Clean up first
./scripts/local-start.sh --rebuild    # Rebuild image
./scripts/local-start.sh --no-container  # Force direct host execution
./scripts/local-test.sh               # Run tests

# Remote deployment
./scripts/setup.sh user@server        # Initial setup on remote
./scripts/deploy.sh user@server        # Deploy to remote
./scripts/start.sh user@server         # Start remote service
./scripts/stop.sh user@server          # Stop remote service
./scripts/import-data.sh user@server  # Import local data to remote
```

## Output

Results are stored in PostgreSQL. Configure `storage.database_url` in
`config/config.yaml` (or set `NEWSCOLLECTOR_DATABASE_URL`) before running.

Each trending item includes:
- `title` — headline or topic name
- `url` — link to the original content
- `source` — publisher or platform name
- `platform` — collector identifier
- `region` — geographic region
- `rank` — position in trending list
- `description` — brief summary
- `summary` — AI-generated summary (when AI is configured)
- `labels` — AI or keyword topic labels
- `heat` — engagement/popularity metric
- `collected_at` — timestamp of collection
