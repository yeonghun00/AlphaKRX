"""Tests for Pydantic config module."""

import json
import os
import tempfile
import pytest

from config_pydantic import (
    AppConfig,
    DatabaseConfig,
    ApiConfig,
    KiwoomConfig,
    ProcessingConfig,
    BackfillConfig,
    load_pydantic_config,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_defaults(self):
        """Default values should work."""
        config = DatabaseConfig()
        assert config.path == "data/krx_stock_data.db"
        assert config.backup_enabled is True

    def test_custom_values(self):
        """Custom values should be accepted."""
        config = DatabaseConfig(path="custom.db", backup_enabled=False)
        assert config.path == "custom.db"
        assert config.backup_enabled is False


class TestApiConfig:
    """Tests for ApiConfig."""

    def test_defaults(self):
        """Default values should work."""
        config = ApiConfig()
        assert config.base_url == "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
        assert config.request_delay == 1.0

    def test_timeout_validation(self):
        """Timeout should accept valid values."""
        config = ApiConfig(timeout=60)
        assert config.timeout == 60


class TestKiwoomConfig:
    """Tests for KiwoomConfig."""

    def test_defaults(self):
        """Default values should work."""
        config = KiwoomConfig()
        assert config.mock is True

    def test_custom_values(self):
        """Custom values should be accepted."""
        config = KiwoomConfig(app_key="key123", account="12345678", mock=False)
        assert config.app_key == "key123"
        assert config.mock is False


class TestProcessingConfig:
    """Tests for ProcessingConfig."""

    def test_threshold_bounds(self):
        """data_quality_threshold should be bounded 0-1."""
        config = ProcessingConfig(data_quality_threshold=0.5)
        assert config.data_quality_threshold == 0.5

    def test_threshold_too_high(self):
        """Should reject threshold > 1."""
        with pytest.raises(ValueError):
            ProcessingConfig(data_quality_threshold=1.5)

    def test_threshold_negative(self):
        """Should reject threshold < 0."""
        with pytest.raises(ValueError):
            ProcessingConfig(data_quality_threshold=-0.1)


class TestBackfillConfig:
    """Tests for BackfillConfig."""

    def test_year_bounds(self):
        """start_year should be within valid range."""
        config = BackfillConfig(start_year=2020)
        assert config.start_year == 2020

    def test_year_too_early(self):
        """Should reject year < 2000."""
        with pytest.raises(ValueError):
            BackfillConfig(start_year=1999)

    def test_year_too_late(self):
        """Should reject year > 2030."""
        with pytest.raises(ValueError):
            BackfillConfig(start_year=2031)


class TestLoadPydanticConfig:
    """Tests for load_pydantic_config function."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        config = {
            "database": {"path": "test.db", "backup_enabled": False},
            "api": {"timeout": 60, "auth_key": "test_key"},
            "kiwoom": {"mock": False, "app_key": "kiwoom_key"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        yield temp_path
        os.unlink(temp_path)

    def test_load_valid_config(self, temp_config_file):
        """Should load valid config."""
        config = load_pydantic_config(temp_config_file)
        assert config.database.path == "test.db"
        assert config.database.backup_enabled is False
        assert config.api.timeout == 60
        assert config.api.auth_key == "test_key"
        assert config.kiwoom.mock is False
        assert config.kiwoom.app_key == "kiwoom_key"

    def test_missing_file(self):
        """Should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_pydantic_config("/nonexistent/config.json")

    def test_invalid_json(self):
        """Should raise ValueError for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid }")
            temp_path = f.name
        try:
            with pytest.raises(ValueError):
                load_pydantic_config(temp_path)
        finally:
            os.unlink(temp_path)

    def test_env_override(self, temp_config_file):
        """Environment variables should override config."""
        os.environ["KRX_AUTH_KEY"] = "env_key"
        os.environ["KIWOOM_MOCK"] = "true"
        try:
            config = load_pydantic_config(temp_config_file)
            assert config.api.auth_key == "env_key"
            assert config.kiwoom.mock is True
        finally:
            del os.environ["KRX_AUTH_KEY"]
            del os.environ["KIWOOM_MOCK"]


class TestAppConfig:
    """Tests for AppConfig."""

    def test_full_config(self):
        """Full config should validate correctly."""
        config = AppConfig(
            database=DatabaseConfig(path="prod.db"),
            api=ApiConfig(timeout=60),
            kiwoom=KiwoomConfig(mock=False),
        )
        assert config.database.path == "prod.db"
        assert config.api.timeout == 60
        assert config.kiwoom.mock is False
