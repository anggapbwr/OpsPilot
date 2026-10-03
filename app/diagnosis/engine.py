"""Diagnosis Engine coordinating Ollama AI and deterministic fallback."""

from typing import Any, Dict, Optional

from app.core.exceptions import DiagnosisValidationError
from app.core.logging import get_logger
from app.diagnosis.fallback import FallbackDiagnoser
from app.diagnosis.ollama_client import OllamaClient
from app.models.diagnosis import DiagnosisResult, DiagnosisSource
from app.models.incident import Incident

logger = get_logger("diagnosis.engine")


class DiagnosisEngine:
    """Diagnoses incidents with AI-first execution and guaranteed deterministic fallback."""

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        prefer_fallback: bool = False,
    ):
        self.ollama_client = ollama_client or OllamaClient()
        self.prefer_fallback = prefer_fallback

    async def diagnose(
        self,
        incident: Incident,
        evidence: Dict[str, Any],
    ) -> DiagnosisResult:
        """Run incident diagnosis, falling back to deterministic rules if AI is unavailable."""
        if self.prefer_fallback:
            logger.info("Diagnosis configured to prefer deterministic fallback.")
            return FallbackDiagnoser.diagnose(incident, evidence)

        try:
            ai_output = await self.ollama_client.diagnose_incident(incident, evidence)
            return DiagnosisResult(
                root_cause=ai_output.root_cause,
                confidence=ai_output.confidence,
                recommended_action=ai_output.recommended_action,
                reasoning_summary=ai_output.reasoning_summary,
                source=DiagnosisSource.ai,
            )
        except DiagnosisValidationError as e:
            logger.warning(
                f"AI diagnosis failed validation or was unavailable ({e}). "
                "Activating deterministic fallback diagnosis."
            )
            return FallbackDiagnoser.diagnose(incident, evidence)
        except Exception as e:
            logger.error(
                f"Unexpected error during AI diagnosis ({e}). "
                "Activating deterministic fallback diagnosis."
            )
            return FallbackDiagnoser.diagnose(incident, evidence)
