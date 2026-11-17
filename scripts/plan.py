"""plan.py - selection candidates -> clip specs for render.py.

  python plan.py --work <work-dir> --out <clips-dir> [--n 50] [--sources stem,stem] [--min-score 55]

Reads  <work>/<stem>/candidates_*.json, transcript.json, sound.csv, loudness.csv, probe.json and style.json.
Writes <out>/clips_square.json, <out>/clips_vertical.json (one file per output canvas) and <out>/plan.md.

Steps: validate -> dedupe overlaps -> snap boundaries to word edges -> tighten dead air (never the action)
-> reframe (face-centred crop) -> allocate variations until N clips.
"""
import argparse, csv, json, math
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
STYLE = json.loads((HERE.parent / "references" / "style.json").read_text(encoding="utf-8"))
PT = STYLE["pause_tightening"]
TH = {"laughter": 0.05, "shout": 0.04, "crowd": 0.10}  # sound.csv thresholds that protect a silence


def load_source(work, stem):
    d = Path(work) / stem
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    words = [w for w in tr.get("words", []) if w.get("type", "word") == "word"]
    sound = list(csv.DictReader(open(d / "sound.csv"))) if (d / "sound.csv").exists() else []
    loud = [(float(r["t"]), float(r["rms_db"])) for r in csv.DictReader(open(d / "loudness.csv"))] if (d / "loudness.csv").exists() else []
    probe = json.loads((d / "probe.json").read_text(encoding="utf-8"))
    sp = [db for t, db in loud if any(w["s"] <= t <= w["e"] for w in words[:400])] or [db for _, db in loud]
    return dict(stem=stem, words=words, sound=sound, loud=loud, probe=probe, speech_db=float(np.median(sp)) if sp else -30.0)


def busy(src, a, b):
    """True if the gap a..b holds a reaction or action sound (so it must not be removed)."""
    for r in src["sound"]:
        t = float(r["t"])
        if a - 0.25 <= t <= b and (float(r["laughter"]) > TH["laughter"] or float(r["shout"]) > TH["shout"] or float(r["crowd"]) > TH["crowd"]):
            return True
    seg = [db for t, db in src["loud"] if a + 0.15 <= t <= b - 0.15]
    return bool(seg) and max(seg) > src["speech_db"] + 3.0  # as loud as speech with no words = something is happening


def snap(src, c):
    """Snap start/end to word edges so no word is clipped; keep the tail after the payoff."""
    W, dur = src["words"], src["probe"]["duration"]
    s, e = float(c["start"]), float(c["end"])
    pay = float(c.get("payoff_at") or (s + 0.7 * (e - s)))
    # start: never pull in the tail of the previous sentence. A word that straddles the start is kept only if it
    # begins within 0.15 s of it (timeline times are rounded to 0.1 s); otherwise the clip starts after that word.
    for w in W:
        if w["s"] < s < w["e"]:
            s = w["s"] if s - w["s"] <= 0.15 else w["e"] + 0.02
    nxt = next((w for w in W if w["s"] >= s - 0.01), None)
    if nxt and nxt["s"] - s <= 0.8:
        s = nxt["s"]
    # Best anchor: the selector's hook_line (the first words the viewer should hear). Start exactly on it.
    norm = lambda t: "".join(ch for ch in t.lower() if ch.isalnum())
    hook = [norm(t) for t in str(c.get("hook_line") or "").split()]
    hook = [t for t in hook if t][:3]
    near = [i for i, w in enumerate(W) if s - 1.5 <= w["s"] <= s + 4.0]
    found = None
    for n in (3, 2):
        if found is not None or len(hook) < n: continue
        for i in near:
            if [norm(x["w"]) for x in W[i:i + n]] == hook[:n]:
                found = W[i]["s"]; break
    if found is not None:
        s = found
    else:  # no match: drop a short leading run by one speaker that is followed by someone else (tail of the previous line)
        run = [w for w in W if w["s"] >= s - 0.01][:6]
        k = next((j for j, w in enumerate(run) if w.get("speaker") != run[0].get("speaker")), None) if run else None
        if k and k <= 3 and run[k - 1]["e"] - run[0]["s"] < 1.2:
            s = run[k]["s"]
    # end: prefer the last sentence end at or before the requested end (never before the payoff), so clips do not
    # stop mid-sentence; otherwise at least never cut a word in half.
    e = max(e, pay + STYLE["structure"]["tail_after_payoff_s"][0])
    ends = [w for w in W if max(pay + 0.5, e - 4.0) <= w["e"] <= e + 0.3 and w["w"].rstrip("\"')”’").endswith((".", "?", "!"))]
    if ends:
        e = ends[-1]["e"]
    else:
        for w in W:
            if w["s"] < e < w["e"]: e = w["e"]
    nxt_w = next((w for w in W if w["s"] >= e - 0.01), None)
    e = min(e + 0.35, nxt_w["s"] - 0.03) if nxt_w and nxt_w["s"] - e < 0.38 else e + 0.35  # keep the tail clear of the next word
    s = max(0.0, s - 0.03)
    e = min(dur, e)
    return round(s, 2), round(e, 2), pay


def tighten(src, s, e, pay, risks):
    """Remove dead air longer than the threshold, but never reactions, never near the payoff."""
    if any(r in PT["skip_if_risk"] for r in risks):
        return [[s, e]], 0
    W = [w for w in src["words"] if w["e"] > s and w["s"] < e]
    cuts, prev = [], s
    edges = [(s, s)] + [(w["s"], w["e"]) for w in W] + [(e, e)]
    for (a0, a1), (b0, b1) in zip(edges, edges[1:]):
        gap = b0 - a1
        if gap > PT["remove_silence_longer_than_s"] and a1 < pay - PT["protect_window_before_payoff_s"] and not busy(src, a1, b0):
            keep = PT["keep_silence_s"] / 2
            cuts.append((a1 + keep, b0 - keep))
    segs = []
    for c0, c1 in cuts:
        if c0 - prev >= PT["min_segment_s"]:
            segs.append([round(prev, 2), round(c0, 2)]); prev = c1
        # else: segment would be too short, keep the silence instead
    segs.append([round(prev, 2), round(e, 2)])
    total = sum(b - a for a, b in segs)
    if (len(segs) - 1) / max(total, 1) * 10 > PT["max_jump_cuts_per_10s"]:
        return [[s, e]], 0
    return segs, round((e - s) - total, 1)


_face = None
_FC = {}        # face-detection results by source file and cut, kept in <work>/_face_cache.json so re-plans are quick
_FC_FILE = None
def _fc_key(path, segs, max_samples):
    p = Path(path)
    return f"{p.name}|{int(p.stat().st_mtime)}|{max_samples}|" + ";".join(f"{a:.2f}-{b:.2f}" for a, b in segs)
_cov = []  # (frames sampled, frames with a face) per segment, from the last face_centres call
def face_centres(path, segs, max_samples=36):
    """Per-segment horizontal face centre (0-1) and spread, from sampled frames."""
    global _face
    key = _fc_key(path, segs, max_samples)
    if key in _FC:
        _cov.clear(); _cov.extend(tuple(c) for c in _FC[key]["cov"])
        return [tuple(o) for o in _FC[key]["out"]]
    model = HERE.parent / "assets" / "face_yunet.onnx"
    if _face is None:
        _face = cv2.FaceDetectorYN.create(str(model), "", (640, 360), 0.6)
    cap = cv2.VideoCapture(str(path))
    total = sum(b - a for a, b in segs)
    step = max(0.5, total / max_samples)
    out = []
    _cov.clear()
    for a, b in segs:
        xs, ws = [], []
        seen = hit = 0
        for t in np.arange(a + 0.1, b, step):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, f = cap.read()
            if not ok: continue
            seen += 1
            h, w = f.shape[:2]
            sm = cv2.resize(f, (640, int(h * 640 / w)))
            _face.setInputSize((sm.shape[1], sm.shape[0]))
            _, faces = _face.detect(sm)
            if faces is None: continue
            big = [fc for fc in faces if fc[3] / sm.shape[0] > 0.06]
            hit += 1 if big else 0
            for fc in big:
                xs.append((fc[0] + fc[2] / 2) / sm.shape[1]); ws.append(fc[2] * fc[3])
        if xs:
            lo, hi = float(np.percentile(xs, 8)), float(np.percentile(xs, 92))
            # centre on the span of all faces (keeps both people of a two-shot in frame); if they are too far apart
            # for any crop, the caller falls back to the area-weighted mean (favours the closer, larger face)
            out.append(((lo + hi) / 2, hi - lo, len(xs), float(np.average(xs, weights=ws))))
        else:
            out.append((None, 0.0, 0, None))
        _cov.append((seen, hit))
    cap.release()
    _FC[key] = {"out": out, "cov": list(_cov)}
    return out


def reframe(src, segs, canvas_ar):
    """crop_x per segment for a crop of aspect canvas_ar (w/h) out of the source frame."""
    p = src["probe"]
    src_ar = p["width"] / p["height"]
    if src_ar <= canvas_ar * 1.02:
        return [0.5] * len(segs), 0.0, True
    half = canvas_ar / src_ar / 2  # half-width of crop window as a fraction of source width
    fc = face_centres(p["path"], segs)
    known = [x for x, _, n, _ in fc if x is not None]
    default = float(np.median(known)) if known else 0.5
    xs, prev = [], default
    for x, spread, n, wmean in fc:
        if x is not None:  # area-weighted mean of faces. (Centring on the face span was tried and did not match visual QA.)
            x = wmean
        x = prev if x is None else x
        if abs(x - prev) < 0.06: x = prev  # avoid tiny reframing jumps between segments
        xs.append(round(min(max(x, half), 1 - half), 3)); prev = x
    spread = max((s for _, s, _, _ in fc), default=0.0)
    fits = spread <= 2 * half * 0.9  # do all detected faces fit inside the crop window?
    return xs, spread, fits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=50); ap.add_argument("--sources", default="")
    ap.add_argument("--min-score", type=float, default=55)
    a = ap.parse_args()
    global _FC_FILE
    _FC_FILE = Path(a.work) / "_face_cache.json"
    if _FC_FILE.is_file():
        _FC.update(json.loads(_FC_FILE.read_text(encoding="utf-8")))
    work, out = Path(a.work), Path(a.out); out.mkdir(parents=True, exist_ok=True)
    want = {s for s in a.sources.split(",") if s}
    cands, srcs = [], {}
    for d in sorted(work.iterdir()):
        if not d.is_dir() or (want and d.name not in want) or not (d / "transcript.json").exists():
            continue
        files = sorted(d.glob("candidates_*.json"))
        if not files: continue
        srcs[d.name] = load_source(work, d.name)
        for f in files:
            for c in json.loads(f.read_text(encoding="utf-8")):
                c["stem"] = d.name; cands.append(c)
    L = STYLE["length"]
    ok = []
    for c in cands:
        try:
            s, e = float(c["start"]), float(c["end"])
        except Exception:
            continue
        dur = srcs[c["stem"]]["probe"]["duration"]
        if not (0 <= s < e <= dur + 1) or float(c.get("score", 0)) < a.min_score or not c.get("titles"):
            continue
        ok.append(c)
    ok.sort(key=lambda c: -float(c["score"]))
    kept = []
    for c in ok:  # dedupe: same source, overlapping more than half of the shorter one
        dup = False
        for k in kept:
            if k["stem"] != c["stem"]: continue
            inter = min(k["end"], c["end"]) - max(k["start"], c["start"])
            if inter > 0.5 * min(k["end"] - k["start"], c["end"] - c["start"]): dup = True; break
        if not dup: kept.append(c)

    ovp = out / "overrides.json"
    OV = json.loads(ovp.read_text(encoding="utf-8")) if ovp.exists() else {}
    moments = []
    for i, c in enumerate(kept, 1):
        src = srcs[c["stem"]]
        key = f"{c['stem']}@{round(float(c['start']))}"
        c["_key"] = key
        if key in OV.get("drop", {}):
            continue
        s, e, pay = snap(src, c)
        risks = c.get("risks") or []
        segs, removed = tighten(src, s, e, pay, risks)
        total = sum(b - a_ for a_, b in segs)
        if total > L["hard_max_s"]:  # trim the tail down to payoff + 3 s, then give up on tightening
            e2 = min(e, pay + STYLE["structure"]["tail_after_payoff_s"][1])
            segs, removed = tighten(src, s, e2, pay, risks); total = sum(b - a_ for a_, b in segs)
        cap = OV.get("max_out_s", {}).get(key)
        if cap and total > cap:  # QA asked for an earlier end: trim segments to this output length
            acc, new = 0.0, []
            for s0, s1 in segs:
                if acc + (s1 - s0) >= cap:
                    new.append([s0, round(s0 + cap - acc, 2)]); break
                new.append([s0, s1]); acc += s1 - s0
            segs = new; total = sum(b - a_ for a_, b in segs)
        if total < L["hard_min_s"] or total > L["hard_max_s"] + 15:
            continue
        horizontal = src["probe"]["width"] > src["probe"]["height"] * 1.1
        sq_x, spread, sq_fits = reframe(src, segs, 1.0) if horizontal else ([0.5] * len(segs), 0, True)
        seen = sum(a_ for a_, _ in _cov); face_cov = round(sum(b_ for _, b_ in _cov) / seen, 2) if seen else None
        pin = OV.get("crop_x", {}).get(key)
        if pin is not None:  # QA-approved crop position (already includes any requested shift)
            sq_x = [pin[min(j, len(pin) - 1)] for j in range(len(segs))] if isinstance(pin, list) else [pin] * len(segs)
        v_x, _, v_fits = reframe(src, segs, 9 / 16) if horizontal else ([0.5] * len(segs), 0, True)
        speech = sum(min(w["e"], e) - max(w["s"], s) for w in src["words"] if w["e"] > s and w["s"] < e) / max(e - s, 1)
        moments.append(dict(n=i, c=c, src=src, segs=segs, removed=removed, total=round(total, 1), pay=pay, horizontal=horizontal,
                            sq_x=sq_x, v_x=v_x, sq_fits=sq_fits, v_fits=v_fits, spread=round(spread, 2), speech=round(speech, 2), face_cov=face_cov))

    def clip(m, vid, canvas, layout, title_i, subs):
        c = m["c"]; xs = m["sq_x"] if canvas == "square" else m["v_x"]
        zf = STYLE["zoom"]["factors_alternate"]
        segs = []
        fitsq = layout == "fitsq"
        if fitsq: layout, xs = "fit", m["sq_x"]
        for j, (s0, s1) in enumerate(m["segs"]):
            extra = {"crop_x": xs[j]} if layout == "crop" else ({"crop_x": xs[j], "fg_aspect": 1.0} if fitsq else {})
            if layout == "crop" and len(m["segs"]) > 1: extra["zoom"] = zf[j % 2]
            segs.append([s0, s1, extra] if extra else [s0, s1])
        t = OV.get("title", {}).get(c["_key"], {}).get(vid) or c["titles"][min(title_i, len(c["titles"]) - 1)]
        y = (0.83 if canvas == "square" else (0.155 if fitsq else (STYLE["title"]["y_fit_layout"] if layout == "fit" else STYLE["title"]["y_crop_layout"])))
        return {"id": f"c{m['n']:02d}_{vid}", "variation_of": None if vid == "a" else f"c{m['n']:02d}_a", "source": m["src"]["probe"]["path"],
                "segments": segs, "layout": layout, "crop_x": 0.5, "title": {"text": t, "y": y, "start": 0, "end": None},
                "subtitles": bool(subs), "loudnorm": STYLE["audio"]["loudnorm"],
                "_meta": {"score": c["score"], "type": c.get("moment_type"), "summary": c.get("summary"), "canvas": canvas,
                          "length_s": m["total"], "dead_air_removed_s": m["removed"], "risks": c.get("risks") or [],
                          "face_coverage": m["face_cov"], "key": c["_key"]}}

    # Variation recipe per moment, in priority order. Horizontal source: A = square crop (the look most IRL outliers use),
    # B = vertical with a different title (crop if one subject fits, else fit), C = square, third title, subtitles on.
    def recipe(m):
        if m["horizontal"]:
            return [("a", "square", "crop", 0, False), ("b", "vertical", "crop" if m["v_fits"] else "fitsq", 1, False), ("c", "square", "crop", 2, True)]
        return [("a", "vertical", "crop", 0, False), ("b", "vertical", "crop", 1, True), ("c", "vertical", "crop", 2, False)]

    rank = OV.get("rank", {})  # QA "holds up" tier: lower = stronger; decides who gets extra variations first
    order = sorted(moments, key=lambda m: (rank.get(m["c"]["_key"], 1), -float(m["c"]["score"])))
    chosen = []
    for level in range(3):  # everyone gets A first, then B, then C, strongest moments first
        for m in order:
            if len(chosen) >= a.n: break
            r = recipe(m)
            if level < len(r): chosen.append(clip(m, *r[level]))
    # Speed versions ride on top of --n, so the a/b/c set never changes when they are switched on: "d" is a copy of the
    # base version (style.json speed.base_version) at speed.factor with speed.pitch; "e" is the same with the pitch kept,
    # only for moments listed in overrides.json "speed_pitch_kept" (lets the creator hear both on a few clips).
    SP = STYLE.get("speed") or {}
    if SP.get("enabled") and float(SP.get("factor") or 1) != 1.0:
        fac, pitch = float(SP["factor"]), str(SP.get("pitch", "up"))
        have = {c["id"]: c for c in chosen}
        kept = set(OV.get("speed_pitch_kept", []))
        for m in order:
            b = have.get(f"c{m['n']:02d}_{SP.get('base_version', 'b')}")
            if not b: continue
            for vid, pt in [("d", pitch)] + ([("e", "keep")] if m["c"]["_key"] in kept and pitch != "keep" else []):
                c2 = json.loads(json.dumps(b))
                c2.update(id=f"c{m['n']:02d}_{vid}", variation_of=b["id"], speed=fac, speed_pitch=pt)
                c2["_meta"].update(speed=fac, speed_pitch=pt, source_length_s=b["_meta"]["length_s"],
                                   length_s=round(b["_meta"]["length_s"] / fac, 1))
                chosen.append(c2)
    sq = [c for c in chosen if c["_meta"]["canvas"] == "square"]; vt = [c for c in chosen if c["_meta"]["canvas"] == "vertical"]
    def font_file(kind):  # style.json fonts.<kind>, relative to the skill folder. No fallback: a missing font stops the run,
        rel = (STYLE.get("fonts") or {}).get(kind)  # so clips are never rendered in the wrong typeface by accident.
        f = HERE.parent / rel if rel else None
        if not (f and f.is_file()):
            raise SystemExit(f"font for {kind} not found: {f} (set fonts.{kind} in references/style.json)")
        return str(f)
    TL = STYLE.get("title_look") or {}
    common_style = {"title_font": font_file("title"), "sub_font": font_file("subtitles"),
                    "title_stroke_width": TL.get("outline_px", 6), "title_shadow": TL.get("shadow")}
    (out / "clips_square.json").write_text(json.dumps({"output": {"width": 1080, "height": 1080, "fps": 30},
        "style": {**common_style, "title_size": TL.get("size_square", 58), "title_min_size": 42, "title_safe_bottom": 0.95, "title_max_lines": 2, "sub_size": 58, "sub_y": 0.66}, "clips": sq}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "clips_vertical.json").write_text(json.dumps({"output": {"width": 1080, "height": 1920, "fps": 30},
        "style": {**common_style, "title_size": TL.get("size_vertical", 64), "title_safe_bottom": 0.78}, "clips": vt}, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = [f"# Clip plan: {len(chosen)} clips from {len(moments)} moments ({len(cands)} candidates, {len(kept)} after dedupe)", "",
             "| clip | score | type | len | cut | canvas/layout | title | risks |", "|---|---|---|---|---|---|---|---|"]
    for c in chosen:
        m = c["_meta"]
        lines.append(f"| {c['id']} | {m['score']} | {m['type']} | {m['length_s']}s | {m['dead_air_removed_s']}s | {m['canvas']}/{c['layout']} | {c['title']['text']} | {', '.join(m['risks'])}{' face ' + str(m['face_coverage']) if m['face_coverage'] is not None else ''} |")
    (out / "plan.md").write_text("\n".join(lines), encoding="utf-8")
    _FC_FILE.write_text(json.dumps(_FC), encoding="utf-8")
    print(f"{len(cands)} candidates -> {len(kept)} unique -> {len(moments)} usable moments -> {len(chosen)} clips ({len(sq)} square, {len(vt)} vertical)")


if __name__ == "__main__":
    main()
