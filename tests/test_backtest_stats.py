"""Tests for ml.backtest.stats module."""

import numpy as np
import pandas as pd
import pytest

from ml.backtest.stats import (
    compute_core_stats,
    compute_performance,
    parse_exclude_years,
)


class TestComputePerformance:
    """Tests for compute_performance function."""

    def test_empty_series_returns_nan(self):
        """Empty series should return NaN values."""
        result = compute_performance(pd.Series(dtype=float))
        assert np.isnan(result["total_return"])
        assert np.isnan(result["ann_return"])
        assert np.isnan(result["ann_vol"])
        assert np.isnan(result["sharpe"])

    def test_single_positive_return(self):
        """Single positive return should work correctly."""
        returns = pd.Series([0.10])
        result = compute_performance(returns)
        assert result["total_return"] == pytest.approx(0.10)
        assert result["ann_return"] == pytest.approx(0.10)
        assert np.isnan(result["ann_vol"])

    def test_multiple_returns(self):
        """Multiple returns should compute correctly."""
        returns = pd.Series([0.05, 0.03, -0.02, 0.04])
        result = compute_performance(returns)
        
        expected_total = (1.05 * 1.03 * 0.98 * 1.04) - 1
        assert abs(result["total_return"] - expected_total) < 0.0001

    def test_negative_returns(self):
        """Negative returns should be handled correctly."""
        returns = pd.Series([-0.10, 0.05, -0.05])
        result = compute_performance(returns)
        assert result["total_return"] < 0

    def test_zero_returns(self):
        """Zero returns should not cause division by zero."""
        returns = pd.Series([0.0, 0.0, 0.0])
        result = compute_performance(returns)
        assert result["total_return"] == 0.0
        assert np.isnan(result["sharpe"])


class TestParseExcludeYears:
    """Tests for parse_exclude_years function."""

    def test_empty_string(self):
        """Empty string should return empty set."""
        result = parse_exclude_years("")
        assert result == set()

    def test_single_year(self):
        """Single year should be parsed correctly."""
        result = parse_exclude_years("2020")
        assert result == {"2020"}

    def test_multiple_years(self):
        """Multiple comma-separated years should be parsed."""
        result = parse_exclude_years("2020,2021,2022")
        assert result == {"2020", "2021", "2022"}

    def test_years_with_whitespace(self):
        """Years with whitespace should be handled."""
        result = parse_exclude_years("2020 , 2021 ")
        assert result == {"2020", "2021"}

    def test_invalid_input_ignored(self):
        """Invalid inputs should be ignored."""
        result = parse_exclude_years("2020,invalid,2021,abc")
        assert result == {"2020", "2021"}

    def test_invalid_length_ignored(self):
        """Invalid length strings should be ignored."""
        result = parse_exclude_years("20201,20,2020")
        assert result == {"2020"}


class TestComputeCoreStats:
    """Tests for compute_core_stats function."""

    @pytest.fixture
    def sample_results(self) -> pd.DataFrame:
        """Create sample backtest results for testing."""
        dates = pd.date_range("2020-01-01", periods=12, freq="ME").strftime("%Y%m%d")
        portfolio_returns = [0.02, 0.03, -0.01, 0.04, 0.01, -0.02,
                             0.03, 0.02, 0.05, -0.01, 0.02, 0.03]
        benchmark_returns = [0.01, 0.02, 0.01, 0.02, 0.01, 0.00,
                            0.02, 0.01, 0.03, 0.01, 0.01, 0.02]
        alphas = [p - b for p, b in zip(portfolio_returns, benchmark_returns)]
        return pd.DataFrame({
            "date": dates,
            "year": [2020] * 6 + [2021] * 6,
            "portfolio_return": portfolio_returns,
            "benchmark_return": benchmark_returns,
            "alpha": alphas,
            "turnover": [0.5, 0.6, 0.55, 0.7, 0.65, 0.5,
                         0.6, 0.55, 0.7, 0.65, 0.6, 0.55],
            "transaction_cost": [0.002, 0.002, 0.002, 0.002, 0.002, 0.002,
                                 0.002, 0.002, 0.002, 0.002, 0.002, 0.002],
        })

    def test_n_rebalances(self, sample_results):
        """Should compute correct number of rebalances."""
        s = compute_core_stats(sample_results)
        assert s["n_rebalances"] == 12

    def test_n_years(self, sample_results):
        """Should compute correct number of years."""
        s = compute_core_stats(sample_results)
        assert s["n_years"] == 2

    def test_total_return(self, sample_results):
        """Should compute correct total return."""
        s = compute_core_stats(sample_results)
        expected = (1 + sample_results["portfolio_return"]).prod() - 1
        assert abs(s["total_return"] - expected) < 0.0001

    def test_alpha(self, sample_results):
        """Should compute correct alpha."""
        s = compute_core_stats(sample_results)
        expected = s["total_return"] - s["benchmark_return"]
        assert abs(s["alpha"] - expected) < 0.0001

    def test_hit_rate(self, sample_results):
        """Should compute correct hit rate."""
        s = compute_core_stats(sample_results)
        expected = (sample_results["alpha"] > 0).mean()
        assert s["hit_rate"] == expected

    def test_max_drawdown(self, sample_results):
        """Should compute max drawdown."""
        s = compute_core_stats(sample_results)
        assert "max_dd" in s
        assert s["max_dd"] <= 0

    def test_annual_stats(self, sample_results):
        """Should compute annual statistics."""
        s = compute_core_stats(sample_results)
        assert "annual" in s
        assert 2020 in s["annual"].index
        assert 2021 in s["annual"].index


class TestComputeCoreStatsEdgeCases:
    """Edge case tests for compute_core_stats."""

    def test_all_positive_returns(self):
        """All positive returns should give positive Sharpe."""
        portfolio_returns = [0.02] * 10
        benchmark_returns = [0.01] * 10
        alphas = [p - b for p, b in zip(portfolio_returns, benchmark_returns)]
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=10, freq="ME").strftime("%Y%m%d"),
            "year": [2020] * 10,
            "portfolio_return": portfolio_returns,
            "benchmark_return": benchmark_returns,
            "alpha": alphas,
        })
        s = compute_core_stats(df)
        assert s["sharpe"] > 0
        assert s["hit_rate"] == 1.0

    def test_all_negative_returns(self):
        """All negative returns should give negative Sharpe."""
        portfolio_returns = [-0.02] * 10
        benchmark_returns = [-0.01] * 10
        alphas = [p - b for p, b in zip(portfolio_returns, benchmark_returns)]
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=10, freq="ME").strftime("%Y%m%d"),
            "year": [2020] * 10,
            "portfolio_return": portfolio_returns,
            "benchmark_return": benchmark_returns,
            "alpha": alphas,
        })
        s = compute_core_stats(df)
        assert s["sharpe"] < 0
        assert s["hit_rate"] == 0.0
