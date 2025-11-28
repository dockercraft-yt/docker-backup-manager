from flask import Flask, render_template, request, redirect, url_for, flash
import threading, os
from docker_interface import DockerInterface
from backup_engine import BackupEngine

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_me")

engine = BackupEngine(config_path="/app/config.yaml")
dock = DockerInterface(engine.stacks_dir)

def run_backups(selected):
    for s in selected:
        try: engine.backup_stack(s)
        except Exception as e: engine.log(f"❌ Error backing up {s}: {e}")
    engine.run_retention()
    engine.log("Web request backups finished.")

@app.route("/")
def index():
    stacks = []
    for s in dock.get_stacks():
        path = os.path.join(engine.stacks_dir, s)
        stacks.append({"name": s, "running": dock.is_stack_running(path)})
    return render_template("index.html", stacks=stacks)

@app.route("/backup", methods=["POST"])
def backup():
    selected = request.form.getlist("stack")
    if not selected:
        flash("No stacks selected.", "warning")
        return redirect(url_for("index"))
    threading.Thread(target=run_backups, args=(selected,), daemon=True).start()
    flash(f"Backup started for: {', '.join(selected)}", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
