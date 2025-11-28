import os
import subprocess

try:
    import docker
except Exception:
    docker = None


class DockerInterface:
    def __init__(self, stacks_dir):
        self.stacks_dir = stacks_dir

    def get_stacks(self):
        if not os.path.isdir(self.stacks_dir):
            return []
        return sorted([
            d for d in os.listdir(self.stacks_dir)
            if os.path.isdir(os.path.join(self.stacks_dir, d))
        ])

    def is_stack_running(self, stack_path):
        """Return True if any container for the compose project is running.

        Strategy:
        - Prefer Docker SDK (`docker` package + socket at /var/run/docker.sock).
        - Fallback to `docker compose ps -q` in the stack directory if SDK unavailable.
        """
        stack_name = os.path.basename(stack_path.rstrip(os.sep))

        # Try Docker SDK first
        if docker is not None:
            try:
                client = docker.from_env()
                # containers created by docker-compose are labeled with
                # com.docker.compose.project=<project_name>
                filters = {"label": f"com.docker.compose.project={stack_name}"}
                containers = client.containers.list(all=True, filters=filters)
                for c in containers:
                    if getattr(c, "status", "") == "running":
                        return True
                return False
            except Exception:
                # fall through to CLI fallback
                pass

        # CLI fallback: run `docker compose ps -q` in stack dir
        try:
            r = subprocess.run(["docker", "compose", "ps", "-q"], cwd=stack_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out = r.stdout.decode().strip()
            return len(out.splitlines()) > 0
        except Exception:
            return False
