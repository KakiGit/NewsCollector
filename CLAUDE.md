# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Guidelines

- After each feature has completed, verify it works with proper methods.
- **MUST** update README.md if any new commands, tools, features, or configuration options are added.

## Project Overview

NewsCollector is a Python CLI tool that collects trending news, topics, and events from major news publishers and social media platforms worldwide. It supports multiple platforms (Twitter/X, YouTube, Weibo, TikTok, RSS feeds, etc.) and can enrich collected data with AI-generated summaries and labels.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for Instagram, RedNote, Douyin scraping)
playwright install chromium

# Setup configuration
cp config/config.example.yaml config/config.yaml

# Collect from all platforms
python -m newscollector collect --all

# Collect from specific platform(s)
python -m newscollector collect --platform twitter --platform youtube

# Collect with region filter
python -m newscollector collect --platform news_rss --region europe

# List available platforms
python -m newscollector list-platforms

# Start web UI
python -m newscollector serve

# Financial report collection
python -m newscollector collect-reports --region us_300
python -m newscollector evaluate-reports
python -m newscollector clean-reports

# Run tests
pytest

# Run a single test file
pytest tests/test_collector.py

# Run a single test
pytest tests/test_collector.py::test_function_name -v
```

## Architecture

### Core Components

- **`newscollector/cli.py`** - CLI entry point using Click. Defines all commands (`collect`, `serve`, `list-platforms`, `verdict`, `collect-reports`, etc.)

- **`newscollector/collector.py`** - Main orchestrator. Loads config, dispatches to platform collectors, handles AI enrichment, saves results. Key functions: `load_config()`, `collect_platform()`, `collect_all()`, `generate_verdicts_from_items()`

- **`newscollector/platforms/`** - Platform-specific collectors. Each module implements a collector class that inherits from `BaseCollector`:
  - `base.py` - Abstract `BaseCollector` class defining the interface
  - `twitter.py`, `youtube.py`, `weibo.py`, `bilibili.py` - API-based collectors
  - `news_rss.py` - RSS feed collector
  - `instagram.py`, `rednote.py`, `tiktok.py`, `douyin.py` - Playwright-based scrapers

- **`newscollector/models.py`** - Pydantic models: `TrendingItem`, `CollectionResult`, `DailyVerdict`, `FinancialReport`

- **`newscollector/utils/storage.py`** - JSON file storage utilities. Saves collected items to date-organized directories, handles deduplication

- **`newscollector/utils/ai.py`** - AI enrichment utilities. Handles summarization, labeling, and daily verdict generation via LLM APIs

- **`newscollector/utils/labeller.py`** - Keyword-based fallback labeling when AI is not configured

- **`newscollector/web.py`** - FastAPI web UI for browsing collected items

- **`newscollector/financial.py`** - Financial report collection using yfinance, with AI evaluation support

### Data Flow

1. CLI parses commands and calls `collector.collect_all()` or `collector.collect_platform()`
2. Collector creates platform-specific collector instances from `PLATFORM_REGISTRY`
3. Each collector's `collect()` method returns a `CollectionResult` with `TrendingItem` list
4. Collector enriches items with AI summaries/labels (if configured) or falls back to keyword labeling
5. Results are saved to JSON files via `storage.save_result()`
6. Daily verdicts are generated via AI (if configured)

### Platform Registry

Platforms are registered in `newscollector/platforms/__init__.py` via `PLATFORM_REGISTRY` dictionary. New platforms should:
1. Create a new module in `platforms/`
2. Implement a class inheriting from `BaseCollector`
3. Register in `PLATFORM_REGISTRY`

### Configuration

Config is loaded from `config/config.yaml`. Key sections:
- `storage.database_url` - PostgreSQL connection (optional)
- `ai.ai_base_url`, `ai.ai_model`, `ai.ai_api_key` - LLM configuration
- Platform-specific API keys (Twitter bearer token, YouTube API key, etc.)

