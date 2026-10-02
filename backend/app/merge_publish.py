"""Merge scrape-shard files into the published corpus.

Run by the workflow's publish job after every shard has finished:

    DATA_DIR=frontend/public/data python -m backend.app.merge_publish shards/*.json

Each shard is authoritative for the companies it lists (see snapshot.merge_shards).
A shard that failed simply has no file, so its companies keep their previous rows.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from .snapshot import publish

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if __name__ == "__main__":
    data_dir = Path(os.getenv("DATA_DIR", "frontend/public/data"))
    paths = [p for p in sys.argv[1:] if Path(p).is_file()]
    if not paths:
        print("no shard files to publish", file=sys.stderr)
        sys.exit(1)
    report = publish(data_dir, paths)
    print(json.dumps(report))
