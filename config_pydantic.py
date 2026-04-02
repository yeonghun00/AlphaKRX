"""Pydantic configuration models for AlphaKRX."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseModel):
    """Database configuration."""
    path: str = "data/krx_stock_data.db"
    backup_enabled: bool = True
    backup_interval_days: int = 7
    max_log_entries: int = 10000
    cleanup_old_data_days: int = 3650


class ApiConfig(BaseModel):
    """API configuration."""
    auth_key: str = ""
    base_url: str = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
    request_delay: float = 1.0
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 60
    backfill_request_delay: float = 0.5
    max_concurrent_requests: int = 3
    enable_parallel_processing: bool = True


class KiwoomConfig(BaseModel):
    """Kiwoom API configuration."""
    app_key: str = ""
    app_secret: str = ""
    account: str = ""
    mock: bool = True


class ProcessingConfig(BaseModel):
    """Data processing configuration."""
    validate_stock_codes: bool = True
    validate_dates: bool = True
    validate_numeric_fields: bool = True
    calculate_derived_fields: bool = True
    remove_duplicates: bool = True
    data_quality_threshold: float = Field(ge=0.0, le=1.0, default=0.8)


class UpdateConfig(BaseModel):
    """Update schedule configuration."""
    update_time: str = "18:00"
    enable_weekend_updates: bool = False
    max_concurrent_updates: int = 1
    batch_size: int = 1000
    enable_notifications: bool = False
    notification_email: str = ""


class BackfillConfig(BaseModel):
    """Backfill configuration."""
    start_year: int = Field(ge=2000, le=2030, default=2011)
    recent_years_threshold: int = Field(ge=1, le=10, default=3)
    monthly_snapshot_enabled: bool = True
    daily_recent_enabled: bool = True
    gap_filling_enabled: bool = True
    max_backfill_days: int = 3650


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    console: bool = True
    file: bool = True
    json_file: bool = False
    log_file: str = "krx_data_manager.log"
    json_log_file: str = "krx_data_manager.json"
    max_file_size: int = 10485760
    backup_count: int = 5
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""
    health_check_interval: int = 3600
    performance_monitoring: bool = True
    alert_on_failure: bool = True
    alert_email: str = ""
    disk_space_warning_gb: float = 5.0
    disk_space_critical_gb: float = 1.0
    memory_warning_percent: float = Field(ge=0, le=100, default=80.0)
    memory_critical_percent: float = Field(ge=0, le=100, default=90.0)


class AppConfig(BaseModel):
    """Main application configuration."""
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    kiwoom: KiwoomConfig = Field(default_factory=KiwoomConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    update: UpdateConfig = Field(default_factory=UpdateConfig)
    backfill: BackfillConfig = Field(default_factory=BackfillConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


class Settings(BaseSettings):
    """Settings with environment variable overrides."""
    
    krx_auth_key: Optional[str] = Field(default=None, validation_alias="KRX_AUTH_KEY")
    kiwoom_app_key: Optional[str] = Field(default=None, validation_alias="KIWOOM_APP_KEY")
    kiwoom_app_secret: Optional[str] = Field(default=None, validation_alias="KIWOOM_APP_SECRET")
    kiwoom_account: Optional[str] = Field(default=None, validation_alias="KIWOOM_ACCOUNT")
    kiwoom_mock: Optional[bool] = Field(default=None, validation_alias="KIWOOM_MOCK")
    database_path: Optional[str] = Field(default=None, validation_alias="DATABASE_PATH")


def load_pydantic_config(config_path: str = "config.json") -> AppConfig:
    """Load configuration with Pydantic validation.
    
    Args:
        config_path: Path to JSON config file
        
    Returns:
        Validated AppConfig instance
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file has invalid JSON or validation fails
    """
    import json
    
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in configuration file: {e}")
    
    settings = Settings()
    config_dict = _apply_env_overrides(config_dict, settings)
    
    try:
        return AppConfig(**config_dict)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e


def _apply_env_overrides(config_dict: dict, settings: Settings) -> dict:
    """Apply environment variable overrides to config dict."""
    
    if settings.krx_auth_key:
        if "api" not in config_dict:
            config_dict["api"] = {}
        config_dict["api"]["auth_key"] = settings.krx_auth_key
    
    if settings.kiwoom_app_key:
        if "kiwoom" not in config_dict:
            config_dict["kiwoom"] = {}
        config_dict["kiwoom"]["app_key"] = settings.kiwoom_app_key
    
    if settings.kiwoom_app_secret:
        if "kiwoom" not in config_dict:
            config_dict["kiwoom"] = {}
        config_dict["kiwoom"]["app_secret"] = settings.kiwoom_app_secret
    
    if settings.kiwoom_account:
        if "kiwoom" not in config_dict:
            config_dict["kiwoom"] = {}
        config_dict["kiwoom"]["account"] = settings.kiwoom_account
    
    if settings.kiwoom_mock is not None:
        if "kiwoom" not in config_dict:
            config_dict["kiwoom"] = {}
        config_dict["kiwoom"]["mock"] = settings.kiwoom_mock
    
    if settings.database_path:
        if "database" not in config_dict:
            config_dict["database"] = {}
        config_dict["database"]["path"] = settings.database_path
    
    return config_dict


__all__ = [
    "AppConfig",
    "DatabaseConfig", 
    "ApiConfig",
    "KiwoomConfig",
    "ProcessingConfig",
    "UpdateConfig",
    "BackfillConfig",
    "LoggingConfig",
    "MonitoringConfig",
    "load_pydantic_config",
]
