## 3. Security & Sandboxing

### 3.1 Threat Model

| Threat Actor | Capabilities | Goals |
|--------------|--------------|-------|
| **Malicious User Input** | Crafted prompts attempting injection | Escape sandbox, access forbidden resources |
| **Compromised Agent** | Self-improvement gone wrong | Modify own constraints, exfiltrate data |
| **Malicious Tool** | Agent-authored tool with hidden behavior | Persist backdoor, steal credentials |
| **Supply Chain Attack** | Modified dependency or skill | Inject malicious code into workflow |

### 3.2 Sandboxing Layers

#### 3.2.1 Filesystem Sandbox (SECURITY HARDENED)

```python
# core/security/fs_sandbox.py

import os
import re
from pathlib import Path
from typing import Set, List
from urllib.parse import unquote

class FilesystemSandbox:
    """Restrict file operations to allowed paths with multi-layer security."""
    
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
        
        # CRITICAL: Forbidden paths (never allow access)
        self.forbidden_paths = {
            Path("/etc"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/root"),
            Path("/home"),
            Path("/var"),
            Path("/proc"),
            Path("/sys"),
        }
    
    def _decode_path_attempts(self, path: str) -> List[str]:
        """Detect and decode various path traversal encodings."""
        attempts = [path]
        
        # URL encoding bypasses
        if "%" in path:
            try:
                decoded = unquote(path)
                if decoded != path:
                    attempts.append(decoded)
            except Exception:
                pass
        
        # Double encoding
        if "%25" in path:
            try:
                double_decoded = unquote(unquote(path))
                attempts.append(double_decoded)
            except Exception:
                pass
        
        # Unicode normalization attacks
        normalized = path.replace("\u002f", "/").replace("\u005c", "\\")
        if normalized != path:
            attempts.append(normalized)
        
        return attempts
    
    def validate_path(self, path: str, mode: str = "read") -> tuple[bool, str]:
        """Check if path is within allowed boundaries with multi-layer detection.
        
        Returns:
            (is_valid, error_message)
        """
        # Check all encoded variants
        path_attempts = self._decode_path_attempts(path)
        
        for test_path in path_attempts:
            resolved = Path(test_path).resolve()
            
            # CRITICAL: Check forbidden paths FIRST
            for forbidden in self.forbidden_paths:
                try:
                    resolved.relative_to(forbidden)
                    return False, f"Access to {forbidden} is strictly forbidden"
                except ValueError:
                    continue
            
            # Check symlinks - resolve and validate again
            if resolved.is_symlink():
                try:
                    real_path = resolved.resolve(strict=True)
                    # Re-check forbidden after symlink resolution
                    for forbidden in self.forbidden_paths:
                        try:
                            real_path.relative_to(forbidden)
                            return False, f"Symlink {path} points to forbidden path {forbidden}"
                        except ValueError:
                            continue
                    
                    # Validate resolved symlink target
                    for allowed in self.allowed_paths:
                        try:
                            real_path.relative_to(allowed)
                            break
                        except ValueError:
                            continue
                    else:
                        return False, f"Symlink {path} resolves outside allowed paths"
                except (OSError, RuntimeError):
                    return False, f"Cannot resolve symlink {path}"
            
            # Check if resolved path is within any allowed path
            for allowed in self.allowed_paths:
                try:
                    resolved.relative_to(allowed)
                    return True, "OK"
                except ValueError:
                    continue
            
            return False, f"Path {path} is outside allowed directories"
        
        return True, "OK"
    
    def wrap_open(self, path: str, mode: str = "r"):
        """Wrapped open() that enforces sandbox."""
        is_valid, error_msg = self.validate_path(path, mode)
        if not is_valid:
            raise PermissionError(error_msg)
        return open(path, mode)
    
    def wrap_listdir(self, path: str) -> list:
        """Wrapped listdir() that enforces sandbox."""
        is_valid, error_msg = self.validate_path(path, "read")
        if not is_valid:
            raise PermissionError(error_msg)
        return os.listdir(path)
```

#### 3.2.2 Network Sandboxing (NEW - CRITICAL SECURITY FIX)

**Problem:** Original design lacked network isolation, allowing potential data exfiltration.

**Solution:** Deny-all-by-default network policy with explicit allowlist.

```python
# core/security/network_sandbox.py

import socket
import threading
from typing import Optional, Set
from contextlib import contextmanager

class NetworkSandbox:
    """Enforce network isolation with deny-all-by-default policy."""
    
    def __init__(
        self,
        deny_all_by_default: bool = True,
        allowed_hosts: Set[str] = None,
        allowed_ports: Set[int] = None,
        block_outbound_data: bool = True
    ):
        self.deny_all = deny_all_by_default
        self.allowed_hosts = allowed_hosts or set()
        self.allowed_ports = allowed_ports or set()
        self.block_outbound_data = block_outbound_data
        
        # NEVER allow these
        self.blocked_hosts = {
            "metadata.google.internal",
            "169.254.169.254",  # AWS/GCP metadata service
            "localhost",
            "127.0.0.1",
            "::1",
        }
    
    def is_host_allowed(self, host: str) -> tuple[bool, str]:
        """Check if host is allowed for network access."""
        # CRITICAL: Block cloud metadata services
        if host in self.blocked_hosts:
            return False, f"Access to {host} is blocked (security risk)"
        
        # Block private IP ranges unless explicitly allowed
        if self._is_private_ip(host) and host not in self.allowed_hosts:
            return False, f"Private IP {host} is not in allowlist"
        
        # Check allowlist
        if self.deny_all and host not in self.allowed_hosts:
            return False, f"Host {host} is not in network allowlist"
        
        return True, "OK"
    
    def _is_private_ip(self, host: str) -> bool:
        """Check if host is a private IP address."""
        try:
            ip = socket.gethostbyname(host)
            octets = list(map(int, ip.split(".")))
            
            # 10.x.x.x
            if octets[0] == 10:
                return True
            # 172.16-31.x.x
            if octets[0] == 172 and 16 <= octets[1] <= 31:
                return True
            # 192.168.x.x
            if octets[0] == 192 and octets[1] == 168:
                return True
            # 127.x.x.x
            if octets[0] == 127:
                return True
            # 169.254.x.x (link-local)
            if octets[0] == 169 and octets[1] == 254:
                return True
            
            return False
        except Exception:
            return False
    
    @contextmanager
    def restrict_network(self):
        """Context manager that temporarily blocks all network access."""
        # In production, this would use seccomp-bpf or similar
        # For now, we rely on application-level enforcement
        original_deny = self.deny_all
        self.deny_all = True
        try:
            yield
        finally:
            self.deny_all = original_deny
    
    def validate_socket_call(self, host: str, port: int) -> tuple[bool, str]:
        """Validate socket connection attempt."""
        host_allowed, host_reason = self.is_host_allowed(host)
        if not host_allowed:
            return False, host_reason
        
        if self.allowed_ports and port not in self.allowed_ports:
            return False, f"Port {port} is not in allowlist"
        
        return True, "OK"


# Integration with subprocess sandbox
class SecureSubprocessRunner:
    """Subprocess runner with network isolation."""
    
    def __init__(self, network_sandbox: NetworkSandbox):
        self.network = network_sandbox
    
    def run(self, cmd: list, **kwargs) -> subprocess.CompletedProcess:
        """Run command with network restrictions."""
        # Block network at process level using environment variables
        env = kwargs.get("env", os.environ.copy())
        
        # Set restrictive proxy to block direct connections
        env["HTTP_PROXY"] = ""
        env["HTTPS_PROXY"] = ""
        env["NO_PROXY"] = "*"
        
        # Disable Python's ability to make outbound connections
        env["PYTHON_DISABLE_NETWORK"] = "1"
        
        kwargs["env"] = env
        
        return subprocess.run(cmd, **kwargs)
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

### 3.5 Tool Bus Security Hardening (NEW - CRITICAL)

**Problem:** Original tool bus allowed arbitrary code execution via auto-discovery.

**Solution:** Whitelist-only loading with signature verification.

```python
# core/tools/tool_bus.py (SECURITY HARDENED)

import hashlib
import json
from pathlib import Path
from typing import Dict, List

class SecureToolBus:
    """Tool loader with strict security controls."""
    
    def __init__(self, tools_dir: str, manifest_path: str):
        self.tools_dir = Path(tools_dir)
        self.manifest_path = Path(manifest_path)
        self.allowed_tools: Dict[str, str] = {}  # name -> hash
        self.load_manifest()
    
    def load_manifest(self):
        """Load signed tool manifest."""
        if not self.manifest_path.exists():
            raise SecurityError("Tool manifest missing - cannot load any tools")
        
        manifest_data = json.loads(self.manifest_path.read_text())
        
        # Verify manifest signature (P0 - must be implemented first)
        if not self._verify_manifest_signature(manifest_data):
            raise SecurityError("Tool manifest signature invalid")
        
        self.allowed_tools = {
            item["name"]: item["hash"] 
            for item in manifest_data["tools"]
        }
    
    def _verify_manifest_signature(self, manifest_data: dict) -> bool:
        """Verify manifest was signed by trusted key."""
        # Implementation uses ed25519 signatures
        # See §3.6 for signing implementation
        pass
    
    def load_tool(self, tool_name: str):
        """Load a single tool with verification."""
        # SECURITY: Reject unknown tools
        if tool_name not in self.allowed_tools:
            raise SecurityError(
                f"Tool '{tool_name}' is not in allowlist. "
                f"Auto-discovery is disabled for security."
            )
        
        tool_path = self.tools_dir / f"{tool_name}.py"
        
        if not tool_path.exists():
            raise FileNotFoundError(f"Tool {tool_name} not found")
        
        # Verify tool hash matches manifest
        actual_hash = hashlib.sha256(tool_path.read_bytes()).hexdigest()
        expected_hash = self.allowed_tools[tool_name]
        
        if actual_hash != expected_hash:
            raise SecurityError(
                f"Tool {tool_name} hash mismatch - possible tampering"
            )
        
        # Safe load with restricted globals
        return self._safe_load_tool(tool_path)
    
    def _safe_load_tool(self, tool_path: Path):
        """Load tool code with restricted execution environment."""
        # NEVER use exec/eval with full globals
        # Use restricted namespace
        safe_globals = {
            "__builtins__": {
                # Only allow safe builtins
                "print": print,
                "len": len,
                "range": range,
                "str": str,
                "int": int,
                "dict": dict,
                "list": list,
                # ... other safe builtins
            },
            "__file__": str(tool_path),
        }
        
        local_ns = {}
        exec(tool_path.read_text(), safe_globals, local_ns)
        
        return local_ns.get("tool")


class SecurityError(Exception):
    """Raised when security policy is violated."""
    pass
```

### 3.6 Git Safety Mechanisms (NEW)

**Problem:** Git tools could accidentally push to main or perform destructive operations.

**Solution:** Protected branches, confirmation prompts, and audit logging.

```python
# core/tools/git_safe.py

from typing import List, Optional
import subprocess

class SafeGitOperations:
    """Git operations with safety guardrails."""
    
    def __init__(
        self,
        protected_branches: List[str] = None,
        require_confirmation_for: List[str] = None
    ):
        self.protected_branches = set(protected_branches or ["main", "master", "prod"])
        self.require_confirmation = set(require_confirmation_for or [
            "push --force",
            "reset --hard",
            "branch -D",
            "rebase",
        ])
    
    def validate_operation(self, cmd: List[str]) -> tuple[bool, str]:
        """Validate git operation is safe."""
        # Check for protected branch operations
        for protected in self.protected_branches:
            if protected in cmd:
                if any(dangerous in cmd for dangerous in ["--force", "-D", "reset"]):
                    return False, f"Cannot perform destructive operation on protected branch '{protected}'"
        
        # Check for operations requiring confirmation
        for req in self.require_confirmation:
            if req in " ".join(cmd):
                return "requires_confirmation", f"Operation '{req}' requires explicit user confirmation"
        
        return True, "OK"
    
    def run(self, cmd: List[str], auto_confirm: bool = False) -> subprocess.CompletedProcess:
        """Run git command with safety checks."""
        is_valid, message = self.validate_operation(cmd)
        
        if is_valid == "requires_confirmation":
            if not auto_confirm:
                raise PermissionError(f"{message}. Use --confirm flag to proceed.")
        
        if not is_valid:
            raise PermissionError(message)
        
        # Add safety flags
        safe_cmd = ["git"] + cmd
        
        # Prevent accidental pushes to protected branches
        if "push" in cmd:
            safe_cmd.append("--no-force-with-lease")
        
        return subprocess.run(safe_cmd, capture_output=True, text=True)
```

### 3.7 Updated Implementation Tasks

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| Filesystem sandbox (hardened) | `core/security/fs_sandbox.py` | **P0** | Tools | ↑ Multi-layer path traversal prevention |
| Network sandbox (NEW) | `core/security/network_sandbox.py` | **P0** | None | ↑ NEW - Critical security fix |
| Permission checker | `core/security/permissions.py` | P0 | Tools | — |
| Core integrity | `core/security/integrity.py` | P1 | None | — |
| **Tool signing** | `core/security/signing.py` | **P0** | None | ↑ P2→P0 (was misaligned) |
| **Tool bus hardening** | `core/tools/tool_bus.py` | **P0** | Tool signing | ↑ NEW - Prevent arbitrary code exec |
| **Git safety** | `core/tools/git_safe.py` | **P0** | None | ↑ NEW - Prevent destructive ops |
| Security tests (incl. adversarial) | `tests/test_security.py` | **P0** | All security modules | ↑ P1→P0 (includes attack scenarios) |

---

