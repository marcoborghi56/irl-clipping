"""Frame-by-frame + audio analysis of downloaded reels.

For every reels/<creator>/*.mp4 it writes analysis/<creator>/<name>/ containing:
  meta.json        duration, fps, resolution, cuts, shot lengths, loudness, speech stats, words
  hook.jpg         frames every 0.25s across the first 3s (the hook)
  shots.jpg        one frame per detected shot (mid-shot), in order
  timeline.jpg     one frame every 1s across the whole reel
  energy.png       loudness (RMS) curve with cut markers and speech spans
Then writes analysis/summary.csv with one row per reel.

Usage: python analyze.py [--model medium] [--only creator]
"""
import argparse, csv, json, math, os, subprocess, sys
from pathlib import Path

# Make pip-installed CUDA DLLs (nvidia-cublas-cu12 / nvidia-cudnn-cu12) visible on Windows.
try:
    import nvidia
    for _base in nvidia.__path__:
        for _bin in Path(_base).glob("*/bin"):
            os.add_dll_directory(str(_bin))
            os.environ["PATH"] = str(_bin) + os.pathsep + os.environ["PATH"]
except ImportError:
    pass

import cv2
import numpy as np

ROOT = Path(os.environ.get("STUDY_ROOT") or Path.cwd()).resolve()  # study data root (reels, analysis), not the skill folder
REELS, OUT = ROOT / "reels", ROOT / "analysis"


def probe(p):
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)],
                                  capture_output=True, text=True).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    num, den = map(int, v["r_frame_rate"].split("/"))
    return {"duration": float(j["format"]["duration"]), "fps": round(num / den, 2), "w": v["width"], "h": v["height"],
            "has_audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def detect_cuts(p, threshold=27.0):
    from scenedetect import detect, ContentDetector
    scenes = detect(str(p), ContentDetector(threshold=threshold, min_scene_len=4))
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def grab(cap, t, w=270):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0) * 1000)
    ok, f = cap.read()
    if not ok:
        return None
    h = int(f.shape[0] * w / f.shape[1])
    f = cv2.resize(f, (w, h))
    cv2.rectangle(f, (0, 0), (78, 22), (0, 0, 0), -1)
    cv2.putText(f, f"{t:5.2f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return f


def sheet(frames, path, cols=6):
    frames = [f for f in frames if f is not None]
    if not frames:
        return
    h, w = frames[0].shape[:2]
    frames = [cv2.resize(f, (w, h)) for f in frames]
    rows = math.ceil(len(frames) / cols)
    canvas = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = f
    cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 82])


def loudness(p):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    tail = r[r.rfind("Summary:"):]
    get = lambda k: next((float(l.split(":")[1].split()[0]) for l in tail.splitlines() if l.strip().startswith(k)), None)
    return {"lufs_integrated": get("I:"), "loudness_range": get("LRA:")}


def decode(p, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def energy(y, sr=16000):
    import librosa
    hop = 1600  # 0.1s
    rms = librosa.feature.rms(y=y, frame_length=3200, hop_length=hop)[0]
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    return rms, hop / sr, onsets


def transcribe(model, audio):
    segs, info = model.transcribe(audio, word_timestamps=True, vad_filter=True)
    words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for s in segs for w in (s.words or [])]
    return words, info.language


def analyze(p, model):
    out = OUT / p.parent.name / p.stem
    if (out / "meta.json").exists():
        return json.loads((out / "meta.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    m = probe(p)
    d = m["duration"]
    shots = detect_cuts(p) or [(0.0, d)]
    lens = [round(e - s, 2) for s, e in shots]
    cuts = [round(s, 2) for s, _ in shots[1:]]

    cap = cv2.VideoCapture(str(p))
    sheet([grab(cap, t) for t in np.arange(0, min(3.0, d), 0.25)], out / "hook.jpg", cols=6)
    sheet([grab(cap, (s + e) / 2) for s, e in shots], out / "shots.jpg", cols=8)
    sheet([grab(cap, t, 180) for t in np.arange(0, d, 1.0)], out / "timeline.jpg", cols=10)
    cap.release()

    words, lang, loud = [], None, {}
    if m["has_audio"]:
        loud = loudness(p)
        audio = decode(p)
        words, lang = transcribe(model, audio)
        rms, step, onsets = energy(audio)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(14, 2.6))
        ax.plot(np.arange(len(rms)) * step, 20 * np.log10(rms + 1e-6), lw=0.8, color="#333")
        for c in cuts:
            ax.axvline(c, color="#d33", lw=0.6, alpha=0.7)
        for w in words:
            ax.axvspan(w["s"], w["e"], color="#3a7", alpha=0.15, lw=0)
        ax.set_xlim(0, d); ax.set_xlabel("s"); ax.set_ylabel("dB")
        ax.set_title(f"{p.parent.name}/{p.stem}  red=cuts  green=speech")
        fig.tight_layout(); fig.savefig(out / "energy.png", dpi=90); plt.close(fig)
    else:
        onsets = []

    speech = sum(w["e"] - w["s"] for w in words)
    meta = {
        "file": str(p.relative_to(ROOT)), **m, **loud, "language": lang,
        "n_shots": len(shots), "cuts": cuts, "shot_lengths": lens,
        "avg_shot_len": round(float(np.mean(lens)), 2), "median_shot_len": round(float(np.median(lens)), 2),
        "cuts_per_10s": round(len(cuts) / d * 10, 2),
        "first_cut": cuts[0] if cuts else None,
        "first_word_at": words[0]["s"] if words else None,
        "words": len(words), "words_per_sec": round(len(words) / d, 2),
        "speech_ratio": round(speech / d, 2),
        "audio_onsets_per_sec": round(len(onsets) / d, 2),
        "hook_text_3s": " ".join(w["w"] for w in words if w["s"] < 3.0),
        "transcript": " ".join(w["w"] for w in words),
        "word_timings": words,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def ensure_disk(min_gb=10):
    import shutil
    free = shutil.disk_usage(Path(__file__).resolve().anchor).free / 1e9
    if free < min_gb:
        raise SystemExit(f"Stopping: only {free:.1f} GB free on disk (minimum buffer {min_gb} GB).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="medium")
    ap.add_argument("--only")
    ap.add_argument("--dir", default="set", help="folder of <creator>/*.mp4 (relative to this script)")
    a = ap.parse_args()
    global REELS, OUT
    REELS, OUT = ROOT / a.dir, ROOT / ("analysis" if a.dir == "reels" else f"analysis_{a.dir}")
    files = sorted(REELS.glob(f"{a.only or '*'}/*.mp4"))
    if not files:
        sys.exit(f"No mp4 files under {REELS}")
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(a.model, device="cuda", compute_type="float16")
    except Exception as e:
        print("CUDA unavailable, using CPU:", e)
        model = WhisperModel(a.model, device="cpu", compute_type="int8")
    rows = []
    for p in files:
        ensure_disk()
        print("->", p.relative_to(ROOT), flush=True)
        m = analyze(p, model)
        rows.append({k: m.get(k) for k in ["file", "duration", "w", "h", "fps", "n_shots", "avg_shot_len", "median_shot_len",
                                           "cuts_per_10s", "first_cut", "first_word_at", "words_per_sec", "speech_ratio",
                                           "audio_onsets_per_sec", "lufs_integrated", "language", "hook_text_3s"]})
    OUT.mkdir(exist_ok=True)
    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print("done:", len(rows), "reels ->", OUT / "summary.csv")


if __name__ == "__main__":
    main()
