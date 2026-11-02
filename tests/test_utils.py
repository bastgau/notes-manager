import pytest

from notes_manager.rewrite import (
    drop_vocab_entry,
    rename_vocab_key,
    rewrite_status_in_text,
    rewrite_tag_in_text,
    upsert_vocab_entry,
    yaml_scalar,
)
from notes_manager.snapshot import parse_vocabulary
from notes_manager.utils import check_id, find_secret, normalize, suggest


def test_normalize_strips_accents_and_case():
    assert normalize("Résumé Éléphant") == "resume elephant"


def test_find_secret_ignores_placeholders():
    assert find_secret("ghp_xxxxxxxxxxxxxxxxxxxx") is None
    assert find_secret("-----BEGIN OPENSSH PRIVATE KEY-----") is not None
    assert find_secret("key AKIAIOSFODNN7EXAMPLE") is not None
    assert find_secret("nothing to see") is None


def test_suggest():
    assert "docker" in suggest("dockr", {"docker": "", "portainer": ""})
    assert suggest("zzzz", {"docker": ""}) == ""


def test_check_id():
    assert check_id(" 11111111-1111-4111-8111-111111111111 ") == "11111111-1111-4111-8111-111111111111"
    for bad in ("../x", "1111", "11111111-1111-4111-8111-11111111111G"):
        with pytest.raises(ValueError):
            check_id(bad)


def test_rewrite_tag_in_text_only_touches_front_matter():
    text = "---\ntags: [a, old, b]\n---\n\ntags: [old]\n"
    assert rewrite_tag_in_text(text, "old", "new") == "---\ntags: [a, new, b]\n---\n\ntags: [old]\n"
    assert "tags: [a, b]" in rewrite_tag_in_text("---\ntags: [a, old, b]\n---\n", "old", "b")


def test_rewrite_status_in_text_only_touches_front_matter():
    text = "---\nstatus: todo\n---\n\nstatus: todo\n"
    assert rewrite_status_in_text(text, "todo", "pending") == "---\nstatus: pending\n---\n\nstatus: todo\n"
    assert rewrite_status_in_text(text, "other", "x") == text


VOCAB = "# c\na:\n  description: A\nold:\n  description: Old\nb:\n  description: B\n"


def test_rename_vocab_key():
    assert "new:\n  description: Old" in rename_vocab_key(VOCAB, "old", "new", merge=False)
    merged = rename_vocab_key(VOCAB, "old", "b", merge=True)
    assert "old:" not in merged and "Old" not in merged and "# c" in merged


def test_drop_vocab_entry_keeps_the_rest():
    assert parse_vocabulary(drop_vocab_entry(VOCAB, "a")) == {"old": "Old", "b": "B"}


def test_upsert_vocab_entry():
    assert parse_vocabulary(upsert_vocab_entry(VOCAB, "old", "Changed")) == {"a": "A", "old": "Changed", "b": "B"}
    added = upsert_vocab_entry(VOCAB, "zz", "Brand new")
    assert added.endswith("zz:\n  description: Brand new\n") and "# c" in added
    # Inserted before the first greater key, and above the comment that heads it.
    grouped = "# top\na:\n  description: A\n# Group\nm:\n  description: M\n"
    assert upsert_vocab_entry(grouped, "c", "C") == (
        "# top\na:\n  description: A\nc:\n  description: C\n# Group\nm:\n  description: M\n")
    assert upsert_vocab_entry(grouped, "0", "Z").startswith("# top\n0:\n  description: Z\na:")
    assert parse_vocabulary(upsert_vocab_entry("", "first", "One")) == {"first": "One"}
    # Replaces a folded multi-line description entirely.
    folded = "x:\n  description: >\n    long\n    text\ny:\n  description: Y\n"
    assert parse_vocabulary(upsert_vocab_entry(folded, "x", "Short")) == {"x": "Short", "y": "Y"}


@pytest.mark.parametrize("value", ["Plain words", "Time: 10:30", "a # b", 'say "hi"', "yes", " padded", "it's", "é accent"])
def test_yaml_scalar_round_trips(value):
    assert parse_vocabulary(f"k:\n  description: {yaml_scalar(value)}\n") == {"k": value}
