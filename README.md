# Docker Backup Manager

**Professional self-hosted backup manager for Docker Compose stacks.**

A modern, feature-rich backup solution with a beautiful web interface, real-time logging, JSON API, and comprehensive Docker orchestration support.

## ✨ Features

### 🎯 Core Functionality
- **Automated Backups** — Compress compose files and data directories into `.tar.gz` archives
- **Stack Control** — Stop/start Docker Compose stacks before/after backups
- **Retention Policy** — Auto-cleanup of old backups and logs based on configurable retention days
- **Real-time Logging** — In-memory log buffer with live dashboard display
- **Multiple Stacks** — Support for batch operations across multiple stacks

### 🖥️ Web Interface
- **Modern Dashboard** — Stats cards showing stacks found, running count, backup status
- **Live Log Viewer** — Auto-refreshing logs (5-second intervals) for real-time backup monitoring
- **Stack Management** — Visual stack selection with status indicators (running/stopped/skip-stop)
- **Sidebar Navigation** — Clean, intuitive navigation with active state highlighting
- **Responsive Design** — Tailwind CSS with dark theme, mobile-friendly layout
- **Log Browser** — Browse, view, and download all backup logs
- **Flash Messages** — Color-coded alerts for success, warnings, and errors

### 🔌 REST API
- `GET /api/status` — Backup state, stacks list, timestamp
- `GET /api/logs?lines=50` — Recent log entries (default 50, max 500)
- `GET /api/config` — Non-sensitive configuration (directories, retention settings)
- `POST /backup` — Trigger backup with stack selection and validation
- `GET /logs` — List all backup log files
- `GET /logs/<name>` — View individual log file content
- `GET /download_log/<name>` — Download log file

### 🏗️ Technical Excellence
- **Type Hints** — Full PEP 484 type annotations throughout codebase
- **Error Handling** — Comprehensive error handlers with 404/500 custom pages
- **Input Validation** — Path traversal and injection prevention on all routes
- **Background Threading** — Non-blocking backup operations with progress tracking
- **Docker Integration** — Docker SDK with CLI fallback for reliable stack detection
- **Health Checks** — Built-in Dockerfile health checks for orchestrators
- **Unbuffered Logging** — Immediate log flushing for real-time dashboard updates
- **Professional Code** — Docstrings on all classes/methods, structured error handling

## 🚀 Quick Start (Docker)

### Prerequisites
- Docker & Docker Compose
- Mount point for stacks directory: `/opt/stacks`
- Backup destination: `/opt/backups`
- Docker socket access: `/var/run/docker.sock`

### Setup

1. **Configure** — Update `config.yaml`:
   ```yaml
   stacks_dir: /opt/stacks
   backup_dir: /opt/backups
   log_dir: /opt/backup-logs
   include_data: true
   skip_stop:
     - traefik  # Don't stop these stacks
   retention_days: 7
   log_retention_days: 14
   ```

2. **Run**:
   ```bash
   docker compose up --build -d
   ```

3. **Access** — Open `http://localhost:8000`

### Configuration

**config.yaml** structure:
```yaml
stacks_dir: /path/to/stacks       # Directory containing docker-compose.yml files
backup_dir: /path/to/backups      # Where to store .tar.gz backups
log_dir: /path/to/logs            # Backup operation logs
include_data: true                # Include data volumes in backups
skip_stop:                        # Stacks to NOT stop during backup
  - traefik
  - networking
retention_days: 7                 # Delete backups older than N days
log_retention_days: 14            # Delete logs older than N days
```

## 🔐 Security Notes

- **Docker Socket** — Mounting `/var/run/docker.sock` gives the container full Docker control. Use only in trusted environments.
- **Health Checks** — Container includes HTTP health checks for orchestrator monitoring.
- **Input Validation** — All user inputs validated against path traversal and injection attacks.
- **Log Sanitization** — Logs stored securely on host filesystem with configurable retention.

## 📁 Project Structure

```
.
├── app.py                    # Flask application (6 routes + 3 API endpoints)
├── backup_engine.py          # Backup orchestration & logging (398 lines)
├── docker_interface.py        # Docker Compose stack detection
├── config.yaml               # Configuration file
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container image definition
├── docker-compose.yml        # Local development compose file
├── templates/
│   ├── layout.html          # Base template with sidebar navigation
│   ├── index.html           # Dashboard with stats & live logs
│   ├── logs.html            # Log file browser
│   ├── view_log.html        # Individual log viewer
│   └── error.html           # Generic error page
└── README.md                # This file
```

## 🛠️ API Endpoints

### Health & Status
```bash
GET /
# Dashboard UI

GET /api/status
# Response: {"backup_in_progress": false, "stacks": [...], "timestamp": "..."}

GET /api/config
# Response: {"stacks_dir": "...", "retention_days": 7, ...}
```

### Logs
```bash
GET /api/logs?lines=50
# Response: {"count": N, "logs": [...], "timestamp": "..."}

GET /logs
# List all backup log files

GET /logs/<name>
# View specific log file

GET /download_log/<name>
# Download log file
```

### Backup Operations
```bash
POST /backup
# Form data: stack=stack1&stack=stack2
# Triggers background backup thread
# Validates stack names before execution
```

## 📊 Web Interface

### Dashboard (`/`)
- **Stats Cards** — Quick overview of stack count, running instances, backup status
- **Backup Form** — Multi-select checkboxes with skip-stop indicators
- **Live Logs** — Auto-refreshing container showing last 30 log entries
- **Stack Details** — Table showing stack configuration and status

### Logs (`/logs`)
- **Log Browser** — List of all `backup_*.log` files with size info
- **View/Download** — Options to view in browser or download each log

### Log Viewer (`/logs/<name>`)
- **Monospace Display** — Raw log content with proper formatting
- **Back Button** — Quick navigation to logs list

## 🔄 Backup Workflow

1. **User selects stacks** via web form or API
2. **Background thread spawned** — Main request returns immediately
3. **Validation** — Stack names sanitized, existence verified
4. **Pre-backup** — Stacks in skip_stop list are preserved; others stopped
5. **Compression** — Compose files + data directories compressed to `.tar.gz`
6. **Logging** — Real-time logs written to buffer (visible in dashboard) and disk
7. **Post-backup** — Stacks restarted (if stopped)
8. **Retention** — Old backups auto-deleted based on `retention_days`
9. **UI Update** — Dashboard logs auto-refresh via `/api/logs` endpoint

## 📝 Logging

All backup operations logged with levels:
- `[INFO]` — General operations
- `[SUCCESS]` — Completed tasks
- `[WARNING]` — Non-critical issues
- `[ERROR]` — Failures and exceptions

Logs stored in two places:
1. **In-memory buffer** — Last 500 lines, displayed in dashboard in real-time
2. **Disk** — Permanent log files in `log_dir`, subject to `log_retention_days` retention

## 🐳 Docker Deployment

### Build & Run
```bash
docker compose up --build -d
docker logs -f docker-backup-manager
```

### Health Check
The container includes a health check that:
- Runs every 30 seconds
- Makes HTTP request to `/`
- Expects HTTP 200 response
- Fails after 3 consecutive failures

### Environment Variables (in docker-compose.yml)
```yaml
PYTHONUNBUFFERED=1           # Unbuffered logging for real-time output
FLASK_ENV=production         # Production Flask mode
```

## 📦 Dependencies

- **Flask 2.2+** — Web framework
- **Werkzeug 2.2+** — WSGI utilities
- **PyYAML 6.0+** — Configuration parsing
- **docker 6.0+** — Docker SDK for Python
- **gunicorn 21.0+** — Production WSGI server

See `requirements.txt` for complete dependency list.

## 🎓 Example Usage

### Via Web UI
1. Navigate to `http://localhost:8000`
2. Check stats — verify stacks detected
3. Select stacks from checkboxes
4. Click "Start Backup"
5. Watch logs auto-update in dashboard
6. Backups saved to `/opt/backups/`

### Via cURL
```bash
# Get status
curl http://localhost:8000/api/status

# Fetch recent logs
curl 'http://localhost:8000/api/logs?lines=100'

# Get configuration
curl http://localhost:8000/api/config

# Trigger backup (form-based)
curl -X POST http://localhost:8000/backup \
  -d 'stack=stack1&stack=stack2'
```

## 🐛 Troubleshooting

**Problem**: Container won't start
- Check Docker socket permissions: `ls -l /var/run/docker.sock`
- Verify volumes mounted in `docker-compose.yml`
- Review logs: `docker logs docker-backup-manager`

**Problem**: Stacks not detected
- Verify `stacks_dir` path exists and contains `docker-compose.yml` files
- Check Docker SDK connectivity: `docker ps` works?
- Review config in `/opt/stacks`

**Problem**: Logs not appearing
- Check `log_dir` exists and is writable by container
- Verify `PYTHONUNBUFFERED=1` set in Dockerfile
- Check container logs for errors

**Problem**: Backups running slowly
- Monitor disk I/O: `docker stats`
- Check backup size: `du -sh /opt/backups/`
- Consider excluding unnecessary directories in `backup_engine.py`

## 📄 License

See LICENSE file for licensing information.

## 🤝 Contributing

Found a bug or have a feature request? Contributions are welcome!
