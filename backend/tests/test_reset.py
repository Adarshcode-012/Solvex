from memory import brain


class FakeCollection:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class FakeClient:
    def __init__(self):
        self.deleted = []
        self.collections = {
            "episodic_memory": FakeCollection(2),
            "semantic_memory": FakeCollection(3),
        }

    def delete_collection(self, name):
        self.deleted.append(name)
        self.collections[name] = FakeCollection(0)

    def get_or_create_collection(self, name, metadata):
        return self.collections[name]


def test_reset_chroma_collections_recreates_empty_collections(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", True)
    monkeypatch.setattr(brain, "_chroma_client", client)
    monkeypatch.setattr(brain, "_episodic_col", client.collections["episodic_memory"])
    monkeypatch.setattr(brain, "_semantic_col", client.collections["semantic_memory"])

    deleted = brain.reset_chroma_collections()

    assert deleted == {"episodic": 2, "semantic": 3}
    assert client.deleted == ["episodic_memory", "semantic_memory"]
    assert brain._episodic_col.count() == 0
    assert brain._semantic_col.count() == 0