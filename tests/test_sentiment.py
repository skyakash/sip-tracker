"""
Sanity tests for the Fear/Greed composite against well-known historical
market regimes -- if these don't classify correctly, the percentile/scoring
logic is broken, not just imprecise.
"""

import pytest

from src import report, sentiment


@pytest.fixture(scope="module")
def frame():
    df = report.load_full_df()
    return sentiment.build_fear_greed_frame(df)


def _composite(frame, month):
    row = frame[frame["month"] == month]
    if row.empty or row.iloc[0]["composite"] != row.iloc[0]["composite"]:  # NaN check
        pytest.skip(f"{month} not available in this environment's fetched data")
    return row.iloc[0]["composite"]


def test_covid_crash_is_fearful(frame):
    # March/April 2020: VIX at record highs, FII dumping, market crashing.
    score = _composite(frame, "2020-03")
    assert sentiment.label_for(score) in ("Extreme Fear", "Fear")
    assert score < 45


def test_vaccine_rally_is_greedy(frame):
    # November 2020: the famous V-shaped recovery month -- record FII
    # buying, strong momentum.
    score = _composite(frame, "2020-11")
    assert sentiment.label_for(score) in ("Greed", "Extreme Greed")
    assert score > 55


def test_label_boundaries():
    assert sentiment.label_for(0) == "Extreme Fear"
    assert sentiment.label_for(24.9) == "Extreme Fear"
    assert sentiment.label_for(25) == "Fear"
    assert sentiment.label_for(50) == "Neutral"
    assert sentiment.label_for(74.9) == "Greed"
    assert sentiment.label_for(75) == "Extreme Greed"
    assert sentiment.label_for(100) == "Extreme Greed"


def test_latest_reading_shape():
    df = report.load_full_df()
    reading = sentiment.latest_reading(df)
    assert reading["month"] is not None
    assert 0 <= reading["composite"] <= 100
    assert reading["label"] == sentiment.label_for(reading["composite"])
    assert len(reading["components"]) >= 3  # the >=3-of-5 usability gate
