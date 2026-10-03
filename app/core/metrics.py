"""Prometheus metrics and operational KPI tracking."""

from typing import Any, Dict, List

from prometheus_client import Counter, Gauge, Histogram

# Prometheus Metric Definitions
INCIDENTS_TOTAL = Counter(
    "opspilot_incidents_total",
    "Total number of detected operational incidents",
    ["type", "severity", "target"],
)

INCIDENTS_RESOLVED_TOTAL = Counter(
    "opspilot_incidents_resolved_total",
    "Total number of incidents successfully resolved",
    ["target", "action"],
)

INCIDENTS_ESCALATED_TOTAL = Counter(
    "opspilot_incidents_escalated_total",
    "Total number of incidents escalated for human intervention",
    ["target", "reason"],
)

REMEDIATION_ATTEMPTS_TOTAL = Counter(
    "opspilot_remediation_attempts_total",
    "Total number of remediation attempts executed",
    ["action", "target"],
)

REMEDIATION_SUCCESS_TOTAL = Counter(
    "opspilot_remediation_success_total",
    "Total number of successful remediation executions",
    ["action", "target"],
)

REMEDIATION_FAILURE_TOTAL = Counter(
    "opspilot_remediation_failure_total",
    "Total number of failed remediation executions",
    ["action", "target"],
)

VERIFICATION_TOTAL = Counter(
    "opspilot_verification_total",
    "Total number of post-remediation health verifications",
    ["status", "target"],
)

REMEDIATION_DURATION_SECONDS = Histogram(
    "opspilot_remediation_duration_seconds",
    "Duration of remediation execution in seconds",
    ["action"],
    buckets=(1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# Active Gauges
ACTIVE_INCIDENTS = Gauge(
    "opspilot_active_incidents",
    "Number of incidents currently in non-terminal state",
)


class OperationalMetricsTracker:
    """Computes operational KPIs such as MTTR, Success Rate, and Intervention Rate."""

    def __init__(self):
        self.recovery_durations: List[float] = []
        self.total_remediation_attempts: int = 0
        self.successful_remediations: int = 0
        self.total_incidents: int = 0
        self.manual_intervention_count: int = 0

    def record_incident_created(self) -> None:
        self.total_incidents += 1

    def record_manual_intervention(self) -> None:
        self.manual_intervention_count += 1

    def record_remediation_result(self, success: bool, duration_seconds: float) -> None:
        self.total_remediation_attempts += 1
        if success:
            self.successful_remediations += 1
        if duration_seconds > 0:
            self.recovery_durations.append(duration_seconds)

    def get_kpis(self) -> Dict[str, Any]:
        """Calculate MTTR, Remediation Success Rate, and Manual Intervention Rate."""
        # 1. MTTR
        mttr = (
            round(sum(self.recovery_durations) / len(self.recovery_durations), 2)
            if self.recovery_durations
            else 0.0
        )

        # 2. Remediation Success Rate
        success_rate = (
            round((self.successful_remediations / self.total_remediation_attempts) * 100, 2)
            if self.total_remediation_attempts > 0
            else 100.0
        )

        # 3. Manual Intervention Rate
        intervention_rate = (
            round((self.manual_intervention_count / self.total_incidents) * 100, 2)
            if self.total_incidents > 0
            else 0.0
        )

        return {
            "mttr_seconds": mttr,
            "remediation_success_rate_percent": success_rate,
            "manual_intervention_rate_percent": intervention_rate,
            "total_incidents": self.total_incidents,
            "total_remediation_attempts": self.total_remediation_attempts,
            "successful_remediations": self.successful_remediations,
            "manual_interventions": self.manual_intervention_count,
        }


# Global KPI tracker singleton
kpi_tracker = OperationalMetricsTracker()
