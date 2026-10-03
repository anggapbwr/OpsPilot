"""FastAPI dependency injection provider."""

from functools import lru_cache

from app.audit.logger import AuditLogger
from app.detection.detector import Detector
from app.detection.health_checker import HealthChecker
from app.diagnosis.engine import DiagnosisEngine
from app.evidence.collector import EvidenceCollector
from app.orchestrator import IncidentOrchestrator
from app.policy.engine import PolicyEngine
from app.remediation.ansible_runner import AnsibleRunner
from app.remediation.executor import RemediationExecutor
from app.verification.verifier import Verifier


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    return PolicyEngine()


@lru_cache(maxsize=1)
def get_audit_logger() -> AuditLogger:
    return AuditLogger()


@lru_cache(maxsize=1)
def get_health_checker() -> HealthChecker:
    return HealthChecker()


@lru_cache(maxsize=1)
def get_detector() -> Detector:
    return Detector(health_checker=get_health_checker())


@lru_cache(maxsize=1)
def get_evidence_collector() -> EvidenceCollector:
    return EvidenceCollector(health_checker=get_health_checker())


@lru_cache(maxsize=1)
def get_diagnosis_engine() -> DiagnosisEngine:
    return DiagnosisEngine()


@lru_cache(maxsize=1)
def get_ansible_runner() -> AnsibleRunner:
    return AnsibleRunner()


@lru_cache(maxsize=1)
def get_remediation_executor() -> RemediationExecutor:
    return RemediationExecutor(
        policy_engine=get_policy_engine(),
        ansible_runner=get_ansible_runner(),
    )


@lru_cache(maxsize=1)
def get_verifier() -> Verifier:
    return Verifier(health_checker=get_health_checker())


@lru_cache(maxsize=1)
def get_orchestrator() -> IncidentOrchestrator:
    return IncidentOrchestrator(
        detector=get_detector(),
        evidence_collector=get_evidence_collector(),
        diagnosis_engine=get_diagnosis_engine(),
        policy_engine=get_policy_engine(),
        remediation_executor=get_remediation_executor(),
        verifier=get_verifier(),
        audit_logger=get_audit_logger(),
    )
