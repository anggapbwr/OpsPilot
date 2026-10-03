"""Client for Ollama local LLM inference with strict JSON schema enforcement."""

import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.exceptions import DiagnosisValidationError
from app.core.logging import get_logger
from app.models.diagnosis import ALLOWED_ACTIONS, AIDiagnosisOutput
from app.models.incident import Incident

logger = get_logger("diagnosis.ollama_client")

DIAGNOSIS_PROMPT_TEMPLATE = """You are an SRE and autonomous operations diagnostic engine for OpsPilot.
Analyze the following infrastructure incident and collected evidence, and determine the root cause and recommended remediation action.

CRITICAL INSTRUCTIONS:
1. You MUST respond with ONLY a valid, parseable JSON object matching the schema below.
2. The field 'recommended_action' MUST BE EXACTLY ONE of the following authorized actions:
   {allowed_actions}
3. Any other action (such as delete_database, rm_rf, execute_shell, modify_firewall) is STRICTLY PROHIBITED and will cause immediate system rejection.
4. 'confidence' must be a float between 0.0 and 1.0.

JSON SCHEMA:
{{
  "root_cause": "string describing the root cause",
  "confidence": 0.85,
  "recommended_action": "restart_container",
  "reasoning_summary": "concise explanation of findings"
}}

INCIDENT DATA:
- Incident ID: {incident_id}
- Incident Type: {incident_type}
- Severity: {incident_severity}
- Target: {incident_target}

COLLECTED EVIDENCE:
{evidence_json}
"""


class OllamaClient:
    """Invokes local Ollama LLM to diagnose incidents with structured outputs."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout_seconds

    async def diagnose_incident(
        self,
        incident: Incident,
        evidence: Dict[str, Any],
    ) -> AIDiagnosisOutput:
        """Call Ollama /api/generate to produce a strictly validated diagnosis."""
        url = f"{self.base_url}/api/generate"
        evidence_str = json.dumps(evidence, indent=2)

        prompt = DIAGNOSIS_PROMPT_TEMPLATE.format(
            allowed_actions=", ".join(sorted(list(ALLOWED_ACTIONS))),
            incident_id=incident.id,
            incident_type=incident.type.value,
            incident_severity=incident.severity.value,
            incident_target=incident.target,
            evidence_json=evidence_str,
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,  # Low temperature for deterministic output
            },
        }

        logger.info(f"Sending diagnostic prompt to Ollama at {url} (model: {self.model})...")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                res_data = response.json()
        except httpx.ConnectError as e:
            logger.warning(f"Failed to connect to Ollama at {self.base_url}: {e}")
            raise DiagnosisValidationError(f"Ollama service unreachable: {str(e)}") from e
        except httpx.TimeoutException as e:
            logger.warning(f"Ollama request timed out after {self.timeout}s: {e}")
            raise DiagnosisValidationError(f"Ollama request timed out: {str(e)}") from e
        except Exception as e:
            logger.error(f"Unexpected error communicating with Ollama: {e}")
            raise DiagnosisValidationError(f"Ollama call failed: {str(e)}") from e

        # Extract text response and parse as JSON
        raw_text = res_data.get("response", "").strip()
        if not raw_text:
            raise DiagnosisValidationError("Ollama returned an empty response.")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise DiagnosisValidationError(f"Failed to parse Ollama output as JSON: {raw_text}") from e

        # Validate with strict Pydantic model
        try:
            validated = AIDiagnosisOutput.model_validate(parsed)
            logger.info(
                f"Ollama diagnosis validated: RootCause='{validated.root_cause}', Action='{validated.recommended_action}'"
            )
            return validated
        except Exception as e:
            raise DiagnosisValidationError(f"Ollama output violated schema constraints: {str(e)}") from e
