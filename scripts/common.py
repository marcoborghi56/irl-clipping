"""Shared helpers for the clipping pipeline: paths (from ../config.json), .env loading, ffprobe, atomic file writes, time formatting."""
import json, os, subprocess
from fractions import Fraction
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent          # <skill>/scripts
SKILL = PIPELINE.parent
REFS = SKILL / "references"                          # PLAYBOOK.md, rubric.md, style.json, qa_brief.md
ASSETS = SKILL / "assets"                            # face_yunet.onnx
RESEARCH = PIPELINE                                  # sound.py sits beside the pipeline scripts
_CFG_PATH = SKILL / "config.json"                    # machine-specific paths live there, not in code
CONFIG = json.loads(_CFG_PATH.read_text(encoding="utf-8")) if _CFG_PATH.is_file() else {}
DATA_ROOT = Path(os.environ.get("CLIPPING_DATA") or CONFIG.get("data_root") or Path.cwd())
WORK_DIR = DATA_ROOT / "work"
CLIPS_DIR = DATA_ROOT / "clips"
ENV_PATH = Path(os.environ.get("CLIPPING_ENV") or CONFIG.get("env_path") or (SKILL / ".env"))

MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm", ".3gp", ".mxf",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


# ---------- paths ----------
def media_files(folder, recursive=False):
    """Media files in a folder (sorted by name). Non-recursive unless asked."""
    folder = Path(folder)
    it = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in MEDIA_EXT)


def work_dir_for(src, work_root=WORK_DIR):
    """work/<source-stem>/ for a media file (created)."""
    d = Path(work_root) / Path(src).stem
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- secrets ----------
def load_env(path=ENV_PATH):
    """Parse a .env file into a dict (KEY=VALUE, optional quotes / 'export ', # comments). Does not touch os.environ."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        out[k.strip()] = v
    return out


def get_secret(name, path=ENV_PATH):
    """Secret from the environment, else from the .env file. Never print the return value."""
    v = os.environ.get(name) or load_env(path).get(name)
    if not v:
        raise RuntimeError(f"{name} not found in environment or {path}")
    return v


# ---------- ffprobe ----------
def ffprobe_raw(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def _rate(s):
    try:
        f = Fraction(s)
        return round(float(f), 3) if f > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _rotation(vs):
    for sd in vs.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                return int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    try:
        return int((vs.get("tags") or {}).get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def probe(path):
    """probe.json fields: path, duration, width/height (display, after rotation), fps, rotation, vcodec, pix_fmt,
    color_transfer, color_primaries, is_hdr, audio_streams, size_bytes. Video fields are None for audio-only files."""
    path = Path(path).resolve()
    info = ffprobe_raw(path)
    streams = info.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video"
               and not (s.get("disposition") or {}).get("attached_pic")), None)
    n_audio = sum(1 for s in streams if s.get("codec_type") == "audio")
    dur = None
    try:
        dur = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        durs = [float(s["duration"]) for s in streams if s.get("duration") not in (None, "N/A")]
        dur = max(durs) if durs else None
    out = {"path": str(path), "duration": round(dur, 3) if dur else None, "width": None, "height": None, "fps": None,
           "rotation": 0, "vcodec": None, "pix_fmt": None, "color_transfer": None, "color_primaries": None,
           "is_hdr": False, "audio_streams": n_audio, "size_bytes": path.stat().st_size}
    if vs:
        rot = _rotation(vs)
        w, h = vs.get("width"), vs.get("height")
        if rot % 180 != 0:
            w, h = h, w
        dovi = any("DOVI" in (sd.get("side_data_type") or "") for sd in vs.get("side_data_list", []) or [])
        out.update(width=w, height=h, rotation=rot, vcodec=vs.get("codec_name"), pix_fmt=vs.get("pix_fmt"),
                   fps=_rate(vs.get("avg_frame_rate")) or _rate(vs.get("r_frame_rate")),
                   color_transfer=vs.get("color_transfer"), color_primaries=vs.get("color_primaries"),
                   is_hdr=bool(vs.get("color_transfer") in HDR_TRANSFERS or dovi))
    return out


# ---------- files ----------
def write_atomic(path, data, mode="w"):
    """Write text/bytes to path via a temp file + rename, so a crash never leaves a half-written 'finished' file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    if mode == "w":
        tmp.write_text(data, encoding="utf-8", newline="\n")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path, obj, indent=1):
    write_atomic(path, json.dumps(obj, indent=indent, ensure_ascii=False))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------- time ----------
def fmt_ts(t):
    """Seconds -> 'MM:SS.s' (minutes keep counting past 59, e.g. 125:03.4)."""
    t = max(0.0, round(float(t), 1))
    m = int(t // 60)
    return f"{m:02d}:{t - m * 60:04.1f}"


def parse_ts(s):
    """'MM:SS.s' or 'H:MM:SS.s' -> seconds."""
    parts = [float(x) for x in s.strip().split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t
