"""Ed25519 tool signing to prevent arbitrary code execution."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core.errors import ToolSignatureError

logger = logging.getLogger(__name__)


class ToolSigner:
    """Sign and verify tool definitions using Ed25519."""

    def __init__(self, public_key_path: str | Path | None = None) -> None:
        self._pub: Ed25519PublicKey | None = None
        if public_key_path:
            pem = Path(public_key_path).read_bytes()
            self._pub = serialization.load_pem_public_key(pem)

    def generate_keypair(self, output_dir: str | Path) -> tuple[Path, Path]:
        """Generate a new Ed25519 keypair and write to disk."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()

        priv_path = out / "tool_signing_key.pem"
        pub_path = out / "tool_signing_key.pub"

        priv_path.write_bytes(
            priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        pub_path.write_bytes(
            pub.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        logger.info("Generated tool signing keys in %s", out)
        return priv_path, pub_path

    def sign_tool(self, tool_source: str, private_key_path: str | Path) -> str:
        """Return a base64-encoded signature of *tool_source*."""
        priv_pem = Path(private_key_path).read_bytes()
        priv = serialization.load_pem_private_key(priv_pem, password=None)
        sig = priv.sign(tool_source.encode())
        return sig.hex()

    def verify_tool(self, tool_source: str, signature: str) -> bool:
        """Return True if *signature* is valid for *tool_source*."""
        if self._pub is None:
            raise ToolSignatureError("No public key configured for tool verification")
        try:
            self._pub.verify(bytes.fromhex(signature), tool_source.encode())
            return True
        except InvalidSignature:
            return False
