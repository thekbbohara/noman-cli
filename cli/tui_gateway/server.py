import json
import sys
from typing import Any, Callable

class GatewayServer:
    def __init__(self):
        self.handlers: dict[str, Callable] = {}
    
    def register(self, method: str | Callable, handler: Callable = None):
        if callable(method):
            self.handlers[method.__name__] = method
            return method
        self.handlers[method] = handler
        return handler
    
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
    from core.orchestrator.core import Orchestrator
    from cli.main import _create_orchestrator, _load_config
    from argparse import Namespace
    args = Namespace(provider=None, debug=False, max_calls=None)
    orch = _create_orchestrator(args)
    if orch is None:
        raise RuntimeError("Failed to create orchestrator")
    import asyncio
    result = asyncio.run(orch.run(params.get("message", "")))
    return {"response": result}

@server.register
def get_sessions(params):
    from core.gateway.router import SessionManager
    mgr = SessionManager()
    return {"sessions": mgr.list_sessions()}

if __name__ == "__main__":
    server.run()