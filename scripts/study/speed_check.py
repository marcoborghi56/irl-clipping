"""Speed-up check for the reel study.

Does a reel play sped up (about 1.2x-2x)? Two audio measures per reel:
  1. articulation rate: syllables/s inside runs of continuous speech
     (words with gaps < GAP s, runs of >= MIN_RUN words), from a fresh
     faster-whisper medium pass (same settings as analyze.py, language forced to en).
  2. 20th-percentile voice F0 (librosa pyin) on frames that are inside whisper words AND
     speech-dominant per sound.csv, compared with the same creator's lowest-pitched reels.
Video is not used.

Sanity mode (--sanity reelA,reelB,...) makes 1.25x/1.5x copies of those reels' audio
with ffmpeg atempo (pitch kept) and asetrate (pitch raised, i.e. plain fast playback)
and runs the same measures on them.

Usage:
  STUDY_ROOT=<study dir> python speed_check.py --out <dir> [--tmp <dir>] [--sanity c/reel,...]
Writes <out>/speed_check.csv. Whisper results are cached in --tmp (default STUDY_ROOT/_tmp_speed).
"""
import argparse, csv, json, os, re, subprocess, sys
from pathlib import Path
import numpy as np

# Make pip-installed CUDA DLLs (nvidia-cublas-cu12 / nvidia-cudnn-cu12) visible on Windows.
try:
    import nvidia
    for _base in nvidia.__path__:
        for _bin in Path(_base).glob("*/bin"):
            os.add_dll_directory(str(_bin))
            os.environ["PATH"] = str(_bin) + os.pathsep + os.environ["PATH"]
except Exception:
    pass

GAP = 0.35        # s, max gap inside a speech run
MIN_RUN = 4       # words
MIN_WORDS = 25    # words in valid runs needed to judge the rate
MIN_RUNS = 3
MIN_PROB = 0.4    # drop low-confidence whisper words
RATE_FAST = 7.0   # syl/s median articulation rate: above this -> fast
RATE_NORMAL = 5.5 # below this and no pitch lift -> normal (1.5x of a 3.7 syl/s talker)
PITCH_LIFT = 3.0  # semitones above creator baseline that suggests un-corrected speed-up
MIN_VOICED = 150  # voiced pyin frames (~2.4 s) needed to trust F0
SR = 16000

ROOT = Path(os.environ.get("STUDY_ROOT", "."))


def syllables(word):
    w = re.sub(r"[^a-z0-9']", "", word.lower())
    if not w:
        return 0
    if w.isdigit():
        return 2 * len(w)  # crude
    w = re.sub(r"[0-9']", "", w)
    if not w:
        return 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("ed") and n > 1 and not w.endswith(("ted", "ded")):
        n -= 1
    return max(n, 1)


def runs_of(words):
    runs, cur = [], []
    for w in words:
        if cur and w["s"] - cur[-1]["e"] > GAP:
            runs.append(cur); cur = []
        cur.append(w)
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= MIN_RUN and r[-1]["e"] - r[0]["s"] > 0.3]


def articulation(words):
    words = [w for w in words if w.get("p", 1) >= MIN_PROB and w["e"] > w["s"]]
    rs, n_words = [], 0
    for r in runs_of(words):
        dur = r[-1]["e"] - r[0]["s"]
        syl = sum(syllables(w["w"]) for w in r)
        rs.append((syl / dur, dur)); n_words += len(r)
    if not rs:
        return None, None, 0, 0
    rates = np.array([x for x, _ in rs]); durs = np.array([d for _, d in rs])
    # duration-weighted median and upper quartile
    o = np.argsort(rates); c = np.cumsum(durs[o]) / durs.sum()
    med = rates[o][np.searchsorted(c, 0.5)]; q75 = rates[o][np.searchsorted(c, 0.75)]
    return float(med), float(q75), n_words, len(rs)


def extract(src, dst, filt=None):
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR)]
    if filt:
        cmd += ["-af", filt]
    subprocess.run(cmd + [str(dst)], check=True)


def transcribe(model, wav, cache):
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import soundfile as sf
    audio, _ = sf.read(str(wav), dtype="float32")
    segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True, language="en")
    words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}
             for s in segs for w in (s.words or [])]
    cache.write_text(json.dumps(words), encoding="utf-8")
    return words


def speech_windows(sound_csv, scale):
    """speech-dominant 0.5 s windows from sound.csv; times divided by scale (for sped copies)."""
    out = []
    if not sound_csv.exists():
        return None
    for r in csv.DictReader(open(sound_csv)):
        s, m = float(r["speech"]), float(r["music"])
        if s >= 0.3 and s >= m:
            t = float(r["t"]) / scale
            out.append((t, t + 0.5 / scale))
    return out


def f0_median(wav, words, windows):
    import librosa
    y, _ = librosa.load(str(wav), sr=SR)
    hop = 256
    t = np.arange(len(y) // hop + 1) * hop / SR
    mask = np.zeros(len(t), bool)
    for w in words:
        if w.get("p", 1) >= MIN_PROB:
            mask |= (t >= w["s"]) & (t <= w["e"])
    if windows is not None:
        wm = np.zeros(len(t), bool)
        for a, b in windows:
            wm |= (t >= a) & (t < b)
        mask &= wm
    idx = np.flatnonzero(mask)
    if len(idx) < MIN_VOICED:
        return None, int(len(idx))
    idx = idx[:120 * SR // hop]  # cap at ~2 min of speech
    # concatenate masked frames into one signal (with small padding), run pyin once
    seg = np.concatenate([y[i * hop:(i + 1) * hop] for i in idx])
    f0, vflag, vprob = librosa.pyin(seg, fmin=70, fmax=500, sr=SR, frame_length=1024, hop_length=hop)
    f = f0[vflag & np.isfinite(f0)]
    if len(f) < MIN_VOICED:
        return None, int(len(f))
    # 20th percentile: the floor of the speaking range moves with a pitch-raising speed-up
    # but is less inflated than the median by shouting or excited bursts
    return float(np.percentile(f, 20)), int(len(f))


def st(hz):
    return 12 * np.log2(hz / 55.0)


def measure(model, src, tag, tmp, sound_csv, filt=None, scale=1.0):
    wav = tmp / f"{tag}.wav"
    if not wav.exists():
        extract(src, wav, filt)
    words = transcribe(model, wav, tmp / f"{tag}.words.json")
    med, q75, nw, nr = articulation(words)
    f0, nv = f0_median(wav, words, speech_windows(sound_csv, scale))
    return dict(rate_med=med, rate_q75=q75, words_used=nw, runs=nr, f0=f0, voiced=nv)


def load_meta():
    fm = json.load(open(ROOT / "formats.json", encoding="utf-8"))
    reels = []
    for c in sorted(p.name for p in (ROOT / "set").iterdir() if p.is_dir()):
        for f in sorted((ROOT / "set" / c).glob("*.mp4")):
            key = f.stem.split("_")[0]
            reels.append(dict(creator=c, reel=f.stem, key=key, path=f,
                              group="outlier" if key.startswith("out") else "flop",
                              format=fm.get(c, {}).get(key, ""),
                              shortcode=f.stem.split("_", 2)[2]))
    return reels


def verdict(r, base_st):
    """Rules set from the sanity check: on clean speech a real 1.5x copy raises articulation
    rate x1.44-1.55 and (without pitch correction) the F0 floor +7 st; 1.25x gives x1.2 and +4 st."""
    rate, f0 = r["rate_med"], r["f0"]
    lift = (st(f0) - base_st) if (f0 and base_st is not None) else None
    r["pitch_lift_st"] = None if lift is None else round(lift, 1)
    enough = r["words_used"] >= MIN_WORDS and r["runs"] >= MIN_RUNS
    if not enough:
        why = f"only {r['words_used']} usable words in speech runs (music, silence or sparse speech)"
        return "cannot tell", "", why
    if rate < 3.0:
        return "cannot tell", "", f"articulation {rate:.1f} syl/s is implausibly slow: whisper timestamps unreliable here"
    pitch_fac = 2 ** (lift / 12) if (lift is not None and lift >= PITCH_LIFT) else None
    # a pitch lift is only credible as a speed-up if undoing it leaves a plausible talking rate
    pitch_ok = pitch_fac is not None and rate / pitch_fac >= 3.3
    ptxt = "" if lift is None else f", F0 floor {lift:+.1f} st vs creator's lowest"
    if rate >= RATE_FAST:
        fac = pitch_fac if pitch_ok else rate / 5.0
        return "likely sped up", round(fac, 2), f"articulation {rate:.1f} syl/s, above natural range{ptxt}"
    if pitch_ok and rate >= 6.0:
        return "likely sped up", round(pitch_fac, 2), f"fast speech {rate:.1f} syl/s and raised pitch{ptxt}, consistent with ~{pitch_fac:.2f}x without pitch correction"
    if rate < RATE_NORMAL and not pitch_ok:
        extra = " (pitch lift too large for the speech rate: other voice or shouting, not speed)" if pitch_fac else ""
        return "likely normal", "", f"articulation {rate:.1f} syl/s, natural range{ptxt}{extra}; a 1.2-1.3x speed-up cannot be excluded"
    return "cannot tell", "", f"borderline: articulation {rate:.1f} syl/s{ptxt}; natural fast talk and a mild speed-up overlap here"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmp", default=None)
    ap.add_argument("--sanity", default="", help="comma list creator/key, e.g. tjr/flop04")
    ap.add_argument("--model", default="medium")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp = Path(a.tmp) if a.tmp else ROOT / "_tmp_speed"; tmp.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(a.model, device="cuda", compute_type="float16")
    except Exception as e:
        print("CUDA unavailable:", e); model = WhisperModel(a.model, device="cpu", compute_type="int8")
    reels = load_meta()
    for r in reels:
        print("->", r["creator"], r["reel"], flush=True)
        sc = ROOT / "analysis_set" / r["creator"] / r["reel"] / "sound.csv"
        r.update(measure(model, r["path"], f"{r['creator']}__{r['key']}", tmp, sc))

    # creator pitch baseline: 20th percentile of that creator's reel F0 floors (semitones)
    base = {}
    for c in {r["creator"] for r in reels}:
        v = sorted(st(r["f0"]) for r in reels if r["creator"] == c and r["f0"])
        base[c] = float(np.percentile(v, 20)) if v else None  # robust to one octave-error reel
    for r in reels:
        r["verdict"], r["factor"], r["reason"] = verdict(r, base[r["creator"]])

    cols = ["creator", "reel", "group", "format", "words_used", "rate_med", "rate_q75", "f0_hz",
            "pitch_lift_st", "est_speed_factor", "verdict", "reason", "url"]
    with open(out / "speed_check.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in reels:
            w.writerow([r["creator"], r["reel"], r["group"], r["format"], r["words_used"],
                        "" if r["rate_med"] is None else round(r["rate_med"], 2),
                        "" if r["rate_q75"] is None else round(r["rate_q75"], 2),
                        "" if r["f0"] is None else round(r["f0"], 1),
                        "" if r["pitch_lift_st"] is None else r["pitch_lift_st"],
                        r["factor"], r["verdict"], r["reason"],
                        f"https://www.instagram.com/reel/{r['shortcode']}/"])
    print("creator pitch baselines (st re 55 Hz):", {k: None if v is None else round(v, 1) for k, v in base.items()})

    if a.sanity:
        print("\nSANITY CHECK")
        byk = {f"{r['creator']}/{r['key']}": r for r in reels}
        for k in a.sanity.split(","):
            r = byk[k]
            sc = ROOT / "analysis_set" / r["creator"] / r["reel"] / "sound.csv"
            print(f"{k}: orig rate {r['rate_med']:.2f} (q75 {r['rate_q75']:.2f}) words {r['words_used']} f0 {r['f0']}")
            for fac in (1.25, 1.5):
                for kind, filt in (("atempo", f"atempo={fac}"), ("asetrate", f"asetrate={SR * fac:.0f},aresample={SR}")):
                    tag = f"{r['creator']}__{r['key']}__{kind}{fac}"
                    m = measure(model, tmp / f"{r['creator']}__{r['key']}.wav", tag, tmp, sc, filt, fac)
                    d = f"{st(m['f0']) - st(r['f0']):+.1f} st" if (m["f0"] and r["f0"]) else "n/a"
                    print(f"   {kind} {fac}: rate {m['rate_med']:.2f} (x{m['rate_med'] / r['rate_med']:.2f}) "
                          f"q75 {m['rate_q75']:.2f} words {m['words_used']} f0 {m['f0']} ({d})", flush=True)


if __name__ == "__main__":
    main()
