"""Day 12: persist every raw DocuSign page to disk before we checkpoint it."""
import json
import os
from pathlib import Path
from typing import Any, Iterable


class RawPageWriter:
    """Layout: <base_dir>/<job_id>/<resource>/page_000000.json (or .jsonl)

    The file name comes from the page number, so re-writing the same page
    after a crash/resume simply overwrites it (idempotent).
    """

    def __init__(self, job_id: Any, base_dir: str = "data/raw") -> None:
        self.root = Path(base_dir) / str(job_id)

    def _resource_dir(self, resource: str) -> Path:
        directory = self.root / resource
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        # write to a temp file, then rename: a crash never leaves a half-written page
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def write_page(self, resource: str, page_number: int, payload: Any) -> Path:
        """Save the whole API response as one JSON file."""
        path = self._resource_dir(resource) / f"page_{page_number:06d}.json"
        self._atomic_write(path, json.dumps(payload, ensure_ascii=False))
        return path

    def write_page_jsonl(self, resource: str, page_number: int, records: Iterable[Any]) -> Path:
        """Save one record per line. One file per page (not append) so resume can't duplicate rows."""
        path = self._resource_dir(resource) / f"page_{page_number:06d}.jsonl"
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        if text:
            text += "\n"
        self._atomic_write(path, text)
        return path

    def list_pages(self, resource: str) -> list[Path]:
        directory = self.root / resource
        if not directory.exists():
            return []
        return sorted(directory.glob("page_*.json"))

    @staticmethod
    def read_page(path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)