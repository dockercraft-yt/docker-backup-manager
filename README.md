# Docker Backup Manager

**Minimal, self-hosted backup manager for Docker Compose stacks.**
This project provides a web UI, REST API, backup & restore engine, basic auth, and can run in Docker or as a systemd service.

## Features
- Backup of stack folders (compose files + data directories)
- Stop/start stacks when needed (mirrors your existing bash script)
- Web UI to select stacks and run backups
- REST API to list stacks, trigger backups and restores
- Restore engine to restore archives
- Basic HTTP authentication for the web UI and API (configurable)
- Ready-to-use Docker image and `docker-compose.yml`
- Systemd service file for non-Docker deployment

## Quick start (Docker)
1. Adjust `config.yaml` to your paths (`stacks_dir`, `backup_dir`, `log_dir`).
2. Build and run:
```bash
docker compose up --build -d
```
3. Open the web UI: `http://HOST:8000`

## Quick start (systemd / non-docker)
1. Install Python 3.11+ and dependencies:
```bash
python -m venv /opt/docker-backup-manager/venv
source /opt/docker-backup-manager/venv/bin/activate
pip install -r requirements.txt
```
2. Place the project under `/opt/docker-backup-manager`.
3. Enable the systemd service:
```bash
sudo cp docker-backup-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now docker-backup-manager.service
```
4. Access the app on port 8000.

## REST API
- `GET /api/stacks` — list stacks
- `POST /api/backup` — JSON `{"stacks":["stack1","stack2"]}`
- `POST /api/restore` — JSON `{"backup":"stackname_2025-11-01_12-00-00.tar.gz"}`

All API endpoints require basic auth by default.

## Security notes
Mounting `/var/run/docker.sock` gives the container access to control Docker on the host. Use only in trusted environments.

Set a strong `FLASK_SECRET` and change credentials used for basic auth (see `app.py`).

## Files of interest
- `backup_engine.py` — backup logic
- `restore_engine.py` — restore logic
- `app.py` — Flask application (UI + API)
- `config.yaml` — configuration
- `docker-compose.yml`, `Dockerfile` — containerization

## Adding users for basic auth
For the MVP, credentials are stored in `app.py` in `USERS` dictionary. For production, integrate with an external store.
