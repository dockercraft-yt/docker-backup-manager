"""Flask Web Interface for Docker Backup Manager

Routes:
  /              - Main dashboard (stack status, backup form)
  /backup        - Start backup (POST)
  /logs          - View recent logs
  /status        - JSON API (stack status)
  /api/logs      - JSON API (recent logs)
"""

import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file

from docker_interface import DockerInterface
from backup_engine import BackupEngine


# Flask app setup
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_me_in_production")

# Initialize engines
engine = BackupEngine(config_path="/app/config.yaml")
dock = DockerInterface(engine.stacks_dir)

# Track active backup job
_backup_in_progress = False


def _run_backups_background(selected_stacks: list) -> None:
    """Run backups in a background thread.
    
    Args:
        selected_stacks: List of stack names to backup.
    """
    global _backup_in_progress
    try:
        _backup_in_progress = True
        results = engine.backup_selected_stacks(selected_stacks)
        
        if results["failed"]:
            engine.log(f"⚠️  Some backups failed: {', '.join(results['failed'])}", level="WARNING")
    except Exception as e:
        engine.log(f"❌ Background backup job error: {e}", level="ERROR")
    finally:
        _backup_in_progress = False


@app.route("/")
def index():
    """Main dashboard - display stacks and backup form."""
    stacks = []
    for stack_name in dock.get_stacks():
        stack_path = os.path.join(engine.stacks_dir, stack_name)
        is_running = dock.is_stack_running(stack_path)
        stacks.append({
            "name": stack_name,
            "running": is_running,
            "skip_stop": stack_name in engine.skip_stop,
        })
    
    return render_template("index.html", stacks=stacks, backup_in_progress=_backup_in_progress)


@app.route("/backup", methods=["POST"])
def backup():
    """Start a backup job for selected stacks."""
    selected = request.form.getlist("stack")
    
    if not selected:
        flash("❌ No stacks selected.", "danger")
        return redirect(url_for("index"))
    
    # Validate stack names (prevent injection)
    available = set(dock.get_stacks())
    valid_stacks = [s for s in selected if s in available]
    
    if not valid_stacks:
        flash("❌ Invalid stack selection.", "danger")
        return redirect(url_for("index"))
    
    engine.log(f"📤 Web UI backup requested: {', '.join(valid_stacks)}", level="SUCCESS")
    
    # Start background thread
    thread = threading.Thread(target=_run_backups_background, args=(valid_stacks,), daemon=True)
    thread.start()
    
    flash(f"✅ Backup started for: {', '.join(valid_stacks)}", "success")
    return redirect(url_for("index"))


@app.route("/logs")
def logs():
    """Display recent logs from file system."""
    log_files = []
    try:
        for fname in sorted(os.listdir(engine.log_dir), reverse=True):
            if fname.startswith("backup_") and fname.endswith(".log"):
                fpath = os.path.join(engine.log_dir, fname)
                fsize = os.path.getsize(fpath)
                log_files.append({
                    "name": fname,
                    "size_kb": fsize / 1024,
                })
    except Exception as e:
        engine.log(f"❌ Error reading log directory: {e}", level="ERROR")
    
    return render_template("logs.html", log_files=log_files)


@app.route("/logs/<log_name>")
def view_log(log_name: str):
    """View contents of a single log file."""
    # Validate filename (prevent path traversal)
    if "/" in log_name or ".." in log_name or not log_name.endswith(".log"):
        flash("❌ Invalid log file.", "danger")
        return redirect(url_for("logs"))
    
    log_path = os.path.join(engine.log_dir, log_name)
    
    if not os.path.isfile(log_path):
        flash("❌ Log file not found.", "danger")
        return redirect(url_for("logs"))
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        return render_template("view_log.html", log_name=log_name, content=content)
    except Exception as e:
        flash(f"❌ Error reading log file: {e}", "danger")
        return redirect(url_for("logs"))


@app.route("/download_log/<log_name>")
def download_log(log_name: str):
    """Download a log file."""
    # Validate filename
    if "/" in log_name or ".." in log_name or not log_name.endswith(".log"):
        return jsonify({"error": "Invalid log file"}), 400
    
    log_path = os.path.join(engine.log_dir, log_name)
    
    if not os.path.isfile(log_path):
        return jsonify({"error": "Log file not found"}), 404
    
    try:
        return send_file(log_path, as_attachment=True, download_name=log_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# JSON API Endpoints
# =====================================================================

@app.route("/api/status")
def api_status():
    """JSON API - Get current backup status and stack information."""
    stacks = []
    for stack_name in dock.get_stacks():
        stack_path = os.path.join(engine.stacks_dir, stack_name)
        stacks.append({
            "name": stack_name,
            "running": dock.is_stack_running(stack_path),
            "skip_stop": stack_name in engine.skip_stop,
        })
    
    return jsonify({
        "backup_in_progress": _backup_in_progress,
        "stacks": stacks,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/logs")
def api_logs():
    """JSON API - Get recent log entries."""
    lines = min(int(request.args.get("lines", 50)), 500)
    recent_logs = engine.get_recent_logs(lines=lines)
    
    return jsonify({
        "logs": recent_logs,
        "count": len(recent_logs),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/config")
def api_config():
    """JSON API - Get non-sensitive configuration."""
    return jsonify({
        "stacks_dir": engine.stacks_dir,
        "backup_dir": engine.backup_dir,
        "log_dir": engine.log_dir,
        "retention_days": engine.retention_days,
        "log_retention_days": engine.log_retention_days,
        "include_data": engine.include_data,
        "skip_stop": list(engine.skip_stop),
    })


# =====================================================================
# Error Handlers
# =====================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return render_template("error.html", error="Page not found"), 404


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    engine.log(f"❌ Server error: {e}", level="ERROR")
    return render_template("error.html", error="Internal server error"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
