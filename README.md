# NewsCollector

A Python CLI tool that collects trending news, topics, and events from major news publishers and social media platforms worldwide.

## Supported Platforms

| Platform    | Method             | Auth Required       |
|-------------|--------------------|---------------------|
| News (RSS)  | RSS feeds          | No                  |
| News (API)  | NewsAPI.org        | Yes (free tier key) |
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

Edit `config/config.yaml` with your API keys for platforms that require authentication.

## Usage

```bash
# Collect from all platforms
python -m newscollector collect --all

# Collect from a specific platform
python -m newscollector collect --platform twitter
python -m newscollector collect --platform news_rss --region europe

# Collect from multiple platforms
python -m newscollector collect --platform twitter --platform youtube --platform weibo

# List available platforms and regions
python -m newscollector list-platforms
```

## Output

Results are saved as JSON files in `output/<platform>/<YYYY-MM-DD>.json`.

Each trending item includes:
- `title` — headline or topic name
- `url` — link to the original content
- `source` — publisher or platform name
- `platform` — collector identifier
- `region` — geographic region
- `rank` — position in trending list
- `description` — brief summary
- `heat` — engagement/popularity metric
- `collected_at` — timestamp of collection
