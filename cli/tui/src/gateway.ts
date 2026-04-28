import { spawn } from "child_process";

interface Session {
  id: string;
  name: string;
  created: number;
}

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

    return new Promise((resolve, reject) => {
      this.proc.stdout!.once("data", (data) => {
        try {
          const response = JSON.parse(data.toString());
          resolve(response.result);
        } catch (e) {
          reject(e);
        }
      });
    });
  }

  async chat(message: string): Promise<string> {
    const result = await this.call("chat", { message }) as { response: string };
    return result.response;
  }

  async getSessions(): Promise<Session[]> {
    const result = await this.call("get_sessions") as { sessions: Session[] };
    return result.sessions;
  }
}