# AGENTS.md - AlphaKRX Development Guide

This file provides guidelines for AI agents working on the AlphaKRX codebase.

## Project Overview

AlphaKRX is a Korean equity quantitative trading system featuring:
- KRX data pipeline with ETL pipelines
- LightGBM ranking model for stock selection
- Walk-forward backtesting with bias controls
- Live trading via Kiwoom REST API

## Build, Lint, and Test Commands

### Testing

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=ml --cov=scripts --cov=config_pydantic

# Run a specific test file
pytest tests/test_backtest_stats.py

# Run a specific test class
pytest tests/test_backtest_stats.py::TestComputeCoreStats

# Run a single test
pytest tests/test_backtest_stats.py::TestComputeCoreStats::test_n_rebalances

# Run tests in parallel
pytest -n auto
```

### Linting & Formatting

```bash
# Run ruff linter (check only)
ruff check .

# Run ruff with auto-fix
ruff check --fix .

# Format code with ruff
ruff format .

# Or use black directly
black .
```

### Type Checking

```bash
# Run mypy
mypy .

# Mypy excludes: tests/, docs/, build/, dist/
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run pre-commit manually
pre-commit run --all-files
```

### Running the Application

```bash
# ETL - Update market data
python scripts/run_etl.py update --markets kospi,kosdaq --workers 4

# Run backtest
python scripts/run_backtest.py --start 20100101 --min-market-cap 200000000000 --horizon 42 --top-n 50 --buy-rank 28 --hold-rank 90 --train-years 3

# Get today's picks
python scripts/get_picks.py --model-path runs/myrun/model.pkl --top 20

# Live rebalancing
python scripts/run_live.py --run myrun          # dry-run
python scripts/run_live.py --run myrun --execute # execute orders
```

## Code Style Guidelines

### General

- **Python version**: 3.10+ (target-version in pyproject.toml)
- **Line length**: 100 characters max
- **Encoding**: UTF-8

### Imports

- Use `from __future__ import annotations` for forward references
- Group imports in order: stdlib, third-party, local
- Sort imports with ruff (isort integration)

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ml.backtest.stats import compute_core_stats
from ml.models import LGBMRanker
```

### Type Hints

- Use type hints for all function signatures
- Use `|` instead of `Union` for Python 3.10+
- Use `Optional[X]` or `X | None` for nullable types

```python
def process_data(df: pd.DataFrame, years: int = 3) -> Dict[str, pd.DataFrame]:
    """Process data with type hints."""
    result: Dict[str, pd.DataFrame] = {}
    return result
```

### Naming Conventions

- **Functions/variables**: `snake_case` (e.g., `compute_core_stats`, `train_years`)
- **Classes**: `PascalCase` (e.g., `MLRanker`, `DatabaseConfig`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRY_DELAY`)
- **Private methods**: `_leading_underscore`

### Docstrings

Use Google-style docstrings:

```python
def compute_core_stats(results: pd.DataFrame) -> dict:
    """Compute all backtest statistics from results DataFrame.
    
    Args:
        results: DataFrame with portfolio returns and benchmark returns.
        
    Returns:
        Dictionary containing all computed statistics.
    """
    ...
```

### Error Handling

- Use specific exceptions from `ml/exceptions.py`
- Raise informative error messages with context
- Validate inputs at function boundaries

```python
if df.empty:
    raise ValueError("Results DataFrame cannot be empty")
```

### Configuration

- Use Pydantic v2 models (from `config_pydantic.py`)
- Define settings classes inheriting from `pydantic_settings.BaseSettings`
- Use `Field` for validation with constraints

```python
class DatabaseConfig(BaseModel):
    """Database configuration."""
    path: str = "data/krx_stock_data.db"
    backup_enabled: bool = True
    max_log_entries: int = Field(ge=100, le=100000, default=10000)
```

### Testing Guidelines

- Place tests in `tests/` directory
- Use `test_*.py` file naming
- Test class names: `Test*`
- Test function names: `test_*`
- Use pytest fixtures for setup
- Use `pytest.approx()` for floating-point comparisons

```python
class TestComputeCoreStats:
    @pytest.fixture
    def sample_results(self) -> pd.DataFrame:
        """Create sample data for testing."""
        return pd.DataFrame({...})
    
    def test_total_return(self, sample_results):
        s = compute_core_stats(sample_results)
        assert s["total_return"] == pytest.approx(0.10, rel=1e-3)
```

### Project Structure

```
alphakrx/
├── config_pydantic.py    # Pydantic config models
├── ml/                   # ML models and features
│   ├── backtest/        # Backtesting logic
│   ├── features/        # Feature engineering
│   └── models/          # ML models (lgbm, xgboost, catboost)
├── scripts/             # CLI entry points
├── etl/                 # ETL pipelines
├── live/                # Live trading
├── tests/               # Test suite
├── verification/        # Independent verification
├── docs/                # Documentation
└── tools/               # Utility scripts
```

### Bias Control Principles (Important!)

When modifying backtest or data pipeline code:
- **No look-ahead bias**: Never use data that wouldn't be available at trade time
- **Walk-forward**: Always use out-of-sample validation
- **Purge gap**: Maintain >= 42 days between train and test windows
- **Survivorship-bias-free**: Include delisted stocks

## Configuration Files

- `pyproject.toml`: Project metadata, tool configurations
- `config.json`: User configuration (gitignored)
- `.env`: Environment variables (API keys, gitignored)
- `config.example.json`: Template for configuration
