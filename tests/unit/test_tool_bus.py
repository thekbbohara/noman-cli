"""Tests for the hardened Tool Bus."""

import tempfile

import pytest

from core.errors import ToolNotFoundError, ToolSignatureError, ToolValidationError
from core.security.fs_sandbox import FilesystemSandbox
from core.security.signing import ToolSigner
from core.tools.bus import Tool, ToolBus


@pytest.mark.asyncio
async def test_tool_execution():
    bus = ToolBus(fs_sandbox=FilesystemSandbox("/tmp"))
    bus.register(Tool(
        name="add", description="add two numbers",
        parameters={"required": ["a", "b"]},
        handler=lambda a, b: a + b,
    ))
    result = await bus.execute("add", {"a": 2, "b": 3})
    assert result == 5


@pytest.mark.asyncio
async def test_missing_tool():
    bus = ToolBus(fs_sandbox=FilesystemSandbox("/tmp"))
    with pytest.raises(ToolNotFoundError):
        await bus.execute("nope", {})


@pytest.mark.asyncio
async def test_missing_args():
    bus = ToolBus(fs_sandbox=FilesystemSandbox("/tmp"))
    bus.register(Tool(
        name="add", description="add",
        parameters={"required": ["a"]},
        handler=lambda a: a,
    ))
    with pytest.raises(ToolValidationError):
        await bus.execute("add", {})


@pytest.mark.asyncio
async def test_signed_tool_verified():
    with tempfile.TemporaryDirectory() as tmp:
        signer = ToolSigner()
        priv, pub = signer.generate_keypair(tmp)
        sig = signer.sign_tool("add two numbers", priv)

        verifier = ToolSigner(pub)
        bus = ToolBus(
            fs_sandbox=FilesystemSandbox("/tmp"),
            signer=verifier,
        )
        bus.register(Tool(
            name="add", description="add two numbers",
            parameters={}, handler=lambda: 1, signature=sig,
        ))
        assert await bus.execute("add", {}) == 1


@pytest.mark.asyncio
async def test_signed_tool_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        signer = ToolSigner()
        priv, pub = signer.generate_keypair(tmp)
        verifier = ToolSigner(pub)
        bus = ToolBus(
            fs_sandbox=FilesystemSandbox("/tmp"),
            signer=verifier,
        )
        with pytest.raises(ToolSignatureError):
            bus.register(Tool(
                name="bad", description="tampered",
                parameters={}, handler=lambda: 1, signature="deadbeef",
            ))
