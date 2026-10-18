"""Rate limits are counted in the database, so every app process (and worker) shares them."""

import pytest

from app.core.errors import TooManyRequests
from app.core.limits import RateLimiter


def test_two_processes_share_one_count():
    a = RateLimiter("test-shared", limit=3, per_seconds=60)
    b = RateLimiter("test-shared", limit=3, per_seconds=60)  # the same limit, as another process sees it
    a.hit("ip:1.2.3.4")
    b.hit("ip:1.2.3.4")
    a.hit("ip:1.2.3.4")
    with pytest.raises(TooManyRequests):
        b.hit("ip:1.2.3.4")
    assert 0 < a.wait_seconds("ip:1.2.3.4", record=False) <= 60
    b.hit("ip:5.6.7.8")  # other callers aren't affected
    assert RateLimiter("test-other", limit=1, per_seconds=60).wait_seconds("ip:1.2.3.4") == 0  # nor other limits


def test_asking_without_recording_counts_nothing():
    r = RateLimiter("test-ask", limit=1, per_seconds=60)
    for _ in range(5):
        assert r.wait_seconds("k", record=False) == 0
    r.hit("k")
    assert r.wait_seconds("k", record=False) > 0
