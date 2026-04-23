"""Adversarial tests for prompt injection resistance."""

import pytest
from core.selfimprove.safety_guardrails import SafetyGuardrails


class TestPromptInjectionResistance:
    """Ensure guardrails reject attempts to bypass constraints."""

    def test_ignore_instructions_blocked(self):
        g = SafetyGuardrails()
        # Attempting to modify an immutable path should always fail
        with pytest.raises(Exception):
            g.validate_target("core/errors.py")

    def test_prefix_attack_blocked(self):
        g = SafetyGuardrails()
        # Attempt to target immutable path via prefix
        with pytest.raises(Exception):
            g.validate_target("core/security/../overlay/prompts")

    def test_nested_traversal_blocked(self):
        g = SafetyGuardrails()
        # Attempt to reach immutable files through relative paths
        with pytest.raises(Exception):
            g.validate_target("overlay/../../core/security/signing.py")
