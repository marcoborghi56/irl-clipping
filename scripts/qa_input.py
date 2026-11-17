"""Build clips/qa_input.md: per moment, what the clip claims to be + the words inside the cut (for visual QA reviewers)."""
import json, sys
from pathlib import Path
O, W = Path(sys.argv[1]), Path(sys.argv[2])
clips = []
for f in ("clips_square.json", "clips_vertical.json"):
    clips += json.loads((O / f).read_text(encoding="utf-8"))["clips"]
by = {}
for c in clips: by.setdefault(c["id"].split("_")[0], []).append(c)
out = ["# QA input: one block per moment (variations share the same cut)", ""]
for mid in sorted(by):
    cs = sorted(by[mid], key=lambda c: c["id"]); a = cs[0]; m = a["_meta"]
    tr = json.loads((W / Path(a["source"]).stem / "transcript.json").read_text(encoding="utf-8"))
    out.append(f"## {mid}  score {m['score']}  {m['type']}  {m['length_s']}s  source {Path(a['source']).name}  face-on-screen {m['face_coverage']}")
    out.append(f"what it should be: {m['summary']}")
    out.append(f"risk flags from selection: {', '.join(m['risks']) or 'none'}")
    for c in cs:
        fg = "square picture on vertical canvas, title in top band" if any(len(s) > 2 and s[2].get("fg_aspect") for s in c["segments"]) else c["layout"]
        out.append(f"- {c['id']}: {c['_meta']['canvas']} ({fg}), subtitles {'on' if c['subtitles'] else 'off'}, title: {c['title']['text']}")
    t0 = 0.0
    out.append("words in the cut (output time):")
    for seg in a["segments"]:
        s, e = seg[0], seg[1]
        line, last_sp, start = [], None, None
        for w in tr["words"]:
            if not (s <= (w["s"] + w["e"]) / 2 < e) or w.get("type", "word") != "word": continue
            if w.get("speaker") != last_sp and line:
                out.append(f"  {t0 + start - s:5.1f}s {last_sp}: {' '.join(line)}"); line = []
            if not line: start = max(w["s"], s)
            line.append(w["w"]); last_sp = w.get("speaker")
        if line: out.append(f"  {t0 + start - s:5.1f}s {last_sp}: {' '.join(line)}")
        t0 += e - s
        if seg is not a["segments"][-1]: out.append(f"  -- jump cut at {t0:.1f}s --")
    out.append("")
(O / "qa_input.md").write_text("\n".join(out), encoding="utf-8")
print("moments:", len(by), "bytes:", len("\n".join(out)))
