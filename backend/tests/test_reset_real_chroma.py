import pytest

chromadb = pytest.importorskip("chromadb")

from memory import brain


def test_real_chroma_reset_removes_only_requesting_guest(tmp_path, monkeypatch):
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    episodic = client.get_or_create_collection("episodic_memory")
    semantic = client.get_or_create_collection("semantic_memory")
    episodic.add(
        ids=["a", "b"],
        documents=["A", "B"],
        metadatas=[{"user_id": "guest_A"}, {"user_id": "guest_B"}],
    )
    semantic.add(
        ids=["sa", "sb"],
        documents=["A semantic", "B semantic"],
        metadatas=[{"user_id": "guest_A"}, {"user_id": "guest_B"}],
    )

    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", True)
    monkeypatch.setattr(brain, "_episodic_col", episodic)
    monkeypatch.setattr(brain, "_semantic_col", semantic)

    deleted = brain.reset_user_memory("guest_A")

    assert deleted == {"episodic": 1, "semantic": 1}
    assert episodic.get(where={"user_id": "guest_A"})["ids"] == []
    assert episodic.get(where={"user_id": "guest_B"})["ids"] == ["b"]
    assert semantic.get(where={"user_id": "guest_A"})["ids"] == []
    assert semantic.get(where={"user_id": "guest_B"})["ids"] == ["sb"]