from scripts.migrate_chroma import export_database, import_database


class FixtureCollection:
    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata
        self.records = []

    def count(self):
        return len(self.records)

    def add(self, ids, documents=None, metadatas=None):
        documents = documents or [None] * len(ids)
        metadatas = metadatas or [None] * len(ids)
        self.records.extend(zip(ids, documents, metadatas))

    def get(self, limit=None, offset=0, include=None, where=None):
        records = self.records[offset: offset + limit if limit is not None else None]
        if where:
            records = [record for record in records if record[2] and record[2].get("user_id") == where["user_id"]]
        return {
            "ids": [record[0] for record in records],
            "documents": [record[1] for record in records],
            "metadatas": [record[2] for record in records],
        }


class FixtureClient:
    def __init__(self, collections=None):
        self.collections = collections or {}

    def list_collections(self):
        return list(self.collections.values())

    def get_collection(self, name):
        return self.collections[name]

    def get_or_create_collection(self, name, metadata=None):
        return self.collections.setdefault(name, FixtureCollection(name, metadata))


def test_chroma_export_import_fixture_preserves_counts_and_user_filter():
    old = FixtureClient({
        "episodic_memory": FixtureCollection("episodic_memory", {"hnsw:space": "cosine"}),
        "semantic_memory": FixtureCollection("semantic_memory", {"hnsw:space": "cosine"}),
    })
    old.collections["episodic_memory"].add(
        ids=["a1", "a2", "b1"],
        documents=["A one", "A two", "B one"],
        metadatas=[{"user_id": "guest_A"}, {"user_id": "guest_A"}, {"user_id": "guest_B"}],
    )
    old.collections["semantic_memory"].add(
        ids=["sa1", "sb1"],
        documents=["A rule", "B rule"],
        metadatas=[{"user_id": "guest_A"}, {"user_id": "guest_B"}],
    )

    exported = export_database(old, batch_size=2)
    new = FixtureClient()
    import_database(new, exported, batch_size=2)

    assert new.collections["episodic_memory"].count() == 3
    assert new.collections["semantic_memory"].count() == 2
    assert new.collections["episodic_memory"].get(where={"user_id": "guest_A"})["ids"] == ["a1", "a2"]
    assert new.collections["semantic_memory"].get(where={"user_id": "guest_B"})["ids"] == ["sb1"]
    assert new.collections["episodic_memory"].metadata == {"hnsw:space": "cosine"}
