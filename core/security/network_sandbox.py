"""Network sandbox: deny-all by default with explicit allowlist."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.errors import NetworkViolation

logger = logging.getLogger(__name__)

# IP ranges that should NEVER be contacted.
_PRIVATE_CIDRS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),        # unique local
    ipaddress.ip_network("fe80::/10"),       # link-local v6
]

# Metadata-service endpoints commonly used for cloud credential exfil.
_METADATA_HOSTS: set[str] = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.aws.internal",
}


@dataclass(frozen=True)
class NetworkPolicy:
    """Immutable network policy."""

    allowlist: set[str] = field(default_factory=set)
    deny_private: bool = True
    deny_metadata: bool = True


class NetworkSandbox:
    """Validate outbound network requests against a deny-all policy."""

    def __init__(self, policy: NetworkPolicy | None = None) -> None:
        self.policy = policy or NetworkPolicy()
        self._compiled = [re.compile(fnmatch_to_regex(p)) for p in self.policy.allowlist]

    def validate_url(self, url: str) -> None:
        """Raise NetworkViolation if *url* is not permitted."""
        parsed = urlparse(url)
        host = parsed.hostname or ""

        # 1. Metadata service guard
        if self.policy.deny_metadata and host in _METADATA_HOSTS:
            raise NetworkViolation(f"Metadata service access blocked: {host}")

        # 2. Private IP guard
        if self.policy.deny_private:
            try:
                addr = ipaddress.ip_address(host)
                for cidr in _PRIVATE_CIDRS:
                    if addr in cidr:
                        raise NetworkViolation(
                            f"Private IP {host} is blocked by network sandbox"
                        )
            except ValueError:
                pass  # not an IP, may be a hostname

        # 3. Allowlist guard (deny-all if not matched)
        if not self._compiled:
            raise NetworkViolation("Network access denied (empty allowlist)")

        for pattern in self._compiled:
            if pattern.match(host):
                logger.debug("Network OK: %s matches allowlist", host)
                return

        raise NetworkViolation(f"Host {host} not in network allowlist")


def fnmatch_to_regex(pattern: str) -> str:
    """Convert simple wildcard pattern to regex."""
    # Escape regex metacharacters except *
    parts = []
    for ch in pattern:
        if ch == "*":
            parts.append(".*")
        elif ch in {'.', '^', '$', '+', '?', '{', '}', '[', ']', '|', '(', ')', '\\'}:
            parts.append(re.escape(ch))
        else:
            parts.append(ch)
    return "".join(parts)
