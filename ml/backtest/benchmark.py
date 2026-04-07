from __future__ import annotations

import sqlite3
from typing import Optional

import pandas as pd


BENCHMARK_INDEX_MAP: dict[str, Optional[str]] = {
    "kospi200": "KOSPI_코스피_200",
    "kospi": "KOSPI_코스피",
    "kosdaq": "KOSDAQ_코스닥",
    "kosdaq150": "KOSDAQ_코스닥_150",
    "universe": None,       # equal-weight universe average
    "universe_cap": None,   # cap-weighted universe average (market_cap from df)
}


def load_benchmark_returns(
    db_path: str, index_code: str, horizon: int
) -> dict[str, float]:
    """Load N-day forward returns for a given index from the DB.

    Returns a dict mapping YYYYMMDD date string → forward return (float).
    Dates near the tail where T+horizon doesn't exist will have NaN and are excluded.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            idx = pd.read_sql_query(
                "SELECT date, closing_index FROM index_daily_prices "
                "WHERE index_code = ? ORDER BY date",
                conn,
                params=(index_code,),
            )
    except Exception as exc:
        print(f"[Benchmark] WARNING: failed to load {index_code}: {exc}", flush=True)
        return {}
    if idx.empty:
        print(f"[Benchmark] WARNING: no data for {index_code}", flush=True)
        return {}
    idx = idx.sort_values("date").reset_index(drop=True)
    idx["fwd"] = idx["closing_index"].shift(-horizon) / idx["closing_index"] - 1
    return dict(zip(idx["date"], idx["fwd"].where(idx["fwd"].notna())))
