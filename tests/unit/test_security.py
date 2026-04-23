"""Security tests: sandbox, signing, guardrails."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.errors import (
    NetworkViolation,
    PathTraversalError,
    SandboxViolation,
    SelfModificationError,
    ToolSignatureError,
)
from core.security.fs_sandbox import FilesystemSandbox
from core.security.network_sandbox import NetworkPolicy, NetworkSandbox
from core.security.signing import ToolSigner
from core.selfimprove.safety_guardrails import SafetyGuardrails


class TestFilesystemSandbox:
    def test_valid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            p = sandbox.validate_path("foo/bar.txt")
            assert p == Path(tmp) / "foo" / "bar.txt"

    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            with pytest.raises(PathTraversalError):
                sandbox.validate_path("../etc/passwd")

    def test_write_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp, allow_write=False)
            with pytest.raises(SandboxViolation):
                sandbox.validate_path("foo.txt", write=True)

    def test_blacklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FilesystemSandbox(tmp)
            with pytest.raises(SandboxViolation):
                sandbox.validate_path("/etc/passwd")


class TestNetworkSandbox:
    def test_empty_allowlist_blocks_all(self):
        sandbox = NetworkSandbox(NetworkPolicy(allowlist=set()))
        with pytest.raises(NetworkViolation):
            sandbox.validate_url("https://example.com")

    def test_allowlist_match(self):
        sandbox = NetworkSandbox(NetworkPolicy(allowlist={"*.openai.com"}))
        sandbox.validate_url("https://api.openai.com")

    def test_private_ip_blocked(self):
        sandbox = NetworkSandbox(NetworkPolicy(allowlist={"*"}))
        with pytest.raises(NetworkViolation):
            sandbox.validate_url("http://192.168.1.1")

    def test_metadata_service_blocked(self):
        sandbox = NetworkSandbox(NetworkPolicy(allowlist={"*"}))
        with pytest.raises(NetworkViolation):
            sandbox.validate_url("http://169.254.169.254/latest/meta-data")


class TestToolSigning:
    def test_generate_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            signer = ToolSigner()
            priv, pub = signer.generate_keypair(tmp)
            verifier = ToolSigner(pub)
            sig = signer.sign_tool("def hello(): pass", priv)
            assert verifier.verify_tool("def hello(): pass", sig)

    def test_tampered_source_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            signer = ToolSigner()
            priv, pub = signer.generate_keypair(tmp)
            verifier = ToolSigner(pub)
            sig = signer.sign_tool("def hello(): pass", priv)
            assert not verifier.verify_tool("def hello(): return 1", sig)

    def test_no_key_raises(self):
        signer = ToolSigner()
        with pytest.raises(ToolSignatureError):
            signer.verify_tool("x", "00")


class TestSafetyGuardrails:
    def test_immutable_path_blocked(self):
        g = SafetyGuardrails()
        with pytest.raises(SelfModificationError):
            g.validate_target("core/security/fs_sandbox.py")

    def test_mutable_path_allowed(self):
        g = SafetyGuardrails()
        g.validate_target("overlay/prompts/planner.md")

    def test_immutable_tool_blocked(self):
        g = SafetyGuardrails()
        with pytest.raises(SelfModificationError):
            g.validate_tool_name("rollback")

    def test_approval_required(self):
        g = SafetyGuardrails()
        assert g.requires_approval("new_tool")
        assert not g.requires_approval("prompt_tweak", diff_percent=10)
        assert g.requires_approval("prompt_replace", diff_percent=10)
