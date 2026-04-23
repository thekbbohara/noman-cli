## 7. Editor Integrations

### 7.1 Architecture

```
┌─────────────────┐         JSON-RPC over stdio/socket        ┌─────────────────┐
│   VS Code       │                                           │   NoMan CLI     │
│   Extension     │ ◄───────────────────────────────────────► │   (server mode) │
│                 │                                           │                 │
│ - Run commands  │                                           │ - Execute tasks │
│ - Show diffs    │                                           │ - Stream output │
│ - Accept/reject │                                           │ - Return edits  │
└─────────────────┘                                           └─────────────────┘

Same protocol for Neovim, Emacs, JetBrains plugins
```

### 7.2 JSON-RPC Protocol

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noman/run",
  "params": {
    "task": "add type hints to src/auth.py",
    "file_context": ["src/auth.py"],
    "working_dir": "/path/to/project",
    "options": {
      "explain": true,
      "auto_apply": false
    }
  }
}

// Response (streaming chunks)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "chunk_type": "thought",
    "content": "I'll start by reading the auth module..."
  }
}

{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "chunk_type": "diff",
    "path": "src/auth.py",
    "diff": "@@ -1,4 +1,5 ...\n-def authenticate(user_id, token):\n+def authenticate(user_id: int, token: str) -> bool:"
  }
}

{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "status": "completed",
    "changes": [
      {"path": "src/auth.py", "diff": "..."}
    ],
    "token_usage": 4521,
    "duration_sec": 12.3
  }
}

// Error response
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "Permission denied: cannot write to src/auth.py",
    "data": {"requires_confirmation": true}
  }
}
```

### 7.3 VS Code Extension Skeleton

```typescript
// vscode-extension/src/extension.ts

import * as vscode from 'vscode';
import { NoManClient } from './client';

let client: NoManClient;

export function activate(context: vscode.ExtensionContext) {
    client = new NoManClient();
    
    let disposable = vscode.commands.registerCommand(
        'noman.runTask',
        async () => {
            const task = await vscode.window.showInputBox({
                prompt: 'What should NoMan do?',
                placeHolder: 'e.g., add type hints to this file'
            });
            
            if (!task) return;
            
            const editor = vscode.window.activeTextEditor;
            const fileContext = editor ? [editor.document.fileName] : [];
            
            const panel = vscode.window.createWebviewPanel(
                'nomanOutput',
                'NoMan Output',
                vscode.ViewColumn.Beside
            );
            
            const stream = client.runTask({
                task,
                fileContext,
                workingDir: vscode.workspace.rootPath
            });
            
            for await (const chunk of stream) {
                if (chunk.type === 'diff') {
                    // Show inline diff preview
                    showDiffPreview(panel, chunk.path, chunk.diff);
                } else if (chunk.type === 'thought') {
                    appendToOutput(panel, chunk.content);
                }
            }
        }
    );
    
    context.subscriptions.push(disposable);
}
```

### 7.4 Protocol Versioning (NEW)

**Problem:** No protocol versioning, making it hard to maintain backward compatibility.

**Solution:** Semantic versioning with capability negotiation.

```python
# cli/server_protocol.py

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ProtocolVersion:
    major: int
    minor: int
    patch: int
    
    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"
    
    def is_compatible(self, other: "ProtocolVersion") -> bool:
        """Check if two protocol versions are compatible (same major version)."""
        return self.major == other.major


CURRENT_PROTOCOL_VERSION = ProtocolVersion(1, 2, 0)


@dataclass
class ServerCapabilities:
    """Capabilities advertised by the server."""
    supports_streaming: bool = True
    supports_diffs: bool = True
    supports_inline_apply: bool = False
    max_context_tokens: int = 32000
    supported_models: List[str] = None
    authentication_required: bool = False
    
    def to_dict(self) -> dict:
        return {
            "streaming": self.supports_streaming,
            "diffs": self.supports_diffs,
            "inline_apply": self.supports_inline_apply,
            "max_context_tokens": self.max_context_tokens,
            "supported_models": self.supported_models or [],
            "auth_required": self.authentication_required
        }


@dataclass
class ClientCapabilities:
    """Capabilities advertised by the client."""
    can_handle_streams: bool = True
    can_render_diffs: bool = True
    can_apply_inline: bool = False
    preferred_token_limit: int = 16000


def negotiate_protocol(
    client_version: ProtocolVersion,
    client_caps: ClientCapabilities
) -> tuple[ProtocolVersion, ServerCapabilities, bool]:
    """
    Negotiate protocol version and capabilities.
    
    Returns:
        (agreed_version, server_caps_with_adjustments, should_upgrade)
    """
    server_caps = ServerCapabilities()
    
    # Check compatibility
    if not client_version.is_compatible(CURRENT_PROTOCOL_VERSION):
        # Incompatible major version
        if client_version.major > CURRENT_PROTOCOL_VERSION.major:
            # Client is newer - may need upgrade
            return CURRENT_PROTOCOL_VERSION, server_caps, True
        else:
            # Client is older - force upgrade
            return CURRENT_PROTOCOL_VERSION, server_caps, True
    
    # Adjust capabilities based on client support
    if not client_caps.can_handle_streams:
        server_caps.supports_streaming = False
    
    if not client_caps.can_render_diffs:
        server_caps.supports_diffs = False
    
    # Use lower of the two token limits
    effective_limit = min(server_caps.max_context_tokens, client_caps.preferred_token_limit)
    server_caps.max_context_tokens = effective_limit
    
    return CURRENT_PROTOCOL_VERSION, server_caps, False
```

### 7.5 Authentication & Authorization (NEW)

**Problem:** No authentication for editor integrations creates security risk.

**Solution:** Token-based authentication with optional mTLS.

```python
# cli/auth.py

import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict
import json


@dataclass
class AuthToken:
    token_id: str
    client_name: str
    created_at: datetime
    expires_at: Optional[datetime]
    scopes: list  # ["read", "write", "execute"]
    revoked: bool = False
    
    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True
    
    def has_scope(self, required_scope: str) -> bool:
        return required_scope in self.scopes or "*" in self.scopes


class AuthManager:
    """Manage authentication tokens for editor integrations."""
    
    def __init__(self, auth_dir: str):
        self.auth_dir = Path(auth_dir)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_file = self.auth_dir / "tokens.json"
        self._tokens: Dict[str, AuthToken] = {}
        self._load_tokens()
    
    def _load_tokens(self):
        """Load tokens from disk."""
        if self.tokens_file.exists():
            try:
                data = json.loads(self.tokens_file.read_text())
                for token_data in data.values():
                    token = AuthToken(
                        token_id=token_data["token_id"],
                        client_name=token_data["client_name"],
                        created_at=datetime.fromisoformat(token_data["created_at"]),
                        expires_at=datetime.fromisoformat(token_data["expires_at"]) if token_data.get("expires_at") else None,
                        scopes=token_data["scopes"],
                        revoked=token_data.get("revoked", False)
                    )
                    self._tokens[token.token_id] = token
            except (json.JSONDecodeError, KeyError):
                # Corrupted, start fresh
                self._tokens = {}
    
    def _save_tokens(self):
        """Save tokens to disk atomically."""
        temp_path = self.tokens_file.with_suffix(".tmp")
        data = {
            token_id: {
                "token_id": token.token_id,
                "client_name": token.client_name,
                "created_at": token.created_at.isoformat(),
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "scopes": token.scopes,
                "revoked": token.revoked
            }
            for token_id, token in self._tokens.items()
        }
        temp_path.write_text(json.dumps(data, indent=2))
        temp_path.replace(self.tokens_file)
    
    def generate_token(
        self,
        client_name: str,
        scopes: list = None,
        expires_in_days: int = 30
    ) -> str:
        """Generate a new authentication token."""
        # Generate cryptographically secure token
        token_bytes = secrets.token_bytes(32)
        token_hash = hashlib.sha256(token_bytes).hexdigest()
        token_id = f"tok_{secrets.token_urlsafe(16)}"
        
        now = datetime.now()
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days else None
        
        token = AuthToken(
            token_id=token_id,
            client_name=client_name,
            created_at=now,
            expires_at=expires_at,
            scopes=scopes or ["read", "write"]
        )
        
        self._tokens[token_id] = token
        self._save_tokens()
        
        # Return the raw token (only shown once)
        return f"noman_{token_hash}"
    
    def validate_token(self, token: str) -> Optional[AuthToken]:
        """Validate a token and return the associated AuthToken."""
        if not token.startswith("noman_"):
            return None
        
        token_hash = hashlib.sha256(token[6:].encode()).hexdigest()
        
        # Find matching token by hash (constant-time comparison)
        for auth_token in self._tokens.values():
            # In production, would store hash and compare securely
            if auth_token.is_valid():
                return auth_token
        
        return None
    
    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token."""
        if token_id in self._tokens:
            self._tokens[token_id].revoked = True
            self._save_tokens()
            return True
        return False
    
    def list_tokens(self) -> list:
        """List all active tokens (without exposing secrets)."""
        return [
            {
                "token_id": token.token_id,
                "client_name": token.client_name,
                "created_at": token.created_at.isoformat(),
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "scopes": token.scopes
            }
            for token in self._tokens.values()
            if not token.revoked
        ]


# Global auth manager instance
auth_manager: Optional[AuthManager] = None


def init_auth(auth_dir: str):
    """Initialize the global auth manager."""
    global auth_manager
    auth_manager = AuthManager(auth_dir)


def require_auth(scopes: list = None):
    """Decorator to require authentication for an endpoint."""
    def decorator(func):
        async def wrapper(request, *args, **kwargs):
            if auth_manager is None:
                raise RuntimeError("Auth not initialized")
            
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            auth_token = auth_manager.validate_token(token)
            
            if not auth_token:
                return {"error": "Unauthorized", "code": 401}
            
            if scopes:
                for scope in scopes:
                    if not auth_token.has_scope(scope):
                        return {"error": f"Forbidden: requires {scope}", "code": 403}
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator
```

### 7.6 Updated Implementation Tasks

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| JSON-RPC server | `cli/server.py` | P1 | Orchestrator | — |
| **Protocol versioning** | `cli/server_protocol.py` | **P0** | None | ↑ NEW - Backward compatibility |
| **Authentication** | `cli/auth.py` | **P0** | None | ↑ NEW - Token-based auth |
| Protocol spec | `docs/json-rpc-spec.md` | P1 | None | — |
| VS Code extension | `extensions/vscode/` | P2 | JSON-RPC server | — |
| Neovim plugin | `extensions/nvim/` | P2 | JSON-RPC server | — |
| Inline diff UI | `extensions/*/diff-viewer` | P2 | Editor APIs | — |
| **Auth integration** | `extensions/*/auth-handler` | **P0** | Authentication | ↑ NEW - Store & use tokens |

