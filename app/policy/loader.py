"""YAML Loader for remediation policies."""

from pathlib import Path
from typing import Union

import yaml

from app.core.config import get_settings
from app.core.exceptions import PolicyDeniedError
from app.core.logging import get_logger
from app.policy.models import PolicyDocument

logger = get_logger("policy.loader")


def load_policy_document(file_path: Union[str, Path, None] = None) -> PolicyDocument:
    """Load and parse policy definitions from YAML file."""
    settings = get_settings()
    path = Path(file_path) if file_path else settings.resolved_policy_file

    if not path.exists():
        logger.warning(f"Policy file '{path}' does not exist. Initializing empty policy set.")
        return PolicyDocument(policies={})

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        doc = PolicyDocument.model_validate(raw_data)
        logger.info(f"Loaded {len(doc.policies)} policy rules from '{path}'")
        return doc
    except Exception as e:
        logger.error(f"Failed to load policy file '{path}': {e}")
        raise PolicyDeniedError(
            action="*",
            reason=f"Failed to load policy definitions: {str(e)}",
        ) from e
