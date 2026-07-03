"""Storage abstraction — local filesystem or Cloudflare R2."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LocalStorage:
    """Reads/writes to a local directory. Default backend for dev and local runs."""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)

    def _path(self, key: str) -> Path:
        return self.base_dir / key

    def read(self, key: str) -> str | None:
        p = self._path(key)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def write(self, key: str, content: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_binary(self, key: str) -> bytes | None:
        p = self._path(key)
        if not p.exists():
            return None
        return p.read_bytes()

    def write_binary(self, key: str, content: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    def list_keys(self, prefix: str) -> list[str]:
        p = self._path(prefix)
        if not p.exists():
            return []
        return [str(f.relative_to(self.base_dir)) for f in p.rglob("*") if f.is_file()]

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

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


class R2Storage:
    """Reads/writes to Cloudflare R2 (S3-compatible). Fatal on errors — storage is a hard dependency."""

    def __init__(self, bucket: str, account_id: str, access_key_id: str, secret_access_key: str):
        import boto3
        self.bucket_name = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def read(self, key: str) -> str | None:
        from botocore.exceptions import ClientError
        try:
            resp = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def write(self, key: str, content: str) -> None:
        self.s3.put_object(Bucket=self.bucket_name, Key=key, Body=content.encode("utf-8"))

    def read_binary(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError
        try:
            resp = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def write_binary(self, key: str, content: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket_name, Key=key, Body=content)

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket_name, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return False
            raise

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


def storage_key(config_path: str) -> str:
    """Strip 'data/' prefix from a config path to produce a storage key."""
    if config_path.startswith("data/"):
        return config_path[5:]
    return config_path


def registry_storage(config: dict) -> LocalStorage:
    """Git-anchored store for registry entity files (tasks.jsonl, notes.jsonl,
    projects_registry.json, project_observation_links.jsonl).

    These files live on origin/main — written by the Registry UI and the Slack
    /task //note workflows — so runtime jobs must read/write the checked-out
    working tree (fresh origin/main in GitHub Actions), never R2. Writers must
    also be covered by their workflow's commit-back `git add` list."""
    return LocalStorage(base_dir=config.get("data_dir", "data"))


def build_storage(config: dict) -> LocalStorage | R2Storage:
    """Return R2Storage if configured and enabled, otherwise LocalStorage."""
    r2_cfg = config.get("storage", {}).get("r2", {})
    if not r2_cfg.get("enabled"):
        return LocalStorage(base_dir=config.get("data_dir", "data"))
    return R2Storage(
        bucket=r2_cfg["bucket"],
        account_id=r2_cfg["account_id"],
        access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
