# lib/main_storage.py
"""A storage adapter whose reads come from origin/main and whose writes accumulate
in memory. Lets the existing lib.tasks / lib.projects logic operate against main
without touching the working tree.

- read*/exists: served from the in-memory write buffer if the key was written this
  session, else from read_blob(repo_rel_path) (origin/main).
- write*/append_line: accumulate into the buffer. Call dirty() to get the changed
  files as {repo_rel_path: content} for committing.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


class MainStorage:
    def __init__(self, read_blob: Callable[[str], Optional[str]], data_prefix: str = "data"):
        self._read_blob = read_blob
        self._prefix = data_prefix
        self._buffer: dict = {}   # key (relative to data/) -> content

    def _rel(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def read(self, key: str) -> Optional[str]:
        if key in self._buffer:
            return self._buffer[key]
        return self._read_blob(self._rel(key))

    def write(self, key: str, content: str) -> None:
        self._buffer[key] = content

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def read_json(self, key: str, default: Any = None) -> Any:
        content = self.read(key)
        if content is None:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def write_json(self, key: str, data: Any, indent: int = 2) -> None:
        self.write(key, json.dumps(data, indent=indent))

    def append_line(self, key: str, line: str) -> None:
        existing = self.read(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write(key, existing + line + "\n")

    def dirty(self) -> dict:
        """Return {repo_rel_path: content} for every file written this session."""
        return {self._rel(k): v for k, v in self._buffer.items()}
