# NewsCollector Docker Compose Template
# Copy this file to docker-compose.yml and fill in your values:
#   cp docker-compose.yml.tpl docker-compose.yml
#
# Or use the render script to auto-fill from config.yaml:
#   python scripts/render_docker_compose.py

services:
  postgresql:
    image: docker.io/library/postgres:16-alpine
    container_name: newscollector_db
    restart: unless-stopped
    volumes:
      - ./output/sqldata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=newscollector
      - POSTGRES_USER={{ .postgres_user }}
      - POSTGRES_PASSWORD={{ .postgres_password }}
    networks:
      - shared-network

  newscollector:
    build: .
    container_name: newscollector
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./config/config.yaml:/app/config/config.yaml:ro
      - ./output:/app/output
    networks:
      - shared-network
    depends_on:
      - postgresql

networks:
  shared-network:
    external: true
