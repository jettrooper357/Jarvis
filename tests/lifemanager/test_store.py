from __future__ import annotations

from openjarvis.lifemanager.store import LifeDomain, LifeStore


def _store(tmp_path):
    return LifeStore(db_path=str(tmp_path / "life.db"))


def test_add_domain_and_get(tmp_path):
    store = _store(tmp_path)
    d = store.add_domain(name="Health", description="body + mind", now=1000.0)
    assert isinstance(d, LifeDomain)
    assert d.name == "Health"
    assert d.slug == "health"  # slug defaults from name
    assert d.created_at == 1000.0
    fetched = store.get_domain(d.id)
    assert fetched is not None
    assert fetched.description == "body + mind"
    store.close()


def test_add_domain_explicit_slug_and_list(tmp_path):
    store = _store(tmp_path)
    store.add_domain(name="Church Work", slug="church", now=1.0)
    store.add_domain(name="Home", now=2.0)
    domains = store.list_domains()
    assert len(domains) == 2
    slugs = {d.slug for d in domains}
    assert slugs == {"church", "home"}
    store.close()


def test_add_domain_requires_name(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.add_domain(name="  ")
    store.close()


def test_add_routine_cadences_and_validation(tmp_path):
    import pytest

    store = _store(tmp_path)
    d = store.add_domain(name="Health", now=1.0)
    r = store.add_routine(
        title="Walk", domain_id=d.id, cadence="daily", now=1.0
    )
    assert r.cadence == "daily"
    assert r.status == "active"
    assert r.streak == 0
    assert store.add_routine(title="W", cadence="weekly", now=1.0).cadence == "weekly"
    assert store.add_routine(title="W2", cadence="weekly", now=1.0).interval_days == 7
    assert store.add_routine(title="M", cadence="monthly", now=1.0).interval_days == 30
    cust = store.add_routine(
        title="C", cadence="custom", interval_days=3, now=1.0
    )
    assert cust.interval_days == 3
    with pytest.raises(Exception):
        store.add_routine(title="bad", cadence="hourly", now=1.0)
    with pytest.raises(Exception):
        store.add_routine(title="bad", cadence="custom", interval_days=0, now=1.0)
    with pytest.raises(Exception):
        store.add_routine(title="  ", now=1.0)
    store.close()


def test_complete_advances_due_and_streak(tmp_path):
    store = _store(tmp_path)
    daily = store.add_routine(title="Walk", cadence="daily", now=1000.0)
    done = store.complete_routine(daily.id, now=1000.0)
    assert done.last_done_at == 1000.0
    assert done.streak == 1
    assert done.next_due_at == 1000.0 + 86400.0  # +1 day
    again = store.complete_routine(daily.id, now=2000.0)
    assert again.streak == 2
    assert again.next_due_at == 2000.0 + 86400.0

    weekly = store.add_routine(title="Review", cadence="weekly", now=1000.0)
    wdone = store.complete_routine(weekly.id, now=1000.0)
    assert wdone.next_due_at == 1000.0 + 7 * 86400.0

    cust = store.add_routine(
        title="C", cadence="custom", interval_days=3, now=1000.0
    )
    cdone = store.complete_routine(cust.id, now=1000.0)
    assert cdone.next_due_at == 1000.0 + 3 * 86400.0
    store.close()


def test_complete_missing_raises(tmp_path):
    import pytest

    store = _store(tmp_path)
    with pytest.raises(Exception):
        store.complete_routine("nope")
    store.close()


def test_due_lists_owed_and_excludes_paused(tmp_path):
    store = _store(tmp_path)
    owed = store.add_routine(title="owed", cadence="daily", now=1.0)
    store.complete_routine(owed.id, now=1.0)  # next_due = 1 + 86400
    fresh = store.add_routine(title="fresh", cadence="daily", now=1.0)
    store.complete_routine(fresh.id, now=10_000_000.0)
    due = store.due(now=200_000.0)
    titles = {r.title for r in due}
    assert "owed" in titles
    assert "fresh" not in titles
    store.set_routine_status(owed.id, "paused")
    assert all(r.title != "owed" for r in store.due(now=200_000.0))
    store.close()


def test_set_status_transitions_and_validation(tmp_path):
    import pytest

    store = _store(tmp_path)
    r = store.add_routine(title="x", now=1.0)
    assert store.set_routine_status(r.id, "paused").status == "paused"
    assert store.set_routine_status(r.id, "archived").status == "archived"
    assert store.set_routine_status(r.id, "active").status == "active"
    with pytest.raises(Exception):
        store.set_routine_status(r.id, "bogus")
    with pytest.raises(Exception):
        store.set_routine_status("missing", "active")
    store.close()


def test_list_routines_filters(tmp_path):
    store = _store(tmp_path)
    d = store.add_domain(name="Health", now=1.0)
    store.add_routine(title="a", domain_id=d.id, now=1.0)
    store.add_routine(title="b", now=2.0)
    assert len(store.list_routines()) == 2
    assert len(store.list_routines(domain_id=d.id)) == 1
    store.set_routine_status(store.list_routines(domain_id=d.id)[0].id, "paused")
    assert len(store.list_routines(status="paused")) == 1
    store.close()
