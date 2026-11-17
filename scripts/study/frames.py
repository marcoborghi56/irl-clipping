"""Per-frame visual analysis of every reel in <dir>/<creator>/*.mp4.

Every frame:      luma, frame difference, camera motion (dx, dy), zoom scale (via tracked features)
5x per second:    face (size as share of frame height, centre x/y), on-screen text boxes + recognised text
Writes analysis_<dir>/<creator>/<name>/frames.csv, text.csv, visual.json and motion.png.

Usage: python frames.py [--dir set] [--only creator] [--ocr-fps 5]
"""
import argparse, csv, json, math
import os
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(os.environ.get("STUDY_ROOT") or Path.cwd()).resolve()  # study data root (reels, analysis), not the skill folder
W = 360  # analysis width


def affine_scale(prev, cur):
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=200, qualityLevel=0.01, minDistance=8)
    if pts is None or len(pts) < 12:
        return 1.0, 0.0, 0.0
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(21, 21), maxLevel=3)
    good = st.ravel() == 1
    if good.sum() < 12:
        return 1.0, 0.0, 0.0
    M, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None:
        return 1.0, 0.0, 0.0
    return float(math.hypot(M[0, 0], M[1, 0])), float(M[0, 2]), float(M[1, 2])


def run(p, out, face, ocr, ocr_fps):
    cap = cv2.VideoCapture(str(p))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ocr_every = max(1, round(fps / ocr_fps))
    rows, texts = [], []
    prev, i = None, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        h0, w0 = f.shape[:2]
        H = int(h0 * W / w0)
        small = cv2.resize(f, (W, H))
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        t = i / fps
        diff = float(np.mean(cv2.absdiff(g, prev))) if prev is not None else 0.0
        s, dx, dy = affine_scale(prev, g) if prev is not None else (1.0, 0.0, 0.0)
        r = dict(f=i, t=round(t, 3), luma=round(float(g.mean()), 1), diff=round(diff, 2),
                 scale=round(s, 4), dx=round(dx, 2), dy=round(dy, 2), face_h="", face_x="", face_y="", n_faces="", text_boxes="")
        if i % ocr_every == 0:
            face.setInputSize((W, H))
            _, faces = face.detect(small)
            if faces is not None and len(faces):
                big = max(faces, key=lambda z: z[3])
                r.update(face_h=round(big[3] / H, 3), face_x=round((big[0] + big[2] / 2) / W, 3),
                         face_y=round((big[1] + big[3] / 2) / H, 3), n_faces=len(faces))
            else:
                r.update(face_h=0, n_faces=0)
            res, _ = ocr(cv2.resize(f, (720, int(h0 * 720 / w0))))
            res = [x for x in (res or []) if x[2] > 0.6]
            r["text_boxes"] = len(res)
            Hh = int(h0 * 720 / w0)
            for box, txt, conf in res:
                ys = [pt[1] for pt in box]; xs = [pt[0] for pt in box]
                texts.append(dict(t=round(t, 2), text=txt, conf=round(conf, 2), y=round((min(ys) + max(ys)) / 2 / Hh, 3),
                                  h=round((max(ys) - min(ys)) / Hh, 3), x=round((min(xs) + max(xs)) / 2 / 720, 3),
                                  w=round((max(xs) - min(xs)) / 720, 3), words=len(txt.split())))
        rows.append(r)
        prev = g
        i += 1
    cap.release()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "frames.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with open(out / "text.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t", "text", "conf", "y", "h", "x", "w", "words"]); w.writeheader(); w.writerows(texts)
    summarize(rows, texts, fps, out, p)


def summarize(rows, texts, fps, out, p):
    n = len(rows); dur = n / fps
    diff = np.array([r["diff"] for r in rows]); scale = np.array([r["scale"] for r in rows])
    dx = np.array([r["dx"] for r in rows]); dy = np.array([r["dy"] for r in rows])
    cut = diff > max(25.0, np.percentile(diff, 99.5) * 0.6)  # big jumps = hard cuts / flashes
    # zoom: cumulative log-scale over 0.5s windows, ignoring cut frames
    ls = np.where(cut, 0.0, np.log(np.clip(scale, 0.5, 2.0)))
    win = max(1, int(fps * 0.5))
    roll = np.convolve(ls, np.ones(win), "same")
    zoom_in = roll > math.log(1.06); zoom_out = roll < -math.log(1.06)
    def events(mask):
        ev, on = [], False
        for k, m in enumerate(mask):
            if m and not on: ev.append(round(k / fps, 2)); on = True
            elif not m: on = False
        return ev
    shake = float(np.median(np.hypot(dx, dy)[~cut])) if (~cut).any() else 0.0
    sampled = [r for r in rows if r["n_faces"] != ""]
    fh = [r["face_h"] for r in sampled]
    face_present = float(np.mean([v > 0 for v in fh])) if fh else 0.0
    face_size = float(np.median([v for v in fh if v > 0])) if any(v > 0 for v in fh) else 0.0
    face_x = [r["face_x"] for r in sampled if r["face_h"]]
    txt_frames = [r for r in sampled if r["text_boxes"]]
    text_cov = len(txt_frames) / len(sampled) if sampled else 0.0
    # caption changes: distinct consecutive OCR strings
    by_t = {}
    for x in texts: by_t.setdefault(x["t"], []).append(x)
    seq = [" ".join(sorted(z["text"] for z in by_t[t])) for t in sorted(by_t)]
    changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    ys = [x["y"] for x in texts]; hs = [x["h"] for x in texts]; wds = [x["words"] for x in texts]
    v = dict(file=str(p.relative_to(ROOT)), frames=n, fps=round(fps, 2), duration=round(dur, 2),
             hard_cuts=int(cut.sum()), hard_cut_times=[round(k / fps, 2) for k in np.where(cut)[0]],
             zoom_in_events=events(zoom_in), zoom_out_events=events(zoom_out),
             zoom_events_per_10s=round((len(events(zoom_in)) + len(events(zoom_out))) / dur * 10, 2),
             camera_motion_px_per_frame=round(shake, 2),
             mean_luma=round(float(np.mean([r["luma"] for r in rows])), 1),
             face_present_ratio=round(face_present, 2), face_height_median=round(face_size, 3),
             face_x_median=round(float(np.median(face_x)), 2) if face_x else None,
             text_on_screen_ratio=round(text_cov, 2), text_changes_per_sec=round(changes / dur, 2),
             text_y_median=round(float(np.median(ys)), 2) if ys else None,
             text_height_median=round(float(np.median(hs)), 3) if hs else None,
             words_per_text_box_median=float(np.median(wds)) if wds else None,
             first_text_at=min(by_t) if by_t else None,
             first_text=" | ".join(z["text"] for z in by_t[min(by_t)]) if by_t else None)
    (out / "visual.json").write_text(json.dumps(v, indent=1, ensure_ascii=False), encoding="utf-8")
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    t = np.arange(n) / fps
    fig, ax = plt.subplots(3, 1, figsize=(14, 5.5), sharex=True)
    ax[0].plot(t, diff, lw=.6, c="#333"); ax[0].set_ylabel("frame diff")
    for c in v["hard_cut_times"]: [a.axvline(c, c="#d33", lw=.5, alpha=.6) for a in ax]
    ax[1].plot(t, roll, lw=.8, c="#36c"); ax[1].axhline(0, c="#999", lw=.5); ax[1].set_ylabel("zoom (0.5s)")
    st = [r["t"] for r in sampled]
    ax[2].plot(st, [r["face_h"] or 0 for r in sampled], lw=.8, c="#c63", label="face height")
    ax[2].plot(st, [min(r["text_boxes"] or 0, 6) / 6 for r in sampled], lw=.8, c="#3a7", label="text boxes/6")
    ax[2].legend(loc="upper right", fontsize=7); ax[2].set_xlabel("s")
    fig.suptitle(f"{p.parent.name}/{p.stem}", fontsize=9); fig.tight_layout(); fig.savefig(out / "motion.png", dpi=85); plt.close(fig)


def ensure_disk(min_gb=10):
    import shutil
    free = shutil.disk_usage(Path(__file__).resolve().anchor).free / 1e9
    if free < min_gb:
        raise SystemExit(f"Stopping: only {free:.1f} GB free on disk (minimum buffer {min_gb} GB).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="set"); ap.add_argument("--only"); ap.add_argument("--ocr-fps", type=float, default=5)
    a = ap.parse_args()
    src, dst = ROOT / a.dir, ROOT / f"analysis_{a.dir}"
    face = cv2.FaceDetectorYN.create(str(Path(__file__).resolve().parents[2] / "assets" / "face_yunet.onnx"), "", (320, 320), 0.7)
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    files = sorted(src.glob(f"{a.only or '*'}/*.mp4"))
    for k, p in enumerate(files, 1):
        out = dst / p.parent.name / p.stem
        if (out / "visual.json").exists():
            continue
        ensure_disk()
        print(f"[{k}/{len(files)}] {p.parent.name}/{p.name}", flush=True)
        try:
            run(p, out, face, ocr, a.ocr_fps)
        except Exception as e:
            print("   FAILED:", e, flush=True)


if __name__ == "__main__":
    main()
