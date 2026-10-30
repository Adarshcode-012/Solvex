import os

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from memory import brain


def test_guest_memory_isolated_and_path_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", False)

    brain.store_episodic("problem A", "approach", "python", 1, True, "code", "guest_A")

    assert brain.recall_similar_problems("problem A", "guest_A")
    assert brain.recall_similar_problems("problem A", "guest_B") == []

    try:
        brain.sanitize_user_id("../outside")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal user id was accepted")