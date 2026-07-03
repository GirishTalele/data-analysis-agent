import pytest


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    import config.settings as m
    m._settings = None
    yield
    m._settings = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.models import Base
    import db.session as session_module

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(session_module, "_engine", engine)
    monkeypatch.setattr(session_module, "_SessionLocal", factory)
    monkeypatch.setattr(session_module, "init_db", lambda: None)
    yield engine
    engine.dispose()


@pytest.fixture
def _require_llm_key():
    """Skip if no LLM provider key is set — works for Anthropic or Gemini."""
    from config.settings import get_settings
    s = get_settings()
    if not s.anthropic_api_key and not s.gemini_api_key:
        pytest.skip("No LLM key set in .env (AGENT_ANTHROPIC_API_KEY or AGENT_GEMINI_API_KEY)")


@pytest.fixture
def large_multifile_dataset(tmp_path):
    """Synthesize a >12-file, >5,000-row-total dataset (13 monthly CSVs, ~450
    rows each) whose full-data aggregates are observably different from any
    single file's aggregate — so a sampled/partial answer would be visibly wrong.

    Shared across generators' Phase-2 integration tests. Returns a dict:
      {
        "dir": Path,                    # directory containing the CSVs
        "files": [Path, ...],           # the 13 monthly CSV paths
        "total_rows": int,
        "columns": [str, ...],
        "expected": {
            "total_rows": int,
            "overall_avg_revenue": float,      # full-data mean of `revenue`
            "total_revenue": float,            # full-data sum of `revenue`
            "avg_revenue_by_region": {region: float, ...},  # full-data groupby mean
        },
      }
    Data is fully deterministic (seeded) so expected values are exact.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(20260703)
    regions = ["North", "South", "East", "West"]
    rows_per_file = 450
    data_dir = tmp_path / "monthly_reports"
    data_dir.mkdir()

    files: list = []
    frames: list = []
    for month in range(1, 14):  # 13 files -> > 12
        n = rows_per_file
        # Make each month's revenue distribution distinct so single-file != full.
        base = 100.0 + month * 25.0
        revenue = rng.normal(loc=base, scale=20.0, size=n).round(2)
        region = rng.choice(regions, size=n)
        units = rng.integers(1, 50, size=n)
        df = pd.DataFrame(
            {
                "month": month,
                "region": region,
                "revenue": revenue,
                "units": units,
            }
        )
        path = data_dir / f"sales_2025_{month:02d}.csv"
        df.to_csv(path, index=False)
        files.append(path)
        frames.append(df)

    full = pd.concat(frames, ignore_index=True)
    expected = {
        "total_rows": int(len(full)),
        "overall_avg_revenue": round(float(full["revenue"].mean()), 4),
        "total_revenue": round(float(full["revenue"].sum()), 2),
        "avg_revenue_by_region": {
            str(k): round(float(v), 4)
            for k, v in full.groupby("region")["revenue"].mean().items()
        },
    }

    return {
        "dir": data_dir,
        "files": files,
        "total_rows": int(len(full)),
        "columns": list(full.columns),
        "expected": expected,
    }


@pytest.fixture
def groupby_question() -> str:
    """A canonical groupby-style question that should yield a populated result_table."""
    return "What is the average revenue by region?"


@pytest.fixture
def api_client(_isolated_db):
    """FastAPI test client with isolated DB."""
    from fastapi.testclient import TestClient
    from api import app
    with TestClient(app) as client:
        yield client
