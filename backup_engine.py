import os
import subprocess
import tarfile
import shutil
from datetime import datetime, timedelta
import yaml


class BackupEngine:
    def __init__(self, config_path="/app/config.yaml"):
        # Load configuration
        with open(config_path, "r") as f:
            self.cfg = yaml.safe_load(f)

        # Config values with basic validation/defaults
        self.stacks_dir = self.cfg.get("stacks_dir", "/opt/stacks")
        self.backup_dir = self.cfg.get("backup_dir", "/opt/backups")
        self.log_dir = self.cfg.get("log_dir", "/opt/backup-logs")
        self.include_data = bool(self.cfg.get("include_data", True))
        self.skip_stop = set(self.cfg.get("skip_stop", []))
        self.retention_days = int(self.cfg.get("retention_days", 7))
        self.log_retention = int(self.cfg.get("log_retention_days", 14))

        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)

        # Logging filename
        date = datetime.now().strftime("%Y-%m-%d")
        self.log_file = os.path.join(self.log_dir, f"backup_{date}.log")

    # =====================================================================
    # Logging
    # =====================================================================
    def log(self, msg):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        line = f"{timestamp} {msg}"
        print(line)
        try:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")
        except Exception as e:
            # Fail-safe: if logging to file fails, still print
            print(f"[LOG-ERROR] Could not write to log file {self.log_file}: {e}")

    # =====================================================================
    # Docker helpers
    # =====================================================================
    def run_compose(self, stack_path, args):
        """Run docker compose commands inside a stack directory."""
        try:
            completed = subprocess.run(
                ["docker", "compose"] + args,
                cwd=stack_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            stdout = completed.stdout.decode().strip()
            stderr = completed.stderr.decode().strip()
            if stdout:
                self.log(f"docker compose {' '.join(args)} output: {stdout}")
            if stderr:
                self.log(f"docker compose {' '.join(args)} stderr: {stderr}")
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"⚠️ docker compose {' '.join(args)} failed: returncode={e.returncode}")
            try:
                err = e.stderr.decode().strip() if e.stderr else ""
                out = e.stdout.decode().strip() if e.stdout else ""
                if out:
                    self.log(f"stdout: {out}")
                if err:
                    self.log(f"stderr: {err}")
            except Exception:
                pass
            return False
        except Exception as e:
            self.log(f"⚠️ Unexpected error running docker compose {' '.join(args)}: {e}")
            return False

    def is_stack_running(self, stack_path):
        """Return True if compose reports running containers."""
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "-q"],
                cwd=stack_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            out = result.stdout.decode().strip()
            if not out:
                return False
            count = len(out.splitlines())
            return count > 0
        except Exception as e:
            self.log(f"⚠️ Error checking stack running state at {stack_path}: {e}")
            return False

    def stop_stack(self, stack_path, name):
        self.log(f"⏸️  Stopping containers for stack: {name}")
        ok = self.run_compose(stack_path, ["down"])
        if not ok:
            self.log(f"⚠️  Could not stop {name} (maybe not running or compose error).")

    def start_stack(self, stack_path, name):
        self.log(f"▶️  Restarting containers for stack: {name}")
        ok = self.run_compose(stack_path, ["up", "-d"])
        if not ok:
            self.log(f"⚠️  Could not start {name} back up!")

    # =====================================================================
    # Stack detection
    # =====================================================================
    def get_stacks(self):
        stacks = []
        try:
            if not os.path.isdir(self.stacks_dir):
                self.log(f"⚠️ Stacks directory does not exist: {self.stacks_dir}")
                return stacks
            for entry in sorted(os.listdir(self.stacks_dir)):
                path = os.path.join(self.stacks_dir, entry)
                if os.path.isdir(path):
                    stacks.append(entry)
        except Exception as e:
            self.log(f"⚠️ Error listing stacks in {self.stacks_dir}: {e}")
        return stacks

    # =====================================================================
    # Backup logic
    # =====================================================================
    def backup_stack(self, stack_name):
        stack_path = os.path.join(self.stacks_dir, stack_name)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        stack_backup_dir = os.path.join(self.backup_dir, f"{stack_name}_{timestamp}")

        self.log(f"📦 Processing stack: {stack_name}")
        try:
            os.makedirs(stack_backup_dir, exist_ok=True)
        except Exception as e:
            self.log(f"❌ Could not create stack backup directory {stack_backup_dir}: {e}")
            return

        # ------------------------------------------------------------------
        # 1. Copy compose.yml, compose.yaml, .env
        # ------------------------------------------------------------------
        self.log("📝 Copying compose files + .env...")
        for filename in ["compose.yml", "compose.yaml", ".env", "docker-compose.yml", "docker-compose.yaml"]:
            src = os.path.join(stack_path, filename)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, stack_backup_dir)
                except Exception as e:
                    self.log(f"⚠️ Could not copy {src} -> {stack_backup_dir}: {e}")

        # ------------------------------------------------------------------
        # 2. Data directories
        # ------------------------------------------------------------------
        if self.include_data:
            if stack_name in self.skip_stop:
                self.log(f"🚫 Skipping stop & data backup for critical stack: {stack_name}")
            else:
                was_running = self.is_stack_running(stack_path)

                if was_running:
                    self.log("🟢 Stack is running — stopping for backup...")
                    self.stop_stack(stack_path, stack_name)
                else:
                    self.log("⚪ Stack is not running — will not start after backup.")

                # Data folders (all subfolders)
                try:
                    subdirs = [
                        d for d in sorted(os.listdir(stack_path))
                        if os.path.isdir(os.path.join(stack_path, d)) and not d.startswith(".")
                    ]
                except Exception as e:
                    self.log(f"⚠️ Error listing subdirectories for {stack_path}: {e}")
                    subdirs = []

                if subdirs:
                    self.log(f"🗂️  Found {len(subdirs)} directories, backing them up...")
                    tar_path = os.path.join(stack_backup_dir, f"{stack_name}_data.tar.gz")
                    try:
                        with tarfile.open(tar_path, "w:gz") as tar:
                            for d in subdirs:
                                srcdir = os.path.join(stack_path, d)
                                # Add directory contents, preserve directory name
                                tar.add(srcdir, arcname=d)
                    except Exception as e:
                        self.log(f"❌ Error creating data tarball {tar_path}: {e}")
                else:
                    self.log(f"⚠️ No data directories found for {stack_name}")

                # Restart if it was running
                if was_running:
                    self.start_stack(stack_path, stack_name)
        else:
            self.log("ℹ️  Skipping data backup (include_data=false)")

        # ------------------------------------------------------------------
        # 3. Compress final backup folder
        # ------------------------------------------------------------------
        self.log("📦 Compressing final archive...")
        final_archive = f"{stack_backup_dir}.tar.gz"
        try:
            with tarfile.open(final_archive, "w:gz") as tar:
                # Use arcname so the top-level folder in tar is just the basename
                tar.add(stack_backup_dir, arcname=os.path.basename(stack_backup_dir))
        except Exception as e:
            self.log(f"❌ Error compressing final archive {final_archive}: {e}")
            # attempt to clean up and return
            try:
                shutil.rmtree(stack_backup_dir)
            except Exception:
                pass
            return

        # remove temp folder
        try:
            shutil.rmtree(stack_backup_dir)
        except Exception as e:
            self.log(f"⚠️ Could not remove temp folder {stack_backup_dir}: {e}")

        self.log(f"✅ Backup complete: {final_archive}")

    # =====================================================================
    # Retention
    # =====================================================================
    def run_retention(self):
        cutoff_backups = datetime.now() - timedelta(days=self.retention_days)
        cutoff_logs = datetime.now() - timedelta(days=self.log_retention)

        # Remove old backups
        try:
            for f in os.listdir(self.backup_dir):
                if f.endswith(".tar.gz"):
                    full = os.path.join(self.backup_dir, f)
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(full))
                        if mtime < cutoff_backups:
                            os.remove(full)
                            self.log(f"🧹 Removed old backup: {full}")
                    except Exception as e:
                        self.log(f"⚠️ Error checking/removing backup {full}: {e}")
        except Exception as e:
            self.log(f"⚠️ Error scanning backup directory {self.backup_dir}: {e}")

        # Remove old logs
        try:
            for f in os.listdir(self.log_dir):
                if f.startswith("backup_") and f.endswith(".log"):
                    full = os.path.join(self.log_dir, f)
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(full))
                        if mtime < cutoff_logs:
                            os.remove(full)
                            self.log(f"🧾 Removed old log: {full}")
                    except Exception as e:
                        self.log(f"⚠️ Error checking/removing log {full}: {e}")
        except Exception as e:
            self.log(f"⚠️ Error scanning log directory {self.log_dir}: {e}")

    # =====================================================================
    # MAIN entry
    # =====================================================================
    def run_backup(self):
        stacks = self.get_stacks()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        self.log("==============================================================")
        self.log(f"🚀 Starting Docker Backup — {timestamp}")
        self.log(f"Configuration loaded from config.yaml")
        self.log(f"Logs written to: {self.log_file}")
        self.log("==============================================================")

        self.log(f"📋 Found {len(stacks)} stacks:")
        for s in stacks:
            if s in self.skip_stop:
                self.log(f"   🚫 {s} (skipped from stop/data backup)")
            else:
                self.log(f"   ✅ {s} (full backup)")
        self.log("--------------------------------------------------------------")

        for stack in stacks:
            try:
                self.backup_stack(stack)
            except Exception as e:
                self.log(f"❌ Unexpected error processing stack {stack}: {e}")

        try:
            self.run_retention()
        except Exception as e:
            self.log(f"⚠️ Error during retention run: {e}")

        self.log("🎉 All backups completed (run_backup finished).")
        self.log("==============================================================")
