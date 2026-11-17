"""Write clips/README.md: ranked index of rendered clips with tiers, titles and flags."""
import json, sys
from pathlib import Path
O = Path(sys.argv[1])
clips = []
for f in ("clips_square.json", "clips_vertical.json"):
    clips += json.loads((O / f).read_text(encoding="utf-8"))["clips"]
ov = json.loads((O / "overrides.json").read_text(encoding="utf-8")) if (O / "overrides.json").exists() else {}
by = {}
for c in clips: by.setdefault(c["id"].split("_")[0], []).append(c)
def tier(m):
    r = ov.get("rank", {}).get(m["key"], 1)
    return "A (post first)" if r == 0 else ("B (decent)" if float(m["score"]) >= 60 else "C (filler)")
order = sorted(by, key=lambda k: (tier(by[k][0]["_meta"]), -float(by[k][0]["_meta"]["score"])))
L = ["# Clips index", "",
     f"{len(clips)} clips from {len(by)} moments. Tier A = reviewers judged the moment holds up on screen; B = decent; C = filler, post only if you need volume.",
     "Versions: `_a` square 1080x1080 (the look most of the studied IRL outliers use), `_b` vertical 1080x1920 with a different title, `_c` square with burned subtitles and a third title.",
     "Post one version per moment per platform; the versions exist so you can test titles and formats, not to post all three.", ""]
if any(c.get("speed") for c in clips):
    L.insert(4, "`_d` is the vertical version sped up, at normal voice pitch unless its label says otherwise.")
for k in order:
    cs = sorted(by[k], key=lambda c: c["id"]); m = cs[0]["_meta"]
    flags = [r for r in m["risks"] if r not in ("overlap",)]
    L.append(f"## {k}: {m['summary']}")
    L.append(f"Tier {tier(m)} | selection score {m['score']} | {m['type']} | {m['length_s']}s | source {Path(cs[0]['source']).name} | flags: {', '.join(flags) or 'none'}")
    for c in cs:
        kind = c["_meta"]["canvas"] + (" + subtitles" if c.get("subtitles") else "")
        if c.get("speed"): kind += f", {c['speed']:g}x speed" + (", higher pitch" if c.get("speed_pitch") == "up" else "")
        L.append(f"- `{c['id']}.mp4` ({kind}): {c['title']['text']}")
    L.append("")
(O / "README.md").write_text("\n".join(L), encoding="utf-8")
print("index written:", len(clips), "clips,", len(by), "moments;", {t: sum(1 for k in by if tier(by[k][0]['_meta']) == t) for t in ("A (post first)", "B (decent)", "C (filler)")})
