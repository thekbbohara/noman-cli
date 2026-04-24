"""Tests for config validation."""

import pytest

from cli.config_validator import ConfigValidator
from core.errors import ConfigError, ProviderConfigError


def test_valid_config():
    raw = {
        "providers": {
            "local": {"base_url": "http://localhost", "api_key": "x", "model": "llama"},
        },
        "model": {"default": "local"},
    }
    cfg = ConfigValidator().validate(raw)
    assert cfg.default_provider == "local"


def test_missing_provider_keys():
    raw = {"providers": {"bad": {"base_url": "http://localhost"}}}
    with pytest.raises(ProviderConfigError):
        ConfigValidator().validate(raw)


def test_default_not_found():
    raw = {
        "providers": {"a": {"base_url": "x", "api_key": "y", "model": "z"}},
        "model": {"default": "b"},
    }
    with pytest.raises(ConfigError):
        ConfigValidator().validate(raw)


def test_empty_providers():
    with pytest.raises(ConfigError):
        ConfigValidator().validate({})
