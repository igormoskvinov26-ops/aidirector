"""Плитки «Новые / Стали постоянными / Вернули» открывают список тех же клиентов."""

from datetime import date

from app.services.client_base import FALLBACK_RISK_DAYS, MIN_STABLE_VISITS, _в_метрике


def test_правила_списка_совпадают_с_плиткой():
    start = date(2026, 10, 1)
    p = lambda *ds: {"visit_dates": list(ds)}  # noqa: E731
    assert _в_метрике(p("2026-10-02"), "new", start)
    assert not _в_метрике(p("2026-09-02", "2026-10-02"), "new", start)
    давно = date.fromordinal(date(2026, 10, 2).toordinal() - FALLBACK_RISK_DAYS - 1).isoformat()
    assert _в_метрике(p(давно, "2026-10-02"), "returned", start)
    визиты = ["2026-01-01", "2026-03-01", "2026-06-01", "2026-10-03"][:MIN_STABLE_VISITS]
    assert _в_метрике(p(*визиты), "became_regular", start) == (визиты[-1] >= "2026-10-01")
