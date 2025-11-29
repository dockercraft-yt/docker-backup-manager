"""Docker Backup Engine

Handles backup/restore operations for Docker Compose stacks.
Features:
  - YAML configuration support
  - Compose file + data directory backup as tar.gz
  - Container stop/start with skip-list
  - Automatic log rotation & retention
  - Detailed logging with timestamps
"""

import os
import subprocess
import tarfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
import yaml


class BackupEngine:
    """Main backup orchestrator for Docker stacks."""

    def __init__(self, config_path: str = "/app/config.yaml"):
        """Initialize BackupEngine with configuration.
        
        Args:
            config_path: Path to YAML configuration file.
        """
        self.config_path = config_path
        self._config = self._load_config()
        
        # Directories
        self.stacks_dir = self._config.get("stacks_dir", "/opt/stacks")
        self.backup_dir = self._config.get("backup_dir", "/opt/backups")
        self.log_dir = self._config.get("log_dir", "/opt/backup-logs")
        
        # Behavior
        self.include_data = bool(self._config.get("include_data", True))
        self.skip_stop = set(self._config.get("skip_stop", []) or [])
        self.retention_days = int(self._config.get("retention_days", 7))
        self.log_retention_days = int(self._config.get("log_retention_days", 14))
        
        # Ensure directories exist
        for d in [self.stacks_dir, self.backup_dir, self.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)
        
        # Today's log file
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = os.path.join(self.log_dir, f"backup_{today}.log")
        
        # In-memory logs for web UI
        self._log_buffer = []

    def _load_config(self) -> dict:
        """Load YAML configuration with fallback to defaults."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                return cfg
        except FileNotFoundError:
            print(f"⚠️  Config file not found: {self.config_path}; using defaults", flush=True)
            return {}
        except yaml.YAMLError as e:
            print(f"⚠️  YAML parse error: {e}; using defaults", flush=True)
            return {}

    def log(self, msg: str, level: str = "INFO") -> None:
        """Write log message to file and buffer.
        
        Args:
            msg: Log message.
            level: Log level (INFO, WARNING, ERROR, SUCCESS).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level:8s}] {msg}\n"
        
        # Write to file
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            print(f"[LOG-ERROR] Could not write to {self.log_file}: {e}", flush=True)
        
        # Buffer for web UI
        self._log_buffer.append(line.rstrip("\n"))
        # Keep last 500 lines in memory
        if len(self._log_buffer) > 500:
            self._log_buffer.pop(0)
        
        # Print to console (unbuffered)
        print(line, end="", flush=True)

    def get_recent_logs(self, lines: int = 100) -> List[str]:
        """Get recent log entries from buffer.
        
        Args:
            lines: Number of recent lines to return.
        
        Returns:
            List of log lines.
        """
        return self._log_buffer[-lines:]

    def run_compose(self, stack_path: str, args: List[str], check: bool = True) -> bool:
        """Execute docker compose command in stack directory.
        
        Args:
            stack_path: Path to stack directory.
            args: Arguments to pass to `docker compose`.
            check: If True, raise on non-zero exit code.
        
        Returns:
            True if successful, False otherwise.
        """
        # Prefer the docker CLI.
        docker_bin = shutil.which("docker")
        if docker_bin is None:
            # If CLI missing, attempt an SDK-based fallback for `down` operations
            # (stop & remove containers). Starting a compose stack (`up -d`) via
            # SDK is non-trivial and not implemented here.
            if "down" in args:
                self.log("ℹ️  'docker' CLI not found; attempting Docker SDK fallback for 'down'...", level="WARNING")
                try:
                    return self._sdk_down(stack_path)
                except Exception as e:
                    self.log(f"❌ SDK fallback for 'down' failed: {e}", level="ERROR")
                    return False

            self.log(
                "❌ 'docker' executable not found in PATH; cannot run 'docker compose' commands. "
                "Install Docker CLI in the container or mount the Docker socket for SDK operations.",
                level="ERROR",
            )
            return False

        try:
            result = subprocess.run(
                ["docker", "compose"] + args,
                cwd=stack_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=120,
            )

            if result.returncode != 0:
                err_msg = result.stderr.strip() or result.stdout.strip()
                self.log(f"⚠️  docker compose {' '.join(args)} failed: {err_msg}", level="WARNING")
                return not check

            if result.stdout.strip():
                self.log(f"docker compose output: {result.stdout.strip()}", level="DEBUG")

            return True

        except subprocess.TimeoutExpired:
            self.log(f"❌ docker compose {' '.join(args)} timed out (120s)", level="ERROR")
            return False
        except Exception as e:
            self.log(f"❌ Error running docker compose {' '.join(args)}: {e}", level="ERROR")
            return False

    def _sdk_down(self, stack_path: str) -> bool:
        """Attempt to stop and remove containers for the compose project using Docker SDK.

        This is a pragmatic fallback used when the `docker` CLI is not available
        inside the runtime but the Docker socket is mounted and `docker` python
        package is installed.
        """
        try:
            import docker as _docker

            client = _docker.from_env()
            project = os.path.basename(stack_path.rstrip("/"))
            label = f"com.docker.compose.project={project}"
            self.log(f"ℹ️  SDK: looking for containers with label {label}")

            containers = client.containers.list(all=True, filters={"label": label})
            if not containers:
                self.log(f"ℹ️  SDK: no containers found for project {project}")
                return False

            for c in containers:
                try:
                    if c.status == "running":
                        self.log(f"ℹ️  SDK: stopping container {c.name} ({c.id[:12]})")
                        c.stop(timeout=10)
                    self.log(f"ℹ️  SDK: removing container {c.name} ({c.id[:12]})")
                    c.remove(v=True, force=True)
                except Exception as exc:
                    self.log(f"⚠️  SDK: failed to stop/remove {c.name}: {exc}", level="WARNING")

            # Optionally remove networks labeled for the project
            try:
                nets = client.networks.list(filters={"label": label})
                for n in nets:
                    try:
                        self.log(f"ℹ️  SDK: removing network {n.name}")
                        n.remove()
                    except Exception:
                        pass
            except Exception:
                pass

            self.log(f"✅ SDK fallback 'down' completed for project {project}", level="SUCCESS")
            return True

        except Exception as e:
            self.log(f"❌ Docker SDK error during fallback 'down': {e}", level="ERROR")
            return False

    def is_stack_running(self, stack_path: str) -> bool:
        """Check if any container in the stack is running.
        
        Args:
            stack_path: Path to stack directory.
        
        Returns:
            True if running containers exist, False otherwise.
        """
        # If the docker CLI is present, use it. Otherwise attempt a Docker
        # SDK-based check (works when the container has access to the
        # host Docker socket and python 'docker' package is installed).
        if shutil.which("docker"):
            try:
                result = subprocess.run(
                    ["docker", "compose", "ps", "-q"],
                    cwd=stack_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,
                )
                containers = result.stdout.strip().splitlines()
                return len(containers) > 0
            except Exception as e:
                self.log(f"⚠️  Could not check stack status at {stack_path}: {e}", level="WARNING")
                return False

        # Fallback: try Docker SDK
        try:
            import docker as _docker

            client = _docker.from_env()
            project = os.path.basename(stack_path.rstrip("/"))
            # Look for containers with the compose project label
            containers = client.containers.list(all=False, filters={"label": f"com.docker.compose.project={project}"})
            return len(containers) > 0
        except Exception as e:
            self.log(f"⚠️  Could not check stack status at {stack_path}: {e}", level="WARNING")
            return False

    def stop_stack(self, stack_path: str, stack_name: str) -> bool:
        """Stop all containers in a stack.
        
        Args:
            stack_path: Path to stack directory.
            stack_name: Name of the stack (for logging).
        
        Returns:
            True if successful, False otherwise.
        """
        self.log(f"⏸️  Stopping stack: {stack_name}")
        return self.run_compose(stack_path, ["down"], check=False)

    def start_stack(self, stack_path: str, stack_name: str) -> bool:
        """Start all containers in a stack.
        
        Args:
            stack_path: Path to stack directory.
            stack_name: Name of the stack (for logging).
        
        Returns:
            True if successful, False otherwise.
        """
        self.log(f"▶️  Starting stack: {stack_name}")
        return self.run_compose(stack_path, ["up", "-d"], check=False)

    def get_stacks(self) -> List[str]:
        """List all available stacks in stacks_dir.
        
        Returns:
            Sorted list of stack directory names.
        """
        try:
            if not os.path.isdir(self.stacks_dir):
                return []
            stacks = [
                d for d in os.listdir(self.stacks_dir)
                if os.path.isdir(os.path.join(self.stacks_dir, d)) and not d.startswith(".")
            ]
            return sorted(stacks)
        except Exception as e:
            self.log(f"❌ Error listing stacks in {self.stacks_dir}: {e}", level="ERROR")
            return []

    def backup_stack(self, stack_name: str) -> Optional[str]:
        """Create a full backup of a stack (compose files + data).
        
        Args:
            stack_name: Name of the stack to backup.
        
        Returns:
            Path to final backup archive, or None if failed.
        """
        stack_path = os.path.join(self.stacks_dir, stack_name)
        
        if not os.path.isdir(stack_path):
            self.log(f"❌ Stack directory not found: {stack_path}", level="ERROR")
            return None
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"{stack_name}_{timestamp}"
        temp_dir = os.path.join(self.backup_dir, f".tmp_{backup_name}")
        final_archive = os.path.join(self.backup_dir, f"{backup_name}.tar.gz")
        
        self.log(f"📦 Starting backup: {stack_name}")
        
        try:
            # Create temp directory
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            
            # Step 1: Copy compose files
            self.log(f"📝 Copying compose configuration...")
            compose_files = ["compose.yml", "compose.yaml", "docker-compose.yml", ".env"]
            for fname in compose_files:
                src = os.path.join(stack_path, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, temp_dir)
                    self.log(f"  ✓ Copied {fname}")
            
            # Step 2: Backup data directories (if enabled and not in skip_stop)
            if self.include_data and stack_name not in self.skip_stop:
                self.log(f"🗂️  Backing up data directories...")
                was_running = self.is_stack_running(stack_path)
                
                if was_running:
                    self.stop_stack(stack_path, stack_name)
                
                try:
                    # Tar all subdirectories
                    data_tar = os.path.join(temp_dir, "data.tar.gz")
                    self._create_tar(stack_path, data_tar, exclude_files=[".git", ".gitignore", "docker-compose.yml", "compose.yml", "compose.yaml", ".env"])
                    self.log(f"  ✓ Data backup created")
                finally:
                    # Always restart if it was running
                    if was_running:
                        self.start_stack(stack_path, stack_name)
            
            # Step 3: Create final archive
            self.log(f"📦 Compressing backup archive...")
            with tarfile.open(final_archive, "w:gz") as tar:
                tar.add(temp_dir, arcname=backup_name)
            
            archive_size_mb = os.path.getsize(final_archive) / (1024 * 1024)
            self.log(f"✅ Backup complete: {backup_name}.tar.gz ({archive_size_mb:.1f} MB)", level="SUCCESS")
            
            return final_archive
            
        except Exception as e:
            self.log(f"❌ Backup failed for {stack_name}: {e}", level="ERROR")
            return None
        
        finally:
            # Cleanup temp directory
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    def _create_tar(self, src_dir: str, tar_path: str, exclude_files: Optional[List[str]] = None) -> None:
        """Create a tar.gz archive of a directory.
        
        Args:
            src_dir: Source directory to tar.
            tar_path: Path to output tar.gz file.
            exclude_files: List of filenames to exclude.
        """
        exclude_files = exclude_files or []
        
        def tar_filter(tarinfo):
            # Exclude certain files/dirs
            if tarinfo.name.split("/")[-1] in exclude_files:
                return None
            return tarinfo
        
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(src_dir, arcname="data", filter=tar_filter)

    def run_retention(self) -> None:
        """Remove old backups and logs based on retention policy."""
        self.log(f"🧹 Running retention cleanup...")
        
        cutoff_backups = datetime.now() - timedelta(days=self.retention_days)
        cutoff_logs = datetime.now() - timedelta(days=self.log_retention_days)
        
        # Clean old backups
        try:
            for fname in os.listdir(self.backup_dir):
                if fname.startswith(".tmp_"):
                    continue
                fpath = os.path.join(self.backup_dir, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if mtime < cutoff_backups and fname.endswith(".tar.gz"):
                        os.remove(fpath)
                        self.log(f"  🗑️  Removed old backup: {fname}")
                except Exception as e:
                    self.log(f"  ⚠️  Could not process {fname}: {e}", level="WARNING")
        except Exception as e:
            self.log(f"❌ Error cleaning backups: {e}", level="ERROR")
        
        # Clean old logs
        try:
            for fname in os.listdir(self.log_dir):
                if not fname.startswith("backup_") or not fname.endswith(".log"):
                    continue
                fpath = os.path.join(self.log_dir, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if mtime < cutoff_logs:
                        os.remove(fpath)
                        self.log(f"  📋 Removed old log: {fname}")
                except Exception as e:
                    self.log(f"  ⚠️  Could not process {fname}: {e}", level="WARNING")
        except Exception as e:
            self.log(f"❌ Error cleaning logs: {e}", level="ERROR")
        
        self.log(f"✅ Retention cleanup complete", level="SUCCESS")

    def backup_selected_stacks(self, stack_names: List[str]) -> dict:
        """Backup multiple stacks (typically from web UI).
        
        Args:
            stack_names: List of stack names to backup.
        
        Returns:
            Dictionary with results: {"success": [...], "failed": [...]}
        """
        results = {"success": [], "failed": []}
        
        self.log("=" * 70, level="INFO")
        self.log(f"🚀 Batch backup started: {', '.join(stack_names)}", level="SUCCESS")
        self.log("=" * 70)
        
        for stack_name in stack_names:
            try:
                archive = self.backup_stack(stack_name)
                if archive:
                    results["success"].append(stack_name)
                else:
                    results["failed"].append(stack_name)
            except Exception as e:
                self.log(f"❌ Unexpected error backing up {stack_name}: {e}", level="ERROR")
                results["failed"].append(stack_name)
        
        # Retention
        try:
            self.run_retention()
        except Exception as e:
            self.log(f"⚠️  Retention error: {e}", level="WARNING")
        
        self.log("=" * 70)
        self.log(f"✅ Backup job complete: {len(results['success'])} succeeded, {len(results['failed'])} failed", level="SUCCESS")
        self.log("=" * 70)
        
        return results
