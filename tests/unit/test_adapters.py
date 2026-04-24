"""Tests for model adapters."""

from __future__ import annotations

import pytest

from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import Message
from core.adapters.factory import AdapterRegistry, create_adapter, get_registry
from core.adapters.negotiator import CapabilityNegotiator
from core.adapters.openai import OpenAIAdapter
from core.adapters.router import RoleRouter


class TestOpenAIAdapter:
    """Tests for OpenAI-compatible adapter."""

    @pytest.fixture
    def config(self):
        return {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4o-mini",
            "max_context_tokens": 16000,
            "max_output_tokens": 4096,
        }

    @pytest.mark.asyncio
    async def test_create_adapter(self, config):
        adapter = OpenAIAdapter(config)
        assert adapter._cfg.model == "gpt-4o-mini"
        assert adapter._cfg.api_key == "sk-test"

    @pytest.mark.asyncio
    async def test_probe_capabilities(self, config):
        adapter = OpenAIAdapter(config)
        caps = await adapter.probe_capabilities()
        assert caps.model_name == "gpt-4o-mini"
        assert caps.supports_tool_calling is True
        assert caps.supports_streaming is True

    @pytest.mark.asyncio
    async def test_to_openai_messages(self, config):
        adapter = OpenAIAdapter(config)
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = adapter._to_openai_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_provider_type_openai(self, config):
        adapter = OpenAIAdapter(config)
        assert adapter.provider_type == "openai"

    @pytest.mark.asyncio
    async def test_provider_type_ollama(self):
        adapter = OpenAIAdapter({"base_url": "http://localhost:11434", "model": "llama3"})
        assert adapter.provider_type == "ollama"


class TestAnthropicAdapter:
    """Tests for Anthropic adapter."""

    @pytest.fixture
    def config(self):
        return {
            "api_key": "sk-ant-test",
            "model": "claude-sonnet-4-20250514",
            "max_context_tokens": 200000,
            "max_output_tokens": 8192,
        }

    @pytest.mark.asyncio
    async def test_create_adapter(self, config):
        adapter = AnthropicAdapter(config)
        assert adapter._cfg.model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_probe_capabilities(self, config):
        adapter = AnthropicAdapter(config)
        caps = await adapter.probe_capabilities()
        assert "claude" in caps.model_name
        assert caps.supports_tool_calling is True

    @pytest.mark.asyncio
    async def test_provider_type(self, config):
        adapter = AnthropicAdapter(config)
        assert adapter.provider_type == "anthropic"


class TestAdapterFactory:
    """Tests for adapter factory."""

    def test_create_openai_adapter(self):
        config = {
            "type": "openai",
            "api_key": "sk-test",
            "model": "gpt-4o",
        }
        adapter = create_adapter(config)
        assert isinstance(adapter, OpenAIAdapter)

    def test_create_anthropic_adapter(self):
        config = {
            "type": "anthropic",
            "api_key": "sk-ant-test03",
            "model": "claude-sonnet-4-20250514",
        }
        adapter = create_adapter(config)
        assert isinstance(adapter, AnthropicAdapter)

    def test_create_ollama_adapter(self):
        config = {
            "type": "ollama",
            "model": "llama3",
        }
        adapter = create_adapter(config)
        assert isinstance(adapter, OpenAIAdapter)

    def test_missing_api_key_openai(self):
        config = {"type": "openai", "model": "gpt-4o"}
        with pytest.raises(Exception):
            create_adapter(config)

    def test_registry(self):
        registry = get_registry()
        assert isinstance(registry, AdapterRegistry)


class TestCapabilityNegotiator:
    """Tests for capability negotiator."""

    @pytest.mark.asyncio
    async def test_negotiate(self):
        config = {"model": "gpt-4o-mini", "api_key": "sk-test"}
        adapter = OpenAIAdapter(config)
        negotiator = CapabilityNegotiator(ttl_sec=3600)

        caps = await negotiator.negotiate(adapter)
        assert caps.model_name == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_cache(self):
        config = {"model": "gpt-4o", "api_key": "sk-test"}
        adapter = OpenAIAdapter(config)
        negotiator = CapabilityNegotiator(ttl_sec=3600)

        caps1 = await negotiator.negotiate(adapter)
        caps2 = await negotiator.negotiate(adapter)
        assert caps1.model_name == caps2.model_name

    def test_conservative_limit(self):
        negotiator = CapabilityNegotiator()
        # Use model prefixes that exist in the dict
        assert negotiator.get_conservative_limit("mixtral") == 32768
        assert negotiator.get_conservative_limit("mistral") == 8192
        assert negotiator.get_conservative_limit("unknown") == 8192

    def test_validate_budget(self):
        negotiator = CapabilityNegotiator()
        budget, warnings = negotiator.validate_budget("mixtral", 50000)
        assert budget <= 32768


class TestRoleRouter:
    """Tests for role-based routing."""

    @pytest.mark.asyncio
    async def test_default_router(self):
        config = {"model": "gpt-4o", "api_key": "sk-test"}
        adapter = OpenAIAdapter(config)
        router = RoleRouter(adapter)
        assert router.get_adapter() == adapter

    @pytest.mark.asyncio
    async def test_role_configuration(self):
        default_cfg = {"model": "gpt-4o", "api_key": "sk-test"}
        planner_cfg = {"model": "gpt-4o", "api_key": "sk-test"}

        default_adapter = OpenAIAdapter(default_cfg)
        planner_adapter = OpenAIAdapter(planner_cfg)

        router = RoleRouter(default_adapter)
        router.configure_role("planner", planner_adapter)

        assert router.has_role("planner")
        assert router.get_adapter("planner") == planner_adapter

    @pytest.mark.asyncio
    async def test_invalid_role(self):
        config = {"model": "gpt-4o", "api_key": "sk-test"}
        adapter = OpenAIAdapter(config)
        router = RoleRouter(adapter)

        with pytest.raises(ValueError):
            router.configure_role("invalid_role", adapter)

    @pytest.mark.asyncio
    async def test_list_roles(self):
        cfg = {"model": "gpt-4o", "api_key": "sk-test"}
        adapter = OpenAIAdapter(cfg)
        router = RoleRouter(adapter)

        router.configure_role("executor", adapter)
        router.configure_role("critic", adapter)

        roles = router.list_roles()
        assert len(roles) == 2
        assert "executor" in roles
        assert "critic" in roles
