"""Tests for config module."""

import json
import os
import tempfile
import pytest

from config import load_config, _apply_env_overrides


class TestLoadConfig:
    """Tests for load_config function."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        config = {
            "database": {"path": "test.db"},
            "api": {"auth_key": "test_key", "timeout": 30},
            "processing": {"validate_stock_codes": True}
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        yield temp_path
        os.unlink(temp_path)

    def test_load_existing_file(self, temp_config_file):
        """Should load config from existing file."""
        config = load_config(temp_config_file)
        assert config["database"]["path"] == "test.db"
        assert config["api"]["auth_key"] == "test_key"

    def test_file_not_found(self):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_invalid_json(self):
        """Should raise ValueError for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name
        try:
            with pytest.raises(ValueError):
                load_config(temp_path)
        finally:
            os.unlink(temp_path)


class TestEnvOverrides:
    """Tests for environment variable overrides."""

    def test_krx_auth_key_override(self):
        """KRX_AUTH_KEY should override api.auth_key."""
        config = {"api": {"auth_key": "original"}}
        os.environ["KRX_AUTH_KEY"] = "env_key_123"
        try:
            result = _apply_env_overrides(config)
            assert result["api"]["auth_key"] == "env_key_123"
        finally:
            del os.environ["KRX_AUTH_KEY"]

    def test_krx_auth_key_creates_section(self):
        """KRX_AUTH_KEY should create api section if missing."""
        config = {}
        os.environ["KRX_AUTH_KEY"] = "env_key_456"
        try:
            result = _apply_env_overrides(config)
            assert result["api"]["auth_key"] == "env_key_456"
        finally:
            del os.environ["KRX_AUTH_KEY"]

    def test_kiwoom_app_key_override(self):
        """KIWOOM_APP_KEY should override kiwoom.app_key."""
        config = {"kiwoom": {"app_key": "original"}}
        os.environ["KIWOOM_APP_KEY"] = "kiwoom_key"
        try:
            result = _apply_env_overrides(config)
            assert result["kiwoom"]["app_key"] == "kiwoom_key"
        finally:
            del os.environ["KIWOOM_APP_KEY"]

    def test_kiwoom_mock_boolean(self):
        """KIWOOM_MOCK should be converted to boolean."""
        config = {"kiwoom": {"mock": False}}
        os.environ["KIWOOM_MOCK"] = "true"
        try:
            result = _apply_env_overrides(config)
            assert result["kiwoom"]["mock"] is True
        finally:
            del os.environ["KIWOOM_MOCK"]

    def test_database_path_override(self):
        """DATABASE_PATH should override database.path."""
        config = {"database": {"path": "original.db"}}
        os.environ["DATABASE_PATH"] = "/new/path/data.db"
        try:
            result = _apply_env_overrides(config)
            assert result["database"]["path"] == "/new/path/data.db"
        finally:
            del os.environ["DATABASE_PATH"]

    def test_multiple_overrides(self):
        """Multiple env vars should all be applied."""
        config = {}
        os.environ["KRX_AUTH_KEY"] = "key1"
        os.environ["KIWOOM_APP_KEY"] = "key2"
        os.environ["KIWOOM_ACCOUNT"] = "12345678"
        os.environ["DATABASE_PATH"] = "new.db"
        try:
            result = _apply_env_overrides(config)
            assert result["api"]["auth_key"] == "key1"
            assert result["kiwoom"]["app_key"] == "key2"
            assert result["kiwoom"]["account"] == "12345678"
            assert result["database"]["path"] == "new.db"
        finally:
            del os.environ["KRX_AUTH_KEY"]
            del os.environ["KIWOOM_APP_KEY"]
            del os.environ["KIWOOM_ACCOUNT"]
            del os.environ["DATABASE_PATH"]

    def test_no_env_vars_unchanged(self):
        """Config should be unchanged without env vars."""
        config = {"api": {"auth_key": "unchanged"}}
        result = _apply_env_overrides(config)
        assert result["api"]["auth_key"] == "unchanged"
