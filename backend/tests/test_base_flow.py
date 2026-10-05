from datetime import date, timedelta

from app.services.client_base import base_flow

D = date(2026, 10, 1)


def test_новые_потерянные_и_накопление():
    # A: единственный визит 61 день назад -> потерян 01.10 (61-й день без визита); B, C: первые визиты 01.10, 02.10
    visits = {1: [D - timedelta(days=61)], 2: [D], 3: [D + timedelta(days=1)]}
    out = base_flow(visits, {}, D, D + timedelta(days=1))
    d1, d2 = out["days"]
    assert (d1["new"], d1["lost"], d1["pulse"], d1["total"]) == (1, 1, 0, 0)
    assert (d2["new"], d2["lost"], d2["pulse"]) == (1, 0, 1)
    assert out["total"] == sum(x["pulse"] for x in out["days"])


def test_вернувшийся_считается_новым_и_ранее_был_потерян():
    v = {1: [D - timedelta(days=100), D + timedelta(days=5)]}
    out = base_flow(v, {}, D - timedelta(days=100), D + timedelta(days=5))
    by = {x["date"]: x for x in out["days"]}
    assert by[(D - timedelta(days=100)).isoformat()]["new"] == 1
    assert by[(D - timedelta(days=39)).isoformat()]["lost"] == 1  # 61-й день после визита
    assert by[(D + timedelta(days=5)).isoformat()]["returned"] == 1
    assert out["total"] == 1  # новый +1, потерян -1, вернулся +1


def test_старый_клиент_вне_истории_не_считается_новым():
    out = base_flow({1: [D]}, {1: D - timedelta(days=500)}, D, D)
    assert out["days"][0]["new"] == 0
