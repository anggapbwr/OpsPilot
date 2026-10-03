"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for OpsPilot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    app_name: str = "OpsPilot"
    app_env: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Ollama AI Configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_seconds: float = 10.0

    # Target Monitored Service
    target_service_name: str = "payment-api"
    target_service_url: str = "http://localhost:8080"
    target_container_name: str = "payment-api"

    # Remediation & Policy Engine
    max_remediation_attempts: int = 3
    policy_file: str = "policies/remediation.yaml"
    ansible_inventory: str = "ansible/inventory/hosts.yml"
    ansible_playbooks_dir: str = "ansible/playbooks"

    # Audit Logging
    audit_log_file: str = "logs/audit.log"

    # Verification configuration
    verification_delay_seconds: float = 2.0
    verification_timeout_seconds: float = 5.0

    @property
    def base_dir(self) -> Path:
        """Return the root repository directory."""
        return Path(__file__).resolve().parent.parent.parent

    @property
    def resolved_policy_file(self) -> Path:
        """Resolve policy file path relative to repo root if needed."""
        p = Path(self.policy_file)
        return p if p.is_absolute() else self.base_dir / p

    @property
    def resolved_audit_log_file(self) -> Path:
        """Resolve audit log file path relative to repo root."""
        p = Path(self.audit_log_file)
        return p if p.is_absolute() else self.base_dir / p

    @property
    def resolved_ansible_playbooks_dir(self) -> Path:
        """Resolve ansible playbooks directory path relative to repo root."""
        p = Path(self.ansible_playbooks_dir)
        return p if p.is_absolute() else self.base_dir / p

    @property
    def resolved_ansible_inventory(self) -> Path:
        """Resolve ansible inventory file path relative to repo root."""
        p = Path(self.ansible_inventory)
        return p if p.is_absolute() else self.base_dir / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
