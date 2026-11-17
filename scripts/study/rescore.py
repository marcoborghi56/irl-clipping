"""Score every reel against its neighbouring posts (not the global median) and drop reels < 7 days old."""
import json, statistics, datetime as dt
from pathlib import Path
A = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
def posted(code):
    n = 0
    for ch in code[:11]: n = n * 64 + A.index(ch)
    return dt.datetime.fromtimestamp(((n >> 23) + 1314220021721) / 1000, dt.timezone.utc)
def num(s): m = {'K': 1e3, 'M': 1e6}; return float(s[:-1]) * m[s[-1]] if s[-1] in m else float(s)
NOW = dt.datetime(2026, 11, 15, tzinfo=dt.timezone.utc)
W = 10  # neighbours each side
res = {}
for f in sorted(Path("deep").glob("*.txt")):
    c = f.stem
    v = []
    for item in f.read_text().strip().split(","):
        k, s = item.rsplit(":", 1)
        v.append(dict(id=k, views=num(s), date=posted(k)))
    v.sort(key=lambda x: x["date"], reverse=True)
    for x in v: x["age_d"] = (NOW - x["date"]).total_seconds() / 86400
    for i, x in enumerate(v):
        nb = [y["views"] for j, y in enumerate(v) if j != i and abs(j - i) <= W]
        x["local_med"] = statistics.median(nb); x["score"] = x["views"] / x["local_med"]
    elig = [x for x in v if x["age_d"] >= 7]
    res[c] = v
    sc = sorted(x["score"] for x in elig)
    print(f"\n== {c}: {len(v)} reels, {v[-1]['date']:%Y-%m-%d} -> {v[0]['date']:%Y-%m-%d}, eligible {len(elig)}")
    print("   score pctiles p10 %.2f p50 %.2f p90 %.2f | >=2.5x: %d  >=2x: %d  <=0.5x: %d" % (
        sc[len(sc)//10], sc[len(sc)//2], sc[9*len(sc)//10], sum(s >= 2.5 for s in sc), sum(s >= 2 for s in sc), sum(s <= .5 for s in sc)))
    for x in sorted(elig, key=lambda x: -x["score"])[:18]:
        print(f"   {x['id']} {x['date']:%m-%d} {x['views']/1e6:6.2f}M  local {x['local_med']/1e6:5.2f}M  {x['score']:4.1f}x")
json.dump({c: [{**x, "date": x["date"].isoformat()} for x in v] for c, v in res.items()}, open("scored.json", "w"), indent=1)
