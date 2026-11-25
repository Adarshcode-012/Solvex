"""Export/import Chroma collection records between installed Chroma versions.

Run ``export`` with the old Chroma environment, then ``import`` with the new
environment. The source database is read-only and is never deleted.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def export_database(client: Any, batch_size: int = 500) -> dict[str, Any]:
    collections = []
    for listed in client.list_collections():
        name = listed if isinstance(listed, str) else listed.name
        collection = client.get_collection(name)
        records = {"ids": [], "documents": [], "metadatas": []}
        for offset in range(0, collection.count(), batch_size):
            page = collection.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"],
            )
            records["ids"].extend(page.get("ids") or [])
            records["documents"].extend(page.get("documents") or [None] * len(page.get("ids") or []))
            records["metadatas"].extend(page.get("metadatas") or [None] * len(page.get("ids") or []))
        collections.append({
            "name": name,
            "metadata": collection.metadata,
            **records,
        })
    return {"format_version": 1, "collections": collections}


def import_database(client: Any, data: dict[str, Any], batch_size: int = 500) -> None:
    if data.get("format_version") != 1:
        raise ValueError("Unsupported Chroma export format.")
    for entry in data.get("collections", []):
        kwargs = {"name": entry["name"]}
        if entry.get("metadata") is not None:
            kwargs["metadata"] = entry["metadata"]
        collection = client.get_or_create_collection(**kwargs)
        if collection.count() != 0:
            raise ValueError(f"Target collection {entry['name']!r} is not empty.")
        ids = entry.get("ids", [])
        documents = entry.get("documents", [])
        metadatas = entry.get("metadatas", [])
        if len(ids) != len(documents) or len(ids) != len(metadatas):
            raise ValueError(f"Record arrays do not align in collection {entry['name']!r}.")
        for offset in range(0, len(ids), batch_size):
            end = offset + batch_size
            values = {"ids": ids[offset:end]}
            if documents[offset:end] and all(item is not None for item in documents[offset:end]):
                values["documents"] = documents[offset:end]
            if metadatas[offset:end] and all(item is not None for item in metadatas[offset:end]):
                values["metadatas"] = metadatas[offset:end]
            collection.add(**values)


def _open_client(path: str):
    import chromadb
    return chromadb.PersistentClient(path=path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--path", required=True, help="Old Chroma persistence directory")
    export_parser.add_argument("--output", required=True, help="JSON export file")
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--path", required=True, help="New, empty Chroma persistence directory")
    import_parser.add_argument("--input", required=True, help="JSON export file")
    args = parser.parse_args()

    if args.action == "export":
        payload = export_database(_open_client(args.path))
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"Exported {sum(len(c['ids']) for c in payload['collections'])} records.")
    else:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        import_database(_open_client(args.path), payload)
        print(f"Imported {sum(len(c['ids']) for c in payload['collections'])} records.")


if __name__ == "__main__":
    main()
