"""Shared fixtures.

Everything is seeded and short: the full suite must run in seconds, not minutes,
or people stop running it.  ``session``-scoped fixtures are used for the pipeline
results because building them costs ~0.5 s each.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import pipeline                                    # noqa: E402
from engine.feeds import SyntheticConfig, SyntheticFeed         # noqa: E402
from engine.models import Category, MinuteBar, Settings         # noqa: E402
from engine.resample import resample                            # noqa: E402
from engine.systembar import annotate as system_annotate        # noqa: E402

SEED = 20260913


@pytest.fixture(scope="session")
def minutes() -> list[MinuteBar]:
    """Ten days of 1-minute synthetic data (deterministic)."""
    return SyntheticFeed(SyntheticConfig(days=10, seed=SEED)).load()


@pytest.fixture(scope="session")
def minutes30() -> list[MinuteBar]:
    """The same 30-day window ``res15`` is built from — needed by tests that
    re-run the pipeline on a truncated window to prove causality."""
    return SyntheticFeed(SyntheticConfig(days=30, seed=SEED)).load()


@pytest.fixture(scope="session")
def bars_15m(minutes) -> list:
    """15-minute system bars with no reference/timing/volatility annotation."""
    return system_annotate(resample(minutes, 15))


@pytest.fixture(scope="session")
def res15() -> pipeline.PipelineResult:
    """Fully annotated 15m pipeline result — the object most tests reuse."""
    return pipeline.run(days=30, seed=SEED, tf=15)


@pytest.fixture(scope="session")
def res15_long() -> pipeline.PipelineResult:
    """45-day run: enough history for the timing heatmap and walk-forward."""
    return pipeline.run(days=45, seed=SEED, tf=15)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


def bar_with_category(bars, cat: Category):
    """First bar of a given category, or ``None``."""
    return next((b for b in bars if b.category is cat), None)
