"""Small preview copies + poster frames of rendered clips, for the review page. Originals are only read.

    python make_previews.py <clips dir> <site dir>

Writes <site>/v/<id>.mp4 (480x480 square, 432x768 vertical, ~450 kbps) and <site>/p/<id>.jpg.
Sized so one clip is about 1-2 MB: hosted pages allow 20 MiB per file and 64 MiB per publish call.
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
_vj = SRC / "clips_vertical.json"   # which clips are 1080x1920
VERTICAL = {c["id"] for c in json.loads(_vj.read_text(encoding="utf-8"))["clips"]} if _vj.exists() else set()
(OUT / "v").mkdir(parents=True, exist_ok=True); (OUT / "p").mkdir(parents=True, exist_ok=True)

def one(mp4: Path):
    cid = mp4.stem
    size = "432:768" if (cid in VERTICAL or (not VERTICAL and cid.endswith("_b"))) else "480:480"
    dst, jpg = OUT / "v" / f"{cid}.mp4", OUT / "p" / f"{cid}.jpg"
    if not dst.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4),
            "-vf", f"fps=30,scale={size}:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
            "-crf", "28", "-maxrate", "380k", "-bufsize", "760k", "-g", "60", "-pix_fmt", "yuv420p",
            "-profile:v", "main", "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-movflags", "+faststart", str(dst)], check=True)
    if not jpg.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(mp4), "-frames:v", "1",
            "-vf", f"scale={size}:flags=lanczos", "-q:v", "6", str(jpg)], check=True)
    return dst.stat().st_size

with ThreadPoolExecutor(4) as ex:
    sizes = list(ex.map(one, sorted(SRC.glob("c*.mp4"))))
print(f"{len(sizes)} previews, {sum(sizes)/1048576:.1f} MiB, largest {max(sizes)/1048576:.2f} MiB")
