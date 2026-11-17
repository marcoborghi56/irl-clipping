"""Build <site>/index.html for the clip review page from <clips>/README.md (written by make_index.py).

    python build.py <clips dir> <site dir> --title "Nov 20 clip picks" --run 2026-11-20-park-vlog

--run names the review round: it keys the page's local storage and labels the Copy-picks text.
"""
import argparse, json, re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("clips"); ap.add_argument("site")
ap.add_argument("--title", default="Clip picks"); ap.add_argument("--run", default="run")
a = ap.parse_args()
HERE, SITE = Path(__file__).parent, Path(a.site)
FLAG = {"profanity": "swearing", "copyrighted_music": "music in the background", "visual_only": "payoff is visual",
        "needs_context": "may need context", "sensitive_on_screen": "a screen is readable",
        "speech_unclear": "speech is hard to hear", "bystander_faces": "bystanders visible"}
TYPE = {"embarrassment": "caught out", "reveal_stakes": "reveal", "confrontation": "argument",
        "wholesome_emotional": "sincere", "mood": "mood", "prank_physical": "prank", "stranger": "stranger"}

moments, cur = [], None
for line in (Path(a.clips) / "README.md").read_text(encoding="utf-8").splitlines():
    m = re.match(r"## (c\d\d): (.*)", line)
    if m:
        cur = {"id": m.group(1), "summary": m.group(2).strip(), "versions": []}
        moments.append(cur); continue
    m = re.match(r"Tier ([ABC]).*?\| selection score (\d+) \| (\w+) \| ([\d.]+)s \| source (.*?) \| flags: (.*)", line)
    if m and cur:
        fl = [f.strip() for f in m.group(6).split(",") if f.strip() and f.strip() != "none"]
        cur.update(tier=m.group(1), score=int(m.group(2)), type=TYPE.get(m.group(3), m.group(3)),
                   len=m.group(4), source=m.group(5).strip(), flags=[FLAG.get(f, f.replace("_", " ")) for f in fl])
        continue
    m = re.match(r"- `(c\d\d_[a-z])\.mp4` \((.*?)\): (.*)", line)
    if m and cur:
        kind = m.group(2).strip()
        cur["versions"].append({"id": m.group(1), "title": m.group(3).strip(), "kind": kind[:1].upper() + kind[1:],
                                "vertical": kind.startswith("vertical")})

missing = [v["id"] for m in moments for v in m["versions"] if not (SITE / "v" / f"{v['id']}.mp4").exists()]
run = re.sub(r"[^A-Za-z0-9_-]+", "-", a.run)
html = (HERE / "template.html").read_text(encoding="utf-8")
html = html.replace("/*DATA*/[]", json.dumps(moments, ensure_ascii=False).replace("</", "<" + chr(92) + "/"))
html = html.replace("__BUILD__", __import__("time").strftime("%m%d%H%M%S"))
html = html.replace("__TITLE__", a.title.replace("&", "&amp;").replace("<", "&lt;")).replace("__RUN__", run)
SITE.mkdir(parents=True, exist_ok=True)
(SITE / "index.html").write_text(html, encoding="utf-8")
print(f"{len(moments)} moments, {sum(len(m['versions']) for m in moments)} clips, previews missing: {missing or 'none'}")
