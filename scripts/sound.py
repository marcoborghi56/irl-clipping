"""Sound-event labeling for every reel: music / speech / laughter / shouting / crowd / sound effects, per 0.5s.

Uses PANNs Cnn14_DecisionLevelMax (AudioSet, 527 classes, frame-level). CPU is fine: audio only.
Writes analysis_<dir>/<creator>/<name>/sound.json (+ sound.csv with per-0.5s group scores).

Usage: python sound.py [--dir set] [--only creator]
Reusable on raw footage: `label_file(path)` returns the same structure for any media file ffmpeg can read.
"""
import argparse, csv, json, subprocess
import os
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("STUDY_ROOT") or Path.cwd()).resolve()  # study data root (reels, analysis), not the skill folder
SR = 32000
GROUPS = {
    "speech": ["Speech", "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking", "Conversation", "Narration, monologue"],
    "music": ["Music", "Musical instrument", "Singing", "Rapping", "Hip hop music", "Pop music", "Electronic music", "Rock music", "Background music",
              "Soundtrack music", "Beatboxing", "Drum", "Bass guitar", "Piano", "Synthesizer", "Theme music", "Jingle (music)", "Trap music", "Drum machine"],
    "laughter": ["Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"],
    "shout": ["Shout", "Bellow", "Whoop", "Yell", "Battle cry", "Children shouting", "Screaming"],
    "crowd": ["Crowd", "Cheering", "Applause", "Chatter", "Hubbub, speech noise, speech babble", "Clapping"],
    "sfx": ["Whoosh, swoosh, swish", "Boom", "Sound effect", "Thump, thud", "Slap, smack", "Ding", "Beep, bleep", "Explosion", "Gunshot, gunfire",
            "Whip", "Boing", "Bang", "Smash, crash", "Glass", "Ding-dong", "Bell", "Buzzer", "Cash register", "Whistle", "Zing", "Burst, pop", "Clang", "Rumble", "Squeal"],
    "vehicle": ["Vehicle", "Car", "Engine", "Motor vehicle (road)", "Accelerating, revving, vroom", "Skidding", "Tire squeal", "Motorcycle", "Car passing by", "Race car, auto racing"],
}
# Frame-level scores for non-dominant classes are low (especially under music), so event thresholds are deliberately low.
THRESH = {"speech": 0.3, "music": 0.25, "laughter": 0.05, "shout": 0.04, "crowd": 0.08, "sfx": 0.06, "vehicle": 0.15}
_model = None


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def model():
    global _model
    if _model is None:
        from panns_inference import SoundEventDetection, labels
        _model = (SoundEventDetection(checkpoint_path=None, device="cpu"), list(labels))
    return _model


def frame_probs(y, chunk_s=30):
    """Frame-level class probabilities (100 fps) for arbitrarily long audio, processed in chunks."""
    sed, _ = model()
    out = []
    for i in range(0, len(y), chunk_s * SR):
        seg = y[i:i + chunk_s * SR]
        if len(seg) < SR:  # pad tiny tail
            seg = np.pad(seg, (0, SR - len(seg)))
        out.append(sed.inference(seg[None, :])[0])
    return np.concatenate(out, 0)


def events(mask, step):
    ev, start = [], None
    for k, m in enumerate(list(mask) + [False]):
        if m and start is None: start = k
        elif not m and start is not None:
            ev.append([round(start * step, 1), round(k * step, 1)]); start = None
    return ev


def label_audio(y, step=0.5):
    _, labels = model()
    if len(y) < SR // 2:
        return None, None
    fp = frame_probs(y)
    hop = int(step * 100)
    n = len(fp) // hop
    win = fp[:n * hop].reshape(n, hop, -1).max(1)  # per-0.5s max probability per class
    idx = {g: [labels.index(l) for l in ls if l in labels] for g, ls in GROUPS.items()}
    scores = {g: win[:, ix].max(1) for g, ix in idx.items()}
    dur = n * step
    summary = {"duration": round(dur, 1)}
    for g, s in scores.items():
        m = s > THRESH[g]
        ev = events(m, step)
        summary[g] = {"ratio": round(float(m.mean()), 2), "first_at": ev[0][0] if ev else None, "events": ev[:40], "n_events": len(ev)}
    # name the specific sfx / other notable labels with when they peak
    named = []
    for g in ("sfx", "laughter", "shout", "crowd", "vehicle"):
        for ix in idx[g]:
            p = win[:, ix]
            if p.max() > THRESH[g]:
                named.append({"label": labels[ix], "peak": round(float(p.max()), 2), "at": round(float(p.argmax() * step), 1),
                              "seconds": round(float((p > THRESH[g]).sum() * step), 1)})
    summary["named_events"] = sorted(named, key=lambda d: -d["peak"])[:15]
    top = win.mean(0).argsort()[::-1][:10]
    summary["top_labels"] = [{"label": labels[i], "mean": round(float(win[:, i].mean()), 2)} for i in top]
    rows = [dict(t=round(k * step, 1), **{g: round(float(scores[g][k]), 2) for g in scores}) for k in range(n)]
    return summary, rows


def beat_sync(y, cuts):
    """Tempo + share of cuts that land within 80 ms of a beat (only meaningful when music is present)."""
    import librosa
    tempo, beats = librosa.beat.beat_track(y=y, sr=SR, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    if not len(cuts) or not len(beats):
        return {"tempo_bpm": round(tempo, 1), "cuts_on_beat": None}
    on = sum(1 for c in cuts if np.min(np.abs(beats - c)) <= 0.08)
    # chance level: fraction of time within +-80ms of any beat
    chance = min(1.0, len(beats) * 0.16 / max(len(y) / SR, 1e-6))
    return {"tempo_bpm": round(tempo, 1), "cuts_on_beat": round(on / len(cuts), 2), "chance_level": round(chance, 2), "n_cuts": len(cuts)}


def label_file(path, cuts=None):
    y = decode(path)
    summary, rows = label_audio(y)
    if summary is not None and cuts is not None and summary["music"]["ratio"] >= 0.3:
        summary["beat_sync"] = beat_sync(y, cuts)
    return summary, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="set"); ap.add_argument("--only")
    a = ap.parse_args()
    src, dst = ROOT / a.dir, ROOT / f"analysis_{a.dir}"
    files = sorted(src.glob(f"{a.only or '*'}/*.mp4"))
    for k, p in enumerate(files, 1):
        out = dst / p.parent.name / p.stem
        if (out / "sound.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        cuts = None
        if (out / "meta.json").exists():
            cuts = json.loads((out / "meta.json").read_text(encoding="utf-8")).get("cuts")
        try:
            summary, rows = label_file(p, cuts)
        except Exception as e:
            print(f"[{k}/{len(files)}] FAILED {p.name}: {e}", flush=True); continue
        if summary is None:
            summary, rows = {"duration": 0, "no_audio": True}, []
        (out / "sound.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        if rows:
            with open(out / "sound.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        print(f"[{k}/{len(files)}] {p.parent.name}/{p.stem}", flush=True)


if __name__ == "__main__":
    main()
