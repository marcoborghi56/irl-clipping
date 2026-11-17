"""Print the `files` arguments for publishing a review site, split to fit the 64 MiB-per-call limit.

    python publish_batches.py <site dir>

Batch 1 (index.html, posters, first videos) creates the artifact; each later batch is a republish with slug and
base_version. Paste each printed JSON array as the publish call's `files`.
"""
import json, sys
from pathlib import Path
SITE = Path(sys.argv[1]).resolve()
LIMIT = 56 * 1048576
files = [SITE / "index.html"] + sorted((SITE / "p").glob("*.jpg")) + sorted((SITE / "v").glob("*.mp4"))
batches, cur, tot = [], [], 0
for f in files:
    s = f.stat().st_size
    if cur and tot + s > LIMIT:
        batches.append(cur); cur, tot = [], 0
    cur.append(f); tot += s
batches.append(cur)
for i, b in enumerate(batches, 1):
    print(f"--- batch {i}: {len(b)} files, {sum(f.stat().st_size for f in b)/1048576:.1f} MiB")
    print(json.dumps([{"as": f.relative_to(SITE).as_posix(), "path": str(f)} for f in b]))
