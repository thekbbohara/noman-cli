## 3. Security & Sandboxing

### 3.1 Threat Model

| Threat Actor | Capabilities | Goals |
|--------------|--------------|-------|
| **Malicious User Input** | Crafted prompts attempting injection | Escape sandbox, access forbidden resources |
| **Compromised Agent** | Self-improvement gone wrong | Modify own constraints, exfiltrate data |
| **Malicious Tool** | Agent-authored tool with hidden behavior | Persist backdoor, steal credentials |
| **Supply Chain Attack** | Modified dependency or skill | Inject malicious code into workflow |

### 3.2 Sandboxing Layers

#### 3.2.1 Filesystem Sandbox

```python
# core/security/fs_sandbox.py

import os
from pathlib import Path
from typing import Set

class FilesystemSandbox:
    """Restrict file operations to allowed paths."""
    
    def __init__(self, working_dir: str, allowed_paths: Set[str] = None):
        self.working_dir = Path(working_dir).resolve()
        self.allowed_paths = {
            self.working_dir,
            Path(os.getcwd()).resolve(),
        }
        if allowed_paths:
            self.allowed_paths.update(Path(p).resolve() for p in allowed_paths)
        
        # Always allow overlay and .noman
        self.allowed_paths.add(self.working_dir / "overlay")
        self.allowed_paths.add(self.working_dir / ".noman")
    
    def validate_path(self, path: str, mode: str = "read") -> bool:
        """Check if path is within allowed boundaries."""
        resolved = Path(path).resolve()
        
        # Check if resolved path is within any allowed path
        for allowed in self.allowed_paths:
            try:
                resolved.relative_to(allowed)
                return True
            except ValueError:
                continue
        
        return False
    
    def wrap_open(self, path: str, mode: str = "r"):
        """Wrapped open() that enforces sandbox."""
        if not self.validate_path(path, mode):
            raise PermissionError(
                f"Path {path} is outside allowed directories"
            )
        return open(path, mode)
```

#### 3.2.2 Process Sandbox

```python
# core/security/process_sandbox.py

import subprocess
import signal
from typing import Optional, List

class ProcessSandbox:
    """Restrict subprocess execution."""
    
    def __init__(
        self,
        max_timeout_sec: int = 60,
        allowed_commands: List[str] = None,
        deny_network: bool = True
    ):
        self.max_timeout = max_timeout_sec
        self.allowed_commands = set(allowed_commands or [])
        self.deny_network = deny_network
    
    def validate_command(self, cmd: str | list) -> bool:
        """Check if command is allowed."""
        if isinstance(cmd, list):
            base_cmd = cmd[0]
        else:
            base_cmd = cmd.split()[0]
        
        # Check allowlist
        if self.allowed_commands:
            return any(
                base_cmd.endswith(allowed) 
                for allowed in self.allowed_commands
            )
        
        # Default deny dangerous commands
        dangerous = ["rm -rf", "mkfs", "dd", "curl", "wget"]
        return not any(d in cmd for d in dangerous)
    
    def run(
        self,
        cmd: str | list,
        timeout: Optional[int] = None,
        **kwargs
    ) -> subprocess.CompletedProcess:
        """Run command with sandbox restrictions."""
        if not self.validate_command(cmd):
            raise PermissionError(f"Command {cmd} is not allowed")
        
        timeout = min(timeout or self.max_timeout, self.max_timeout)
        
        # Add resource limits
        preexec_fn = None
        if self.deny_network:
            preexec_fn = self._block_network
        
        return subprocess.run(
            cmd,
            timeout=timeout,
            preexec_fn=preexec_fn,
            **kwargs
        )
    
    def _block_network(self):
        """Block network access via socket filtering (Linux)."""
        # Implementation uses seccomp-bpf on Linux
        # Or sandbox-exec on macOS
        pass
```

### 3.3 Permission Model

```toml
# user/config.toml

[security]
# Tool permission levels
auto_approve = ["read-only"]
require_confirmation = ["write"]
require_explicit_approval = ["execute", "self-modify"]

# Shell restrictions
max_shell_timeout_sec = 60
allowed_shell_patterns = [
    "git status",
    "git diff",
    "pytest",
    "cargo build",
    "npm test",
    "make",
    "ls",
    "cat",
    "grep",
    "find"
]
deny_shell_patterns = [
    "rm -rf /",
    "chmod -R 777",
    "curl.*\\|.*sh",
    "wget.*\\|.*sh"
]

# Self-modification thresholds
auto_promote_score_delta = 0.15
require_review_for_new_tools = true
max_overlay_changes_per_session = 5
```

### 3.4 Supply Chain Integrity

```python
# core/security/integrity.py

import hashlib
import json
from pathlib import Path

class CoreIntegrityChecker:
    """Verify core/ hasn't been tampered with."""
    
    def __init__(self, core_dir: str, manifest_path: str):
        self.core_dir = Path(core_dir)
        self.manifest_path = Path(manifest_path)
    
    def generate_manifest(self) -> dict:
        """Generate hash manifest for all core files."""
        manifest = {}
        for file in self.core_dir.rglob("*"):
            if file.is_file():
                relative = file.relative_to(self.core_dir)
                manifest[str(relative)] = self._hash_file(file)
        return manifest
    
    def verify(self) -> list[str]:
        """Verify core/ against manifest. Return list of mismatches."""
        if not self.manifest_path.exists():
            return ["Manifest missing"]
        
        manifest = json.loads(self.manifest_path.read_text())
        mismatches = []
        
        for rel_path, expected_hash in manifest.items():
            file_path = self.core_dir / rel_path
            if not file_path.exists():
                mismatches.append(f"Missing: {rel_path}")
            elif self._hash_file(file_path) != expected_hash:
                mismatches.append(f"Modified: {rel_path}")
        
        return mismatches
    
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
```

### 3.5 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Filesystem sandbox | `core/security/fs_sandbox.py` | P0 | Tools |
| Process sandbox | `core/security/process_sandbox.py` | P0 | Tools |
| Permission checker | `core/security/permissions.py` | P0 | Tools |
| Core integrity | `core/security/integrity.py` | P1 | None |
| Skill signing | `core/security/signing.py` | P2 | None |
| Security tests | `tests/test_security.py` | P1 | All security modules |

---

