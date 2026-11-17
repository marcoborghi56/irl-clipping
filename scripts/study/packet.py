"""Build compact review packets + aggregate tables from analysis_set/.

Per reel:  analysis_set/<creator>/<reel>/packet.md   (metrics, timed transcript, caption timeline)
Overall:   aggregate.csv (one row per reel)  and  aggregate.md (outlier-vs-flop / format comparison tables)
"""
import csv, json, statistics as st
from difflib import SequenceMatcher
import os
from pathlib import Path

ROOT = Path(os.environ.get("STUDY_ROOT") or Path.cwd()).resolve()  # study data root (reels, analysis), not the skill folder
A = ROOT / "analysis_set"
FMT = json.loads((ROOT / "formats.json").read_text())
SEL = {r["url"].rstrip("/").split("/")[-1]: r for r in csv.DictReader(open(ROOT / "selected_reels.tsv"), delimiter="\t")}


def caption_spans(text_csv, max_lines=70):
    rows = list(csv.DictReader(open(text_csv, encoding="utf-8")))
    by_t = {}
    for r in rows:
        if float(r["h"]) < 0.018:  # tiny UI text / watermarks
            continue
        by_t.setdefault(float(r["t"]), []).append(r)
    spans = []
    for t in sorted(by_t):
        items = sorted(by_t[t], key=lambda r: float(r["y"]))
        s = " / ".join(r["text"] for r in items)
        y = st.median(float(r["y"]) for r in items)
        if spans and SequenceMatcher(None, spans[-1][2], s).ratio() > 0.8:
            spans[-1][1] = t
        else:
            spans.append([t, t, s, y])
    out = [f"{a:5.1f}-{b:5.1f}s  y={y:.2f}  {s[:110]}" for a, b, s, y in spans]
    if len(out) > max_lines:
        out = out[:max_lines] + [f"... ({len(spans) - max_lines} more caption changes)"]
    return out, len(spans)


def phrases(words, gap=0.4):
    lines, cur = [], []
    for w in words:
        if cur and w["s"] - cur[-1]["e"] > gap:
            lines.append(cur); cur = []
        cur.append(w)
    if cur: lines.append(cur)
    return [f"{l[0]['s']:5.1f}s  {' '.join(w['w'] for w in l)}" for l in lines]


def main():
    rows = []
    for d in sorted(A.glob("*/*")):
        mp, vp = d / "meta.json", d / "visual.json"
        if not (mp.exists() and vp.exists()):
            continue
        m, v = json.loads(mp.read_text(encoding="utf-8")), json.loads(vp.read_text(encoding="utf-8"))
        creator, name = d.parent.name, d.name
        tag, score, rid = name.split("_", 2)
        fmt = FMT.get(creator, {}).get(tag, "?")
        s = SEL.get(rid, {})
        caps, ncap = caption_spans(d / "text.csv")
        sp = d / "sound.json"
        snd = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        TH = {"speech": 0.3, "music": 0.25, "laughter": 0.05, "shout": 0.04, "crowd": 0.08, "sfx": 0.06}
        sc = list(csv.DictReader(open(d / "sound.csv"))) if (d / "sound.csv").exists() else []
        def sr(g): return round(sum(float(r[g]) > TH[g] for r in sc) / len(sc), 2) if sc else None
        def sev(g, n=8):
            ev, start = [], None
            for r in sc + [None]:
                on = r is not None and float(r[g]) > TH[g]
                if on and start is None: start = float(r["t"])
                elif not on and start is not None:
                    ev.append(f"{start:.1f}-{(float(r['t']) if r else float(sc[-1]['t']) + 0.5):.1f}s"); start = None
            return ", ".join(ev[:n]) or "none"
        def first(g):
            return next((float(r["t"]) for r in sc if float(r[g]) > TH[g]), None)
        bs = snd.get("beat_sync") or {}
        sound_lines = ["## Sound labels (AudioSet model, low-confidence flags; share of runtime and when)"] + ([
            f"music {sr('music'):.0%} (first at {first('music')}s) | speech {sr('speech'):.0%} | laughter {sr('laughter'):.0%} | shouting {sr('shout'):.0%} | crowd {sr('crowd'):.0%} | sound effects {sr('sfx'):.0%}",
            f"laughter at: {sev('laughter')}", f"shouting at: {sev('shout')}", f"crowd at: {sev('crowd')}", f"sound effects at: {sev('sfx')}",
            "named events: " + ("; ".join(f"{n['label']} @{n['at']}s (p={n['peak']})" for n in snd.get("named_events", [])[:8]) or "none"),
            (f"music tempo {bs.get('tempo_bpm')} bpm, cuts on beat {bs.get('cuts_on_beat')} (chance {bs.get('chance_level')})" if bs else "beat sync: n/a (little or no music)"),
        ] if sc else ["(not available)"])
        dur = m["duration"]
        cuts = v["hard_cut_times"]
        row = dict(creator=creator, reel=tag, kind="outlier" if tag.startswith("out") else "flop", score=float(score.rstrip("x")),
                   views=int(s.get("views", 0)), format=fmt, aspect=f'{m["w"]}x{m["h"]}', duration=round(dur, 1),
                   scene_cuts=len(m["cuts"]), cuts_per_10s=m["cuts_per_10s"], first_cut=m["first_cut"],
                   median_shot=m["median_shot_len"], zooms_per_10s=v["zoom_events_per_10s"], cam_motion=v["camera_motion_px_per_frame"],
                   face_ratio=v["face_present_ratio"], face_h=v["face_height_median"],
                   text_ratio=v["text_on_screen_ratio"], caption_changes=ncap, caption_changes_per_10s=round(ncap / dur * 10, 1),
                   text_y=v["text_y_median"], text_h=v["text_height_median"], first_text_at=v["first_text_at"],
                   first_word_at=m["first_word_at"], wps=m["words_per_sec"], speech_ratio=m["speech_ratio"],
                   lufs=m.get("lufs_integrated"), onsets_ps=m["audio_onsets_per_sec"],
                   music=sr("music"), laughter=sr("laughter"), shout=sr("shout"), crowd=sr("crowd"), sfx=sr("sfx"),
                   cuts_on_beat=bs.get("cuts_on_beat"), hook_3s=m["hook_text_3s"])
        rows.append(row)
        md = [f"# {creator} / {tag}  ({row['kind']}, {row['score']}x vs neighbouring posts, {row['views']:,} views, format tag: {fmt})",
              f"duration {dur:.1f}s | {m['w']}x{m['h']} @ {m['fps']}fps | scene cuts {len(m['cuts'])} ({m['cuts_per_10s']}/10s), first cut {m['first_cut']}s, median shot {m['median_shot_len']}s",
              f"zoom events/10s {v['zoom_events_per_10s']} (in at {v['zoom_in_events'][:12]}, out at {v['zoom_out_events'][:12]}) | camera motion {v['camera_motion_px_per_frame']} px/frame",
              f"face on screen {v['face_present_ratio']:.0%} of time, median face height {v['face_height_median']:.0%} of frame | text on screen {v['text_on_screen_ratio']:.0%}, median text y {v['text_y_median']}, height {v['text_height_median']}",
              f"speech: first word {m['first_word_at']}s, {m['words_per_sec']} words/s, speech {m['speech_ratio']:.0%} of runtime, language {m['language']} | loudness {m.get('lufs_integrated')} LUFS, audio onsets {m['audio_onsets_per_sec']}/s",
              f"scene cut times: {m['cuts']}", "",
              *sound_lines, "",
              "## Transcript (phrase start time)", *phrases(m["word_timings"]), "",
              f"## On-screen text timeline ({ncap} changes; y = vertical position 0 top - 1 bottom)", *caps, "",
              "Images in this folder: hook.jpg (every 0.25s of first 3s), shots.jpg (one frame per shot), timeline.jpg (1 frame/s), energy.png (loudness + cuts + speech), motion.png (frame diff / zoom / face+text)."]
        (d / "packet.md").write_text("\n".join(md), encoding="utf-8")
    if not rows:
        print("no complete reels yet"); return
    with open(ROOT / "aggregate.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    num = ["duration", "cuts_per_10s", "first_cut", "median_shot", "zooms_per_10s", "cam_motion", "face_ratio", "face_h", "text_ratio",
           "caption_changes_per_10s", "text_y", "first_text_at", "first_word_at", "wps", "speech_ratio", "lufs", "onsets_ps", "music", "laughter", "shout", "crowd", "sfx", "cuts_on_beat"]
    def med(g, k):
        vals = [r[k] for r in g if r[k] is not None]
        return f"{st.median(vals):.2f}" if vals else "-"
    def table(title, groups):
        out = [f"\n### {title}", "| group | n | " + " | ".join(num) + " |", "|---|---|" + "---|" * len(num)]
        for name, g in groups:
            if g: out.append(f"| {name} | {len(g)} | " + " | ".join(med(g, k) for k in num) + " |")
        return out
    md = ["# Aggregate medians (excluded reels: ad/repost/produced removed from format tables)"]
    ok = [r for r in rows if r["format"] not in ("ad", "repost", "produced")]
    md += table("Outliers vs flops, all creators", [("outlier", [r for r in ok if r["kind"] == "outlier"]), ("flop", [r for r in ok if r["kind"] == "flop"])])
    for c in sorted({r["creator"] for r in rows}):
        md += table(f"{c}: outliers vs flops", [("outlier", [r for r in ok if r["creator"] == c and r["kind"] == "outlier"]),
                                                  ("flop", [r for r in ok if r["creator"] == c and r["kind"] == "flop"])])
    md += table("By format (outliers only)", [(f, [r for r in ok if r["format"] == f and r["kind"] == "outlier"]) for f in ["irl", "talking", "stream", "edit"]])
    md += table("IRL only: outliers vs flops", [("irl outlier", [r for r in ok if r["format"] == "irl" and r["kind"] == "outlier"]),
                                                 ("irl flop", [r for r in ok if r["format"] == "irl" and r["kind"] == "flop"])])
    asp = {}
    for r in ok: asp.setdefault((r["creator"], r["aspect"]), 0); asp[(r["creator"], r["aspect"])] += 1
    md += ["\n### Aspect ratios", *[f"- {c}: {a} x{n}" for (c, a), n in sorted(asp.items())]]
    (ROOT / "aggregate.md").write_text("\n".join(md), encoding="utf-8")
    print(f"packets: {len(rows)} reels -> aggregate.csv, aggregate.md")


if __name__ == "__main__":
    main()
