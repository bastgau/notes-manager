import pytest
from helpers import IDS, note


def test_search_is_accent_and_case_insensitive(env):
    store = env[1]
    assert [r["id"] for r in store.search("resume", None, None, 10)] == [IDS[2]]
    assert [r["id"] for r in store.search("MIGRATION", None, None, 10)] == [IDS[0]]


def test_search_tolerates_plurals(env):
    store = env[1]
    assert [r["id"] for r in store.search("volumes", None, None, 10)] == [IDS[0]]
    assert [r["id"] for r in store.search("incident", None, None, 10)] == [IDS[2]]
    assert [r["id"] for r in store.search("incidents", None, None, 10)] == [IDS[2]]


def test_search_requires_all_words_and_ranks_title_first(env):
    store = env[1]
    assert store.search("docker zzz", None, None, 10) == []
    ids = [r["id"] for r in store.search("home assistant", None, None, 10)]
    assert ids[0] == IDS[1] and IDS[2] in ids


def test_search_filters_and_snippet(env):
    store = env[1]
    hits = store.search("docker", "migration", None, 10)
    assert [h["id"] for h in hits] == [IDS[0]]
    assert "docker" in hits[0]["snippet"].lower() or hits[0]["snippet"] == ""
    assert store.search("docker", None, "up-to-date", 10)[0]["id"] == IDS[2]
    with pytest.raises(ValueError):
        store.search("   ", None, None, 10)


def test_list_docs_is_sorted_by_update_date(env):
    store = env[1]
    assert [d["id"] for d in store.list_docs(None, None)] == [IDS[2], IDS[0], IDS[1]]
    assert [d["id"] for d in store.list_docs("docker", "todo")] == [IDS[0]]


def test_validate_flags_undeclared_values(env):
    cfg, store, *_ = env
    (cfg.notes_dir / "notes" / "44444444-4444-4444-8444-444444444444.md").write_text(
        note("Bad", "bad", ["nope"], "weird", "2026-01-01", "x"))
    (cfg.notes_dir / "notes" / "not-a-uuid.md").write_text("ignored")
    store.reload()
    problems = store.snapshot.problems()
    assert len(problems) == 1
    assert {"undeclared tag: nope", "undeclared status: weird"} <= set(problems[0]["problems"])
