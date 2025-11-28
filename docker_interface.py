import os, subprocess
class DockerInterface:
    def __init__(self, stacks_dir):
        self.stacks_dir = stacks_dir
    def get_stacks(self):
        if not os.path.isdir(self.stacks_dir): return []
        return sorted([d for d in os.listdir(self.stacks_dir)
                       if os.path.isdir(os.path.join(self.stacks_dir, d))])
    def is_stack_running(self, stack_path):
        try:
            r = subprocess.run(["docker","compose","ps","-q"], cwd=stack_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return len(r.stdout.decode().strip().splitlines())>0
        except: return False
