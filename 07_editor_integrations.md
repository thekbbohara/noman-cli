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

### 7.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| JSON-RPC server | `cli/server.py` | P1 | Orchestrator |
| Protocol spec | `docs/json-rpc-spec.md` | P1 | None |
| VS Code extension | `extensions/vscode/` | P2 | JSON-RPC server |
| Neovim plugin | `extensions/nvim/` | P2 | JSON-RPC server |
| Inline diff UI | `extensions/*/diff-viewer` | P2 | Editor APIs |

---

