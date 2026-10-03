"""Deterministic Policy Engine enforcing safe autonomous operations."""

from pathlib import Path
from typing import Optional, Union

from app.core.logging import get_logger
from app.models.remediation import PolicyDecision, RiskLevel
from app.policy.loader import load_policy_document
from app.policy.models import PolicyDocument

logger = get_logger("policy.engine")


class PolicyEngine:
    """Enforces deterministic policy validation before any remediation executes."""

    def __init__(
        self,
        policy_doc: Optional[PolicyDocument] = None,
        policy_file: Optional[Union[str, Path]] = None,
    ):
        if policy_doc is not None:
            self.policy_doc = policy_doc
        else:
            self.policy_doc = load_policy_document(policy_file)

    def reload(self, policy_file: Optional[Union[str, Path]] = None) -> None:
        """Reload policy document from disk."""
        self.policy_doc = load_policy_document(policy_file)

    def evaluate(self, action: str, current_attempts: int = 0) -> PolicyDecision:
        """Evaluate whether an action is permitted, blocked, or requires approval.

        Enforces mandatory DEFAULT-DENY:
        1. Any unrecognized action is immediately denied.
        2. Prohibited/blocked actions are rejected.
        3. Attempts exceeding max_attempts are rejected.
        4. Validated actions return structured authorization metadata.
        """
        normalized_action = action.strip().lower()

        # Rule 1: Unknown actions MUST be denied (Default Deny)
        if normalized_action not in self.policy_doc.policies:
            logger.warning(
                f"Policy DENY: Action '{normalized_action}' is unrecognized (Default-Deny)."
            )
            return PolicyDecision(
                action=normalized_action,
                risk=RiskLevel.critical,
                allowed=False,
                auto_execute=False,
                requires_approval=True,
                max_attempts=0,
                blocked=True,
                reason=f"Action '{action}' is unrecognized. Default-deny enforced.",
            )

        rule = self.policy_doc.policies[normalized_action]

        # Rule 2: Explicitly blocked actions (e.g. delete_resource)
        if rule.blocked:
            logger.warning(
                f"Policy BLOCKED: Action '{normalized_action}' is prohibited by policy."
            )
            return PolicyDecision(
                action=normalized_action,
                risk=rule.risk,
                allowed=False,
                auto_execute=False,
                requires_approval=rule.requires_approval,
                max_attempts=0,
                blocked=True,
                reason="Critical action is prohibited by policy.",
            )

        # Rule 3: Max attempts check
        if current_attempts >= rule.max_attempts and rule.max_attempts > 0:
            logger.warning(
                f"Policy REJECTED: Action '{normalized_action}' reached max attempts ({current_attempts}/{rule.max_attempts})."
            )
            return PolicyDecision(
                action=normalized_action,
                risk=rule.risk,
                allowed=False,
                auto_execute=False,
                requires_approval=rule.requires_approval,
                max_attempts=rule.max_attempts,
                blocked=False,
                reason=f"Maximum remediation attempts ({rule.max_attempts}) reached.",
            )

        # Rule 4: Action allowed
        logger.info(
            f"Policy ALLOWED: Action '{normalized_action}' (Risk={rule.risk.value}, AutoExecute={rule.auto_execute}, RequiresApproval={rule.requires_approval})"
        )
        return PolicyDecision(
            action=normalized_action,
            risk=rule.risk,
            allowed=True,
            auto_execute=rule.auto_execute,
            requires_approval=rule.requires_approval,
            max_attempts=rule.max_attempts,
            blocked=False,
            reason=rule.description or "Action permitted by policy engine.",
        )
