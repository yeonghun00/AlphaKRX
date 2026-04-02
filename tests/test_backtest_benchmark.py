"""Tests for ml.backtest.benchmark module."""

import os
import sqlite3
import tempfile
import pytest

from ml.backtest.benchmark import (
    load_benchmark_returns,
    BENCHMARK_INDEX_MAP,
)


class TestBenchmarkIndexMap:
    """Tests for BENCHMARK_INDEX_MAP constant."""

    def test_contains_expected_indices(self):
        """Should contain expected benchmark indices."""
        assert "kospi200" in BENCHMARK_INDEX_MAP
        assert "kospi" in BENCHMARK_INDEX_MAP
        assert "kosdaq" in BENCHMARK_INDEX_MAP
        assert "universe" in BENCHMARK_INDEX_MAP

    def test_kospi200_maps_to_korean_name(self):
        """kospi200 should map to Korean index code."""
        assert BENCHMARK_INDEX_MAP["kospi200"] == "KOSPI_코스피_200"

    def test_universe_maps_to_none(self):
        """universe should map to None (equal-weight)."""
        assert BENCHMARK_INDEX_MAP["universe"] is None


class TestLoadBenchmarkReturns:
    """Tests for load_benchmark_returns function."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with index data."""
        db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        conn = sqlite3.connect(db_path)
        
        conn.execute("""
            CREATE TABLE index_daily_prices (
                date TEXT,
                index_code TEXT,
                closing_index REAL
            )
        """)
        
        data = [
            ("20200101", "KOSPI_코스피_200", 300.0),
            ("20200102", "KOSPI_코스피_200", 305.0),
            ("20200103", "KOSPI_코스피_200", 302.0),
            ("20200106", "KOSPI_코스피_200", 308.0),
            ("20200107", "KOSPI_코스피_200", 310.0),
        ]
        conn.executemany(
            "INSERT INTO index_daily_prices VALUES (?, ?, ?)",
            data
        )
        conn.commit()
        conn.close()
        
        yield db_path
        os.unlink(db_path)

    def test_load_returns_correct_horizon(self, temp_db):
        """Should compute correct forward returns for given horizon."""
        result = load_benchmark_returns(temp_db, "KOSPI_코스피_200", horizon=1)
        
        assert "20200101" in result
        assert result["20200101"] == pytest.approx((305.0 / 300.0) - 1)

    def test_load_respects_horizon(self, temp_db):
        """Different horizons should give different results."""
        r1 = load_benchmark_returns(temp_db, "KOSPI_코스피_200", horizon=1)
        r2 = load_benchmark_returns(temp_db, "KOSPI_코스피_200", horizon=2)
        
        assert r1["20200101"] != r2["20200101"]

    def test_missing_index_returns_empty(self, temp_db):
        """Missing index code should return empty dict."""
        result = load_benchmark_returns(temp_db, "NONEXISTENT_INDEX", horizon=1)
        assert result == {}

    def test_empty_db_returns_empty(self):
        """Empty database should return empty dict."""
        db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE index_daily_prices (date TEXT, index_code TEXT, closing_index REAL)")
        conn.commit()
        conn.close()
        
        try:
            result = load_benchmark_returns(db_path, "KOSPI_코스피_200", horizon=1)
            assert result == {}
        finally:
            os.unlink(db_path)
