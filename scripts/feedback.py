"""Record one review round (which clips the creator picked) and rebuild feedback/SUMMARY.md from all rounds.

    python feedback.py <clips dir> <picks file> --round 2026-11-15-first-run

<picks file> is any of:
  - JSON object  {"c01": {"good": ["c01_a"], "none": false, "note": "..."}, ...}
  - JSON list or JSON-lines of review-page documents  {"id": "c01", "data": {...}}  (what db_list returns)
  - the text the review page's "Copy picks" button produces

Writes feedback/rounds/<round>.json (one record per moment, with the features the selector and planner used) and
regenerates feedback/SUMMARY.md. Also reads feedback/posted.csv if it has rows (real view counts after posting).
Rerunning with the same --round replaces that round. Use --not-offered de when versions were added after the creator
picked, so a version nobody could choose is not counted as unpicked. `python feedback.py --summary` only rebuilds the summary.
"""
import argparse, csv, datetime as dt, json, re, sys
from collections import defaultdict
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
FB = SKILL / "feedback"
ROUNDS = FB / "rounds"


def read_picks(path):
    """-> {moment id: {"good": [clip ids], "none": bool, "note": str}}"""
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    picks = {}

    def put(mid, v):
        picks[mid] = {"good": [g for g in (v.get("good") or []) if isinstance(g, str)],
                      "none": bool(v.get("none")), "note": str(v.get("note") or "").strip()}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if rows:
            data = rows
    if isinstance(data, dict) and "docs" in data:
        data = data["docs"]
    if isinstance(data, dict):
        for mid, v in data.items():
            if isinstance(v, dict):
                put(mid, v)
        return picks
    if isinstance(data, list):
        for d in data:
            if isinstance(d, dict) and d.get("id"):
                put(d["id"], d.get("data") or d)
        return picks
    # "Copy picks" text
    def ids(label):
        m = re.search(rf"^{label}[^:]*:\s*(.*)$", text, re.M)
        return [x for x in re.findall(r"c\d\d(?:_[abc])?", m.group(1))] if m else []
    for cid in ids("Picked"):
        picks.setdefault(cid[:3], {"good": [], "none": False, "note": ""})["good"].append(cid)
    for mid in ids("None of these"):
        picks.setdefault(mid, {"good": [], "none": True, "note": ""})["none"] = True
    for mid, note in re.findall(r"^- (c\d\d): (.+)$", text, re.M):
        picks.setdefault(mid, {"good": [], "none": False, "note": ""})["note"] = note.strip()
    return picks


def title_style(t):
    t = t.strip()
    if t[:1] in "\"“":
        return "quote"
    if t.endswith(("?", "..", "…")):
        return "question or teaser"
    return "what happened"


def record(clips_dir, picks_file, name, not_offered=""):
    O = Path(clips_dir)
    clips = []
    for f in ("clips_square.json", "clips_vertical.json"):
        if (O / f).exists():
            clips += json.loads((O / f).read_text(encoding="utf-8"))["clips"]
    if not clips:
        sys.exit(f"no clips_square.json / clips_vertical.json in {O}")
    ov = json.loads((O / "overrides.json").read_text(encoding="utf-8")) if (O / "overrides.json").exists() else {}
    picks = read_picks(picks_file)
    by = defaultdict(list)
    for c in clips:
        by[c["id"].split("_")[0]].append(c)
    moments = []
    for mid in sorted(by):
        cs = sorted(by[mid], key=lambda c: c["id"]); m = cs[0]["_meta"]; p = picks.get(mid, {})
        good = set(p.get("good") or [])
        rank0 = ov.get("rank", {}).get(m.get("key"), 1) == 0
        moments.append({
            "id": mid, "key": m.get("key"), "source": Path(cs[0]["source"]).name, "type": m.get("type"),
            "score": m.get("score"), "length_s": m.get("length_s"), "risks": [r for r in m.get("risks", []) if r != "overlap"],
            "qa_tier": "A" if rank0 else ("B" if float(m.get("score") or 0) >= 60 else "C"), "summary": m.get("summary"),
            "verdict": "picked" if good else ("passed" if p.get("none") else "unreviewed"), "note": p.get("note", ""),
            "versions": [{"id": c["id"], "canvas": c["_meta"].get("canvas"), "subtitles": bool(c.get("subtitles")),
                          "title": c["title"]["text"], "title_style": title_style(c["title"]["text"]),
                          "speed": float(c.get("speed") or 1.0), "pitch": c.get("speed_pitch") if c.get("speed") else None,
                          "offered": c["id"][-1] not in not_offered,   # False: added after these picks were made
                          "picked": c["id"] in good} for c in cs]})
    unknown = sorted(set(picks) - set(by))
    ROUNDS.mkdir(parents=True, exist_ok=True)
    out = {"round": name, "recorded": dt.date.today().isoformat(), "clips_dir": str(O), "moments": moments}
    (ROUNDS / f"{name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    n = lambda v: sum(1 for m in moments if m["verdict"] == v)
    print(f"round {name}: {len(moments)} moments, picked {n('picked')}, passed {n('passed')}, unreviewed {n('unreviewed')}"
          + (f"; picks for unknown moments ignored: {unknown}" if unknown else ""))


def rate_table(title, rows, key, order=None):
    """Pick rate of reviewed moments grouped by key(m) (key may return a list)."""
    g = defaultdict(lambda: [0, 0])
    for m in rows:
        ks = key(m); ks = ks if isinstance(ks, list) else [ks]
        for k in ks:
            g[k][1] += 1; g[k][0] += m["verdict"] == "picked"
    if not g:
        return []
    keys = [k for k in (order or []) if k in g] + sorted(k for k in g if k not in (order or []))
    L = [f"### {title}", "", "| group | picked | reviewed | pick rate |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {g[k][0]} | {g[k][1]} | {100 * g[k][0] / g[k][1]:.0f}% |" for k in keys]
    return L + [""]


def band(v, edges, labels):
    for e, l in zip(edges, labels):
        if v < e:
            return l
    return labels[-1]


def summary():
    rounds = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ROUNDS.glob("*.json"))]
    rounds = [r for r in rounds if isinstance(r, dict) and "moments" in r]   # raw picks belong in feedback/picks/
    L = ["# What the picks say", "",
         "Generated by `scripts/feedback.py` from `feedback/rounds/*.json`. Do not edit by hand.",
         "Picks show what the creator is willing to post (taste and brand fit). They are not view counts: see",
         "`references/refining.md` for how much weight each kind of evidence carries.", ""]
    if not rounds:
        L += ["No review round has been recorded yet.", ""]
    else:
        allm = [dict(m, round=r["round"]) for r in rounds for m in r["moments"]]
        rev = [m for m in allm if m["verdict"] != "unreviewed"]
        L += ["## Rounds", "", "| round | recorded | moments | picked | passed | unreviewed | clips picked |", "|---|---|---:|---:|---:|---:|---:|"]
        for r in rounds:
            ms = r["moments"]; c = lambda v: sum(1 for m in ms if m["verdict"] == v)
            L.append(f"| {r['round']} | {r['recorded']} | {len(ms)} | {c('picked')} | {c('passed')} | {c('unreviewed')} | "
                     f"{sum(v['picked'] for m in ms for v in m['versions'])} |")
        L.append("")
        if not rev:
            L += ["No moment has been reviewed yet (no picks and no \"None of these\").", ""]
        else:
            pk = [m for m in rev if m["verdict"] == "picked"]; ps = [m for m in rev if m["verdict"] == "passed"]
            mean = lambda ms: f"{sum(float(m['score']) for m in ms) / len(ms):.1f}" if ms else "n/a"
            L += [f"## All rounds together: {len(rev)} reviewed moments, {len(pk)} picked, {len(ps)} passed", "",
                  f"Selector score, picked moments: mean {mean(pk)}. Passed moments: mean {mean(ps)}. "
                  "If these are close, the score is not predicting the creator's taste and the rubric's scoring needs work.", ""]
            L += rate_table("By selector score", rev, lambda m: band(float(m["score"]), [60, 70, 80], ["under 60", "60-69", "70-79", "80+"]),
                            ["under 60", "60-69", "70-79", "80+"])
            L += rate_table("By moment type", rev, lambda m: m["type"])
            L += rate_table("By visual QA tier", rev, lambda m: m["qa_tier"], ["A", "B", "C"])
            L += rate_table("By length", rev, lambda m: band(float(m["length_s"]), [15, 25, 35], ["under 15 s", "15-25 s", "25-35 s", "over 35 s"]),
                            ["under 15 s", "15-25 s", "25-35 s", "over 35 s"])
            L += rate_table("By risk flag", rev, lambda m: m["risks"] or ["none"])
            # which version wins, among picked moments
            def wins(title, key):
                g = defaultdict(lambda: [0, 0])
                for m in pk:
                    for v in m["versions"]:
                        if v.get("offered") is False: continue
                        g[key(v)][1] += 1; g[key(v)][0] += v["picked"]
                out = [f"### {title}", "", "| version | picked | offered in picked moments | share |", "|---|---:|---:|---:|"]
                out += [f"| {k} | {a} | {b} | {100 * a / b:.0f}% |" for k, (a, b) in sorted(g.items())]
                return out + [""]
            if pk:
                L += ["## Which version gets picked (within picked moments)", ""]
                L += wins("By shape and speed", lambda v: f"{v['canvas']}{' + subtitles' if v['subtitles'] else ''}"
                          + (f", {v['speed']:g}x" + (" higher pitch" if v.get("pitch") == "up" else "") if v.get("speed", 1.0) != 1.0 else ""))
                L += wins("By title style", lambda v: v["title_style"])
            notes = [m for m in allm if m["note"]]
            L += ["## Notes from the creator", ""]
            L += [f"- {m['round']} {m['id']} ({m['verdict']}, {m['type']}, score {m['score']}): {m['note']}" for m in notes] or ["None."]
            L += ["", "## Passed moments", ""]
            L += [f"- {m['round']} {m['id']} ({m['type']}, score {m['score']}, {m['length_s']} s): {m['summary']}" for m in ps] or ["None."]
            L.append("")
    posted = FB / "posted.csv"
    rows = [r for r in csv.DictReader(posted.open(encoding="utf-8-sig"))] if posted.exists() else []
    rows = [r for r in rows if (r.get("views_7d") or "").strip() and (r.get("account_median_views_7d") or "").strip()]
    L += ["## Posted results", ""]
    if not rows:
        L += ["No posted results logged yet. Add rows to `feedback/posted.csv` after clips have been up for 7 days.", ""]
    else:
        L += ["| clip | round | platform | views at 7 days | vs account median |", "|---|---|---|---:|---:|"]
        for r in rows:
            try:
                x = float(r["views_7d"]) / float(r["account_median_views_7d"])
                L.append(f"| {r.get('clip_id')} | {r.get('round')} | {r.get('platform')} | {int(float(r['views_7d'])):,} | {x:.1f}x |")
            except (ValueError, ZeroDivisionError):
                pass
        L.append("")
    (FB / "SUMMARY.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
    print("summary written:", FB / "SUMMARY.md", f"({len(rounds)} rounds)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="?"); ap.add_argument("picks", nargs="?")
    ap.add_argument("--round"); ap.add_argument("--summary", action="store_true")
    ap.add_argument("--not-offered", default="", help="version letters that did not exist when these picks were made, "
                    "e.g. de; they are recorded but left out of the which-version-wins tables")
    a = ap.parse_args()
    if not a.summary:
        if not (a.clips and a.picks and a.round):
            ap.error("need <clips dir> <picks file> --round <name>, or --summary")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", a.round):
            ap.error("--round may use letters, digits, dot, dash and underscore only")
        record(a.clips, a.picks, a.round, a.not_offered)
    summary()
