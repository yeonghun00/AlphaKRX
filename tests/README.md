# Test Suite

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=ml --cov=config --cov-report=html

# Run specific test file
pytest tests/test_backtest_stats.py -v
```

## Test Structure

| File | Tests | Coverage |
|------|-------|----------|
| `test_backtest_benchmark.py` | 7 | Benchmark loading, index mapping |
| `test_backtest_stats.py` | 16 | Statistics computation, performance metrics |
| `test_config.py` | 14 | Legacy config loader, environment variable overrides |
| `test_config_pydantic.py` | 17 | Pydantic config validation, type safety |

## Adding Tests

1. Follow naming convention: `test_<module>.py`
2. Use pytest fixtures for common setup
3. Test both happy path and edge cases
4. Use `pytest.approx()` for floating point comparisons
