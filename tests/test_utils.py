import pytest

from notes_manager.rewrite import rewrite_tag_in_text, rewrite_tags_yaml
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


def test_rewrite_tags_yaml():
    text = "# c\na:\n  description: A\nold:\n  description: Old\nb:\n  description: B\n"
    assert "new:\n  description: Old" in rewrite_tags_yaml(text, "old", "new", merge=False)
    merged = rewrite_tags_yaml(text, "old", "b", merge=True)
    assert "old:" not in merged and "Old" not in merged and "# c" in merged
