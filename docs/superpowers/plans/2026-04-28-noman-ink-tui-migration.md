# Nomank Ink TUI Implementation Plan

**Goal:** Migrate noman CLI from Python(Textual) to TypeScript(Ink) following Hermes architecture

**Architecture:** 
- TypeScript/Ink TUI running as subprocess
- Python gateway server via JSON-RPC over stdin/stdout
- Same session/database as Python backend

**Tech Stack:** TypeScript, Ink (React-based), React, Node.js ≥20

---

### Task 1: Initialize TypeScript Package

**Files:**
- Create: `cli/tui/package.json`
- Create: `cli/tui/tsconfig.json`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "noman-tui",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.tsx",
    "build": "tsc",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "react": "^18.2.0",
    "ink": "^5.0.0",
    "meow": "^10.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "tsx": "^4.0.0",
    "typescript": "^5.0.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "jsx": "react",
    "strict": true,
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 3: Commit**

```bash
git add cli/tui/ && git commit -m "feat(tui): initialize TypeScript package with Ink"
```

---

### Task 2: Create JSON-RPC Gateway Server

**Files:**
- Create: `cli/tui_gateway/server.py`
- Modify: `cli/main.py`

- [ ] **Step 1: Create gateway server**

```python
import json
import sys
from typing import Any, Callable

class GatewayServer:
    def __init__(self):
        self.handlers: dict[str, Callable] = {}
    
    def register(self, method: str, handler: Callable):
        self.handlers[method] = handler
    
    def handle_request(self, request: dict) -> dict:
        method = request.get("method")
        params = request.get("params", {})
        id = request.get("id")
        
        if method not in self.handlers:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}, "id": id}
        
        try:
            result = self.handlers[method](params)
            return {"result": result, "id": id}
        except Exception as e:
            return {"error": {"code": -32603, "message": str(e)}, "id": id}
    
    def run(self):
        for line in sys.stdin:
            if not line.strip():
                continue
            request = json.loads(line)
            response = self.handle_request(request)
            print(json.dumps(response), flush=True)

server = GatewayServer()

@server.register
def chat(params):
    from core.orchestrator import orchestrate
    return {"response": orchestrate(params.get("message"))}

@server.register
def get_sessions(params):
    from core.session import SessionManager
    mgr = SessionManager()
    return {"sessions": mgr.list_sessions()}

if __name__ == "__main__":
    server.run()
```

- [ ] **Step 2: Add TUI launch to main.py**

```python
def _launch_tui():
    import subprocess
    import os
    
    tui_dir = Path(__file__).parent / "tui_gateway"
    if (tui_dir / "dist" / "entry.js").exists():
        entry = tui_dir / "dist" / "entry.js"
    else:
        entry = tui_dir.parent / "tui" / "src" / "index.tsx"
    
    return subprocess.Popen(
        ["npx", "tsx", str(entry)] if entry.suffix == ".tsx" else ["node", str(entry)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "NOMAN_GATEWAY": "1"}
    )
```

- [ ] **Step 3: Commit**

```bash
git add cli/tui_gateway/ cli/main.py && git commit -m "feat(tui): add JSON-RPC gateway server"
```

---

### Task 3: Build Ink TUI Components

**Files:**
- Create: `cli/tui/src/index.tsx`
- Create: `cli/tui/src/components/App.tsx`
- Create: `cli/tui/src/components/Input.tsx`
- Create: `cli/tui/src/components/Output.tsx`

- [ ] **Step 1: Create entry point**

```tsx
#!/usr/bin/env node
import React from "react";
import { render } from "ink";
import App from "./components/App.js";

render(<App />);
```

- [ ] **Step 2: Create App component**

```tsx
import React, { useState } from "react";
import { Box, Text } from "ink";
import Input from "./Input.js";
import Output from "./Output.js";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (text: string) => {
    setMessages([...messages, { role: "user", content: text }]);
    setIsLoading(true);
    
    const response = await fetch("/dev/stdin", {
      method: "POST",
      body: JSON.stringify({ method: "chat", params: { message: text }, id: 1 }),
    });
    const data = await response.json();
    
    setMessages([...messages, { role: "user", content: text }, { role: "assistant", content: data.result?.response ?? "" }]);
    setIsLoading(false);
  };

  return (
    <Box flexDirection="column" height={process.stdout.rows - 1}>
      <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1}>
        <Output messages={messages} />
      </Box>
      <Input onSubmit={handleSubmit} isLoading={isLoading} />
    </Box>
  );
}
```

- [ ] **Step 3: Create Input component**

```tsx
import React, { useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";

interface Props {
  onSubmit: (text: string) => void;
  isLoading: boolean;
}

export default function Input({ onSubmit, isLoading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim()) return;
    onSubmit(value);
    setValue("");
  };

  return (
    <Box borderStyle="round" borderColor="green" paddingX={1}>
      <Text bold green>{">"} </Text>
      <TextInput value={value} onChange={setValue} onSubmit={handleSubmit} isDisabled={isLoading} />
      {isLoading && <Text dim> (thinking...)</Text>}
    </Box>
  );
}
```

- [ ] **Step 4: Create Output component**

```tsx
import React from "react";
import { Box, Text } from "ink";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  messages: Message[];
}

export default function Output({ messages }: Props) {
  return (
    <Box flexDirection="column">
      {messages.map((msg, i) => (
        <Box key={i} flexDirection="column">
          <Text bold cyan>{msg.role === "user" ? "You:" : "Assistant:"}</Text>
          <Text>{msg.content}</Text>
        </Box>
      ))}
    </Box>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add cli/tui/src/ && git commit -m "feat(tui): add Ink components (App, Input, Output)"
```

---

### Task 4: Add Keybindings & Command Palette

**Files:**
- Modify: `cli/tui/src/components/App.tsx`
- Create: `cli/tui/src/components/CommandPalette.tsx`

- [ ] **Step 1: Add keybinding support to App**

```tsx
import { useInput } from "ink";

export default function App() {
  // Add to existing App:
  useInput((input, key) => {
    if (key.ctrl && input === "c") {
      // Copy output - implement OSC52
    }
    if (input === "/" && !inputMode) {
      // Open command palette
    }
  });
}
```

- [ ] **Step 2: Create CommandPalette component**

```tsx
import React, { useState } from "react";
import { Box, Text } from "ink";
import Select from "ink-select-input";

const COMMANDS = [
  { label: "New Session", value: "new" },
  { label: "Resume Session", value: "resume" },
  { label: "Model: Anthropic", value: "model:anthropic" },
  { label: "Model: OpenAI", value: "model:openai" },
];

export default function CommandPalette({ onSelect }: { onSelect: (cmd: string) => void }) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1}>
      <Text bold>Command Palette</Text>
      <Select items={COMMANDS} onSelect={(item) => onSelect(item.value)} />
    </Box>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add cli/tui/src/ && git commit -m "feat(tui): add keybindings and command palette"
```

---

### Task 5: Mirror Python TUI Features

**Files:**
- Modify: `cli/tui/src/components/App.tsx`
- Create: `cli/tui/src/gateway.ts`

- [ ] **Step 1: Create gateway client**

```typescript
import { spawn } from "child_process";

export class GatewayClient {
  private proc: ReturnType<spawn>;
  
  constructor() {
    this.proc = spawn("python3", ["-m", "cli.tui_gateway.server"], {
      stdio: ["pipe", "pipe", "pipe"],
    });
  }
  
  async call(method: string, params?: object): Promise<unknown> {
    const request = { method, params, id: Date.now() };
    this.proc.stdin!.write(JSON.stringify(request) + "\n");
    
    return new Promise((resolve) => {
      this.proc.stdout!.once("data", (data) => {
        const response = JSON.parse(data.toString());
        resolve(response.result);
      });
    });
  }
  
  async chat(message: string): Promise<string> {
    const result = await this.call("chat", { message }) as { response: string };
    return result.response;
  }
}
```

- [ ] **Step 2: Integrate session management**

```typescript
async getSessions(): Promise<Session[]> {
  const result = await this.call("get_sessions") as { sessions: Session[] };
  return result.sessions;
}
```

- [ ] **Step 3: Commit**

```bash
git add cli/tui/src/ && git commit -m "feat(tui): add gateway client and session management"
```

---

### Task 6: Test & Verify

**Files:**
- Test: `cli/tui/__tests__/`

- [ ] **Step 1: Run TUI locally**

```bash
cd cli/tui && npm install && npm run dev
```

- [ ] **Step 2: Verify basic chat flow works**

- [ ] **Step 3: Test command palette (/)**

- [ ] **Step 4: Commit**

```bash
git add cli/tui/__tests__/ && git commit -m "test(tui): add basic TUI tests"
```