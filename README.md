# SLSPanel

[![GHCR](https://img.shields.io/badge/ghcr-packages-blue?style=for-the-badge)](https://github.com/jahaddow/slspanel/pkgs/container/slspanel)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

A web-based control panel for SLS live streaming servers.

## Features

- Stream management
- Player and URL management
- Real-time statistics viewer
- OPN-branded login and dashboard UI
- Supports both single-publisher and multi-publisher SLS stats payloads
- Per-stream push configuration and toggle (`srt://`, `rtmp://`, `rtmps://`)
- Optional authentication
- Login throttling and security-header hardening controls
- Docker-ready deployment
- English-only interface configuration

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Running SLS instance
- SLS API key

### Docker Compose

```bash
git clone https://github.com/jahaddow/slspanel.git
cd slspanel
docker compose up -d
```

### Docker Run

```bash
docker run -d \
  --name slspanel \
  -e REQUIRE_LOGIN=True \
  -e USERNAME=admin \
  -e PASSWORD=change-me \
  -e SLS_API_URL=http://localhost:8789 \
  -e SLS_API_KEY=your_api_key \
  -e PUSH_INTERNAL_TOKEN=change-me \
  -e SLSPANEL_DB_PATH=/app/data/db.sqlite3 \
  -e SLS_DOMAIN_IP=localhost \
  -e TZ=UTC \
  -e SRT_PUBLISH_PORT=4000 \
  -e SRT_PLAYER_PORT=4001 \
  -e SRTLA_PUBLISH_PORT=5000 \
  -e SLS_STATS_PORT=8789 \
  -p 8000:8000/tcp \
  -v slspanel-data:/app/data \
  ghcr.io/jahaddow/slspanel:latest
```

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `REQUIRE_LOGIN` | Enable authentication (`True`/`False`) | `False` | No |
| `USERNAME` | Admin username | `admin` | If login enabled |
| `PASSWORD` | Admin password | - | If login enabled |
| `SLSPANEL_ALLOWED_HOSTS` | Comma-separated host allowlist | `localhost,127.0.0.1,<SLS_DOMAIN_IP>,<SLS_STATS_DOMAIN_IP>` | No |
| `SLSPANEL_CSRF_TRUSTED_ORIGINS` | Comma-separated CSRF trusted origins (`http(s)://host`) | empty | No |
| `SLSPANEL_SECURE_COOKIES` | Set secure cookie flags (enable when behind HTTPS proxy) | `False` | No |
| `SLSPANEL_TRUST_PROXY_SSL_HEADER` | Trust `X-Forwarded-Proto` for secure request detection | `False` | No |
| `SLSPANEL_ENABLE_LOGIN_THROTTLE` | Enable login attempt throttling | `True` | No |
| `SLSPANEL_LOGIN_THROTTLE_WINDOW_SECONDS` | Failed-attempt counting window | `300` | No |
| `SLSPANEL_LOGIN_THROTTLE_MAX_ATTEMPTS` | Max failed attempts before lockout | `6` | No |
| `SLSPANEL_LOGIN_LOCKOUT_SECONDS` | Lockout duration after threshold | `900` | No |
| `SLS_API_URL` | SLS server API endpoint | - | Yes |
| `SLS_API_KEY` | SLS API key | - | Yes |
| `PUSH_INTERNAL_TOKEN` | Internal auth token shared with srtla-server push runner | - | Yes (for push relay) |
| `SLSPANEL_DB_PATH` | SQLite database path inside container | `/app/data/db.sqlite3` | No |
| `SLS_DOMAIN_IP` | Domain/IP for stream URLs | `localhost` | Yes |
| `TZ` | Timezone | `UTC` | No |
| `SRT_PUBLISH_PORT` | SRT publishing port | `4000` | Yes |
| `SRT_PLAYER_PORT` | SRT playback port | `4001` | Yes |
| `SRTLA_PUBLISH_PORT` | SRTLA publishing port | `5000` | Yes |
| `SLS_STATS_PORT` | SLS statistics port | `8789` | Yes |

## Data Persistence

- Mount a persistent volume at `/app/data` to retain panel users, push destinations, and push control tokens across container updates.
- If your deployment previously ran without this volume, older data from that period cannot be restored unless you still have a backup of the prior `db.sqlite3`.

## Related Projects

- [jahaddow/srtla-server](https://github.com/jahaddow/srtla-server)
- [jahaddow/stream-relay-installer](https://github.com/jahaddow/stream-relay-installer)

## License

MIT


## Companion Remote Control

SLSPanel can issue per-stream control tokens for push relay control:

- `POST /api/push/control/{publisher}/enable`
- `POST /api/push/control/{publisher}/disable`
- `GET /api/push/control/{publisher}/status`

Each token is scoped to a single publisher stream.
For browser testing, `enable`/`disable` also accept `GET` with `?token=...`.
Bearer header authentication is safer than query-token links and should be preferred for production tooling.
