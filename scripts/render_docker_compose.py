#!/usr/bin/env python3
"""
Render docker-compose.yml.tpl with values from config.yaml.

Usage:
    python scripts/render_docker_compose.py
"""

import argparse
import os
import sys
from pathlib import Path

import yaml


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_postgres_credentials(database_url: str) -> tuple[str, str]:
    """Extract user and password from PostgreSQL connection string."""
    # Format: postgresql://user:password@host:port/dbname
    if "://" not in database_url:
        return "kaki", "password"

    # Remove protocol prefix
    url = database_url.split("://", 1)[1]
    # Split on @ to get user:password part
    if "@" in url:
        user_pass, _ = url.split("@", 1)
        if ":" in user_pass:
            user, password = user_pass.split(":", 1)
            # URL decode password
            from urllib.parse import unquote

            return user, unquote(password)

    return "kaki", "password"


def render_template(template_path: str, config: dict) -> str:
    """Render docker-compose template with config values."""
    with open(template_path, "r") as f:
        template = f.read()

    # Extract values from config
    storage = config.get("storage", {})
    database_url = storage.get("database_url", "")

    postgres_user, postgres_password = get_postgres_credentials(database_url)

    # Replace placeholders
    replacements = {
        "{{ .postgres_user }}": postgres_user,
        "{{ .postgres_password }}": postgres_password,
    }

    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Render docker-compose.yml.tpl with config.yaml values"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config/config.yaml",
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "-t",
        "--template",
        default="docker-compose.yml.tpl",
        help="Path to template file (default: docker-compose.yml.tpl)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="docker-compose.yml",
        help="Output file (default: docker-compose.yml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout instead of writing file",
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent
    config_path = project_root / args.config
    template_path = project_root / args.template

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if not template_path.exists():
        print(f"Error: Template file not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(str(config_path))
    rendered = render_template(str(template_path), config)

    if args.dry_run:
        print(rendered)
    else:
        output_path = project_root / args.output
        with open(output_path, "w") as f:
            f.write(rendered)
        print(f"Rendered {template_path.name} -> {output_path}")


if __name__ == "__main__":
    main()
