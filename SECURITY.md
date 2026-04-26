# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately:

- **Email**: [Your email or preferred contact]
- **Discord**: DM the maintainers directly

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

Do **not** open a public issue for security vulnerabilities.

## Security Features

NoMan includes several security mechanisms:

1. **Filesystem Sandbox** — `core/security/fs_sandbox.py` restricts tool access to allowed directories only. Path traversal is blocked.
2. **Network Sandbox** — `core/security/network_sandbox.py` enforces an allowlist for network requests. Private IPs and cloud metadata endpoints are blocked by default.
3. **Tool Signing** — `core/security/signing.py` verifies tool integrity before execution.
4. **Safety Guardrails** — `core/security/safety_guardrails.py` provides additional checks including immutable tool protection and approval workflows.
5. **Emergency Stop** — Set `NOMAN_EMERGENCY_STOP=1` or call `noman emergency stop` to halt all agent operations immediately.

## Configuration Security

- API keys are stored in `~/.noman/config.toml` — never commit this file.
- `.env` files are gitignored.
- Memory data in `.noman/memory.db` may contain sensitive conversation data — treat it as sensitive.

## Dependency Security

Run `pip audit` or `uv pip check` to check for known vulnerabilities in dependencies.
