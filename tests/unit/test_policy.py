"""Unit tests for the Deterministic Policy Engine."""

import pytest

from app.models.remediation import RiskLevel
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyDocument, PolicyRule


@pytest.fixture
def policy_engine() -> PolicyEngine:
    """Initialize policy engine with predefined test rules."""
    doc = PolicyDocument(
        policies={
            "restart_container": PolicyRule(
                risk=RiskLevel.low,
                auto_execute=True,
                requires_approval=False,
                max_attempts=3,
                blocked=False,
            ),
            "restart_service": PolicyRule(
                risk=RiskLevel.low,
                auto_execute=True,
                requires_approval=False,
                max_attempts=3,
                blocked=False,
            ),
            "rollback_deployment": PolicyRule(
                risk=RiskLevel.medium,
                auto_execute=False,
                requires_approval=True,
                max_attempts=1,
                blocked=False,
            ),
            "modify_firewall": PolicyRule(
                risk=RiskLevel.high,
                auto_execute=False,
                requires_approval=True,
                max_attempts=1,
                blocked=False,
            ),
            "delete_resource": PolicyRule(
                risk=RiskLevel.critical,
                auto_execute=False,
                requires_approval=True,
                max_attempts=0,
                blocked=True,
            ),
        }
    )
    return PolicyEngine(policy_doc=doc)


def test_known_low_risk_action_is_allowed(policy_engine: PolicyEngine):
    """Low risk actions such as restart_container must be allowed with auto_execute."""
    decision = policy_engine.evaluate("restart_container", current_attempts=0)

    assert decision.action == "restart_container"
    assert decision.allowed is True
    assert decision.auto_execute is True
    assert decision.requires_approval is False
    assert decision.risk == RiskLevel.low
    assert decision.blocked is False


def test_unknown_action_is_denied_by_default(policy_engine: PolicyEngine):
    """Mandatory Default-Deny: Any unrecognized action must be strictly denied and blocked."""
    unauthorized_actions = ["rm_rf", "drop_database", "execute_shell", "format_disk", "arbitrary_cmd"]

    for action in unauthorized_actions:
        decision = policy_engine.evaluate(action, current_attempts=0)
        assert decision.allowed is False
        assert decision.blocked is True
        assert "Default-deny" in (decision.reason or "")


def test_high_risk_action_requires_approval(policy_engine: PolicyEngine):
    """High risk actions like rollback_deployment or modify_firewall require explicit operator approval."""
    decision = policy_engine.evaluate("rollback_deployment", current_attempts=0)

    assert decision.allowed is True
    assert decision.requires_approval is True
    assert decision.auto_execute is False
    assert decision.risk == RiskLevel.medium

    fw_decision = policy_engine.evaluate("modify_firewall", current_attempts=0)
    assert fw_decision.allowed is True
    assert fw_decision.requires_approval is True
    assert fw_decision.risk == RiskLevel.high


def test_critical_prohibited_action_is_strictly_blocked(policy_engine: PolicyEngine):
    """Actions with blocked: true (e.g. delete_resource) must be completely prohibited."""
    decision = policy_engine.evaluate("delete_resource", current_attempts=0)

    assert decision.allowed is False
    assert decision.blocked is True
    assert "prohibited by policy" in (decision.reason or "").lower()


def test_max_attempts_exhaustion_rejects_further_execution(policy_engine: PolicyEngine):
    """When attempt count reaches or exceeds max_attempts, policy must reject execution."""
    # Under limit (2 of 3)
    allowed_decision = policy_engine.evaluate("restart_container", current_attempts=2)
    assert allowed_decision.allowed is True

    # At limit (3 of 3)
    exhausted_decision = policy_engine.evaluate("restart_container", current_attempts=3)
    assert exhausted_decision.allowed is False
    assert "Maximum remediation attempts" in (exhausted_decision.reason or "")
