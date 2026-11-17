"""Media file -> probe.json, audio.mp3, sound.csv, loudness.csv, transcript.json, timeline_NNN.md (see DESIGN.md).

Usage:
  python ingest.py <media-file-or-folder> --work <work-dir> [--recursive] [--no-transcribe] [--language xx] [--force-timeline]

Writes <work-dir>/<source-stem>/... . Idempotent: every stage is skipped when its output exists (outputs are written
atomically). Stage order: probe -> audio proxy -> sound+loudness (one streaming pass) -> transcript -> timeline.
"""
import argparse, csv, json, math, subprocess, sys, time
from pathlib import Path

import numpy as np

from common import (RESEARCH, WORK_DIR, fmt_ts, get_secret, media_files, probe, read_json, work_dir_for,
                    write_atomic, write_json)

sys.path.insert(0, str(RESEARCH))
import sound  # noqa: E402  scripts/sound.py: SR, GROUPS, THRESH, model()

GROUP_ORDER = ["speech", "music", "laughter", "shout", "crowd", "sfx", "vehicle"]
SOUND_STEP = 0.5          # sound.csv resolution (s)
LOUD_STEP = 0.1           # loudness.csv resolution (s)
PANN_CHUNK_S = 30         # seconds of audio per PANNs inference (bounded memory)
TAGS = [("laughter", "LAUGH"), ("shout", "SHOUT"), ("crowd", "CROWD"), ("music", "MUSIC")]
LOUD_DB = 8.0             # LOUD tag: peak more than this above median speech loudness
PAUSE_SPLIT = 0.7         # new utterance after a pause longer than this
SILENCE_LINE = 2.0        # '-- silence --' line for speech gaps longer than this
UTT_SOFT_MAX, UTT_HARD_MAX = 12.0, 20.0  # split very long utterances (at sentence end / hard)
CHUNK_S, OVERLAP_S, MAX_BYTES, MIN_CHUNK_S = 600.0, 60.0, 9000, 120.0

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODELS = ["scribe_v3", "scribe_v2", "scribe_v1"]   # newest first; first one the API accepts is kept
STT_MAX_SINGLE_S = 4 * 3600   # longer ranges are split at quiet points before upload
STT_MIN_PIECE_S = 300
_stt_model = None


def log(msg):
    try:
        print(msg, flush=True)
    except (OSError, ValueError):  # a closed/broken console must never kill a long run
        pass


# ---------------------------------------------------------------- probe / audio proxy
def stage_probe(src, wd):
    p = wd / "probe.json"
    if p.exists():
        old = read_json(p)
        if old.get("size_bytes") == src.stat().st_size:
            if old.get("path") != str(src):   # same file, moved/copied: keep stages, fix the path
                old["path"] = str(src)
                write_json(p, old)
            return old
        log("  source changed since last run: redoing all stages")
        for f in list(wd.glob("*")):
            if f.is_file():
                f.unlink()
    info = probe(src)
    write_json(p, info)
    return info


def stage_audio(src, wd, info):
    out = wd / "audio.mp3"
    if out.exists() or not info["audio_streams"]:
        return
    tmp = wd / "audio.part.mp3"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "libmp3lame", "-b:a", "64k", str(tmp)], capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"audio proxy failed: {r.stderr.strip()[:300]}")
    tmp.replace(out)


# ---------------------------------------------------------------- sound labels + loudness (single streaming pass)
def _stream_pcm(src, sr, block_s):
    """Yield float32 mono blocks of block_s seconds from the first audio stream, without holding the whole file."""
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr),
                             "-f", "f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    nbytes = int(block_s * sr) * 4
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if not buf:
                break
            buf = buf[:len(buf) // 4 * 4]
            if buf:
                yield np.frombuffer(buf, np.float32)
    finally:
        proc.stdout.close()
        proc.wait()


def _pann_windows(seg, sed, idx):
    """Per-0.5 s max probability per group for one block (<= PANN_CHUNK_S seconds)."""
    sr = sound.SR
    n = math.ceil(len(seg) / (SOUND_STEP * sr))
    x = seg if len(seg) >= sr else np.pad(seg, (0, sr - len(seg)))  # model needs >= 1 s
    fp = sed.inference(x[None, :].astype(np.float32))[0]           # (frames @100 fps, 527)
    hop = int(SOUND_STEP * 100)
    rows = np.zeros((n, len(GROUP_ORDER)), np.float32)
    for k in range(n):
        w = fp[k * hop:(k + 1) * hop]
        if not len(w):
            w = fp[-1:]
        cls = w.max(0)
        rows[k] = [cls[idx[g]].max() if idx[g] else 0.0 for g in GROUP_ORDER]
    return rows


def stage_sound_loudness(src, wd, info):
    s_csv, l_csv = wd / "sound.csv", wd / "loudness.csv"
    if s_csv.exists() and l_csv.exists():
        return
    s_rows, l_rows = [], []
    if info["audio_streams"]:
        sed, labels = sound.model()
        idx = {g: [labels.index(l) for l in sound.GROUPS[g] if l in labels] for g in GROUP_ORDER}
        sr, lhop = sound.SR, int(LOUD_STEP * sound.SR)
        t0 = 0.0
        for seg in _stream_pcm(src, sr, PANN_CHUNK_S):
            # loudness: RMS dBFS per 0.1 s
            nl = math.ceil(len(seg) / lhop)
            pad = np.pad(seg, (0, nl * lhop - len(seg)))
            rms = np.sqrt((pad.reshape(nl, lhop).astype(np.float64) ** 2).mean(1))
            if nl * lhop > len(seg):  # correct the mean of a partial last window
                tail = len(seg) - (nl - 1) * lhop
                rms[-1] = np.sqrt((seg[-tail:].astype(np.float64) ** 2).mean())
            db = np.maximum(20 * np.log10(rms + 1e-10), -100.0)
            base = int(round(t0 / LOUD_STEP))
            l_rows += [(round((base + k) * LOUD_STEP, 1), round(float(v), 1)) for k, v in enumerate(db)]
            # sound groups per 0.5 s
            if len(seg) >= int(0.1 * sr):
                win = _pann_windows(seg, sed, idx)
                sbase = int(round(t0 / SOUND_STEP))
                s_rows += [(round((sbase + k) * SOUND_STEP, 1), *[round(float(v), 2) for v in r]) for k, r in enumerate(win)]
            t0 += len(seg) / sr
            if int(t0) % 600 < PANN_CHUNK_S:
                log(f"  sound/loudness {fmt_ts(t0)}")
    write_atomic(l_csv, "t,rms_db\n" + "".join(f"{t},{v}\n" for t, v in l_rows))
    write_atomic(s_csv, "t," + ",".join(GROUP_ORDER) + "\n" + "".join(",".join(map(str, r)) + "\n" for r in s_rows))


# ---------------------------------------------------------------- transcription (ElevenLabs Scribe)
class Rejected(Exception):
    """Provider refused the file for size/length (caller should split)."""


def _post_stt(path, key, language):
    import requests
    global _stt_model
    models = [_stt_model] if _stt_model else STT_MODELS
    last = None
    for model_id in models:
        data = {"model_id": model_id, "diarize": "true", "tag_audio_events": "true", "timestamps_granularity": "word"}
        if language:
            data["language_code"] = language
        size_mb = Path(path).stat().st_size / 1e6
        timeout = (30, max(600, size_mb * 60))
        for attempt in range(5):
            try:
                with open(path, "rb") as fh:
                    r = requests.post(STT_URL, headers={"xi-api-key": key}, data=data,
                                      files={"file": (Path(path).name, fh, "audio/mpeg")}, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last = f"{type(e).__name__}"
                log(f"  scribe network error ({last}), retry {attempt + 1}")
                time.sleep(min(120, 5 * 3 ** attempt))
                continue
            if r.status_code == 200:
                _stt_model = model_id
                return model_id, r.json()
            body = r.text[:400]
            last = f"HTTP {r.status_code}: {body}"
            if r.status_code in (429, 500, 502, 503, 504):
                log(f"  scribe {last[:120]}, retry {attempt + 1}")
                time.sleep(min(120, 5 * 3 ** attempt))
                continue
            if r.status_code in (401, 403):
                raise RuntimeError(f"ElevenLabs auth/permission error {r.status_code}: {body[:200]}")
            low = body.lower()
            if r.status_code == 413 or any(s in low for s in ("too long", "too large", "file size", "duration", "exceed")):
                raise Rejected(last)
            log(f"  scribe model {model_id} not accepted ({last[:160]}); trying next")
            break  # 400/422 etc: try the next model
        else:
            raise Rejected(f"retries exhausted: {last}")
    raise RuntimeError(f"no Scribe model accepted the request; last error {last}")


def _quiet_point(loud, t_lo, t_hi):
    """Quietest 0.5 s position in [t_lo, t_hi] from loudness rows (t, db); midpoint if unknown."""
    if loud is None or not len(loud):
        return (t_lo + t_hi) / 2
    i0, i1 = np.searchsorted(loud[:, 0], [t_lo, t_hi])
    seg = loud[i0:i1, 1]
    if len(seg) < 5:
        return (t_lo + t_hi) / 2
    sm = np.convolve(seg, np.ones(5) / 5, mode="same")
    return float(loud[i0 + int(sm.argmin()), 0])


def _transcribe_range(wd, t0, t1, key, language, loud, total):
    """Transcribe [t0, t1] of audio.mp3, splitting at a quiet point when too long or rejected. Returns pieces."""
    whole = t0 <= 0 and t1 >= total - 0.01
    cache = wd / ("scribe_raw.json" if whole else f"scribe_raw_{t0:09.2f}-{t1:09.2f}.json")
    if cache.exists():
        return [read_json(cache)]
    if t1 - t0 <= STT_MAX_SINGLE_S:
        piece = wd / "audio.mp3"
        if not whole:
            piece = wd / f"_piece_{t0:.2f}.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(wd / "audio.mp3"),
                            "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(piece)], check=True)
        try:
            log(f"  scribe {fmt_ts(t0)}-{fmt_ts(t1)} uploading {piece.stat().st_size / 1e6:.1f} MB")
            model_id, resp = _post_stt(piece, key, language)
            rec = {"offset": round(t0, 3), "end": round(t1, 3), "model": model_id, "response": resp}
            write_json(cache, rec, indent=None)
            return [rec]
        except Rejected as e:
            if t1 - t0 < 2 * STT_MIN_PIECE_S:
                raise RuntimeError(f"Scribe rejected a {t1 - t0:.0f}s piece: {e}")
            log(f"  scribe rejected {fmt_ts(t0)}-{fmt_ts(t1)} ({str(e)[:120]}); splitting")
        finally:
            if not whole and piece.exists():
                piece.unlink()
    mid = (t0 + t1) / 2
    cut = _quiet_point(loud, mid - min(120, (t1 - t0) / 4), mid + min(120, (t1 - t0) / 4))
    return (_transcribe_range(wd, t0, cut, key, language, loud, total)
            + _transcribe_range(wd, cut, t1, key, language, loud, total))


def _merge_pieces(pieces, source):
    words, langs = [], []
    multi = len(pieces) > 1
    for k, rec in enumerate(pieces):
        off, resp = rec["offset"], rec["response"]
        langs.append(resp.get("language_code"))
        for w in resp.get("words", []):
            if w.get("type") == "spacing" or w.get("start") is None:
                continue
            spk = w.get("speaker_id")
            if spk is not None and multi:
                spk = f"p{k + 1}/{spk}"   # diarization ids are only consistent within one request
            s = float(w["start"]) + off
            e = float(w["end"]) + off if w.get("end") is not None else s
            txt = (w.get("text") or "").strip()
            if w.get("type") == "audio_event" and txt:
                txt = "(" + txt.strip("()[] ") + ")"   # Scribe returns "[laughter]"; contract uses "(laughter)"
            words.append({"w": txt if txt != "()" else "", "s": round(s, 3), "e": round(max(e, s), 3),
                          "speaker": spk, "type": "audio_event" if w.get("type") == "audio_event" else "word"})
    words.sort(key=lambda d: (d["s"], d["e"]))
    lang = max(set(l for l in langs if l), key=langs.count) if any(langs) else None
    raw = pieces[0]["response"] if not multi else [{"offset": p["offset"], "end": p["end"], "response": p["response"]} for p in pieces]
    return {"source": source, "language": lang, "model": pieces[0].get("model") if pieces else None,
            "words": [w for w in words if w["w"]], "raw": raw}


def stage_transcript(src, wd, info, language):
    out = wd / "transcript.json"
    if out.exists():
        return
    if not info["audio_streams"] or not (wd / "audio.mp3").exists() or not info["duration"]:
        write_json(out, {"source": str(src), "language": None, "no_audio": True, "words": [], "raw": None})
        return
    key = get_secret("ELEVENLABS_API_KEY")
    loud = _load_loudness(wd)
    pieces = _transcribe_range(wd, 0.0, float(info["duration"]), key, language, loud, float(info["duration"]))
    write_json(out, _merge_pieces(pieces, str(src)), indent=None)
    for f in wd.glob("scribe_raw_*.json"):   # piece caches are now inside transcript.json
        f.unlink()


# ---------------------------------------------------------------- timeline
def _load_loudness(wd):
    p = wd / "loudness.csv"
    if not p.exists() or p.stat().st_size < 12:
        return None
    a = np.loadtxt(p, delimiter=",", skiprows=1, ndmin=2)
    return a if len(a) else None


def _load_sound(wd):
    p = wd / "sound.csv"
    if not p.exists():
        return None
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    return {g: np.array([float(r[g]) for r in rows]) for g in GROUP_ORDER}


def _utterances(words):
    utts, cur = [], None
    for w in words:
        is_word = w["type"] == "word"
        new = cur is None or (w["s"] - cur["e"] > PAUSE_SPLIT)
        if cur is not None and not new and is_word:
            dur = w["s"] - cur["s"]
            if cur["spk"] is not None and w["speaker"] is not None and w["speaker"] != cur["spk"]:
                new = True
            elif dur > UTT_HARD_MAX or (dur > UTT_SOFT_MAX and cur["toks"] and cur["toks"][-1][-1:] in ".?!"):
                new = True
        if new:
            cur = {"s": w["s"], "e": w["e"], "spk": w["speaker"] if is_word else None, "toks": [], "ev_spk": w["speaker"]}
            utts.append(cur)
        if is_word and cur["spk"] is None:
            cur["spk"] = w["speaker"]
        t = w["w"]
        if not is_word and not t.startswith("("):
            t = f"({t})"
        cur["toks"].append(t)
        cur["e"] = max(cur["e"], w["e"])
    return utts


class Tagger:
    def __init__(self, snd, loud, words):
        self.snd, self.loud = snd, loud
        self.med = None
        if loud is not None:
            db, t = loud[:, 1], loud[:, 0]
            mask = np.zeros(len(t), bool)
            spoken = [(w["s"], w["e"]) for w in words if w["type"] == "word"]
            if spoken:
                st = np.array(spoken)
                i0 = np.searchsorted(t, st[:, 0]); i1 = np.searchsorted(t, st[:, 1])
                for a, b in zip(i0, i1):
                    mask[a:max(b, a + 1)] = True
            elif snd is not None:
                sp = snd["speech"] > sound.THRESH["speech"]
                mask = np.repeat(sp, int(SOUND_STEP / LOUD_STEP))[:len(t)]
                mask = np.pad(mask, (0, len(t) - len(mask)))
            if mask.sum() < 10:
                mask = db > -60
            if mask.sum():
                self.med = float(np.median(db[mask]))
            self.sm = np.convolve(db, np.ones(3) / 3, mode="same")  # 0.3 s smoothed peak

    def tags(self, s, e):
        out = []
        if self.med is not None:
            i0 = int(s / LOUD_STEP); i1 = max(int(math.ceil(e / LOUD_STEP)), i0 + 1)
            seg = self.sm[i0:i1]
            if len(seg):
                d = float(seg.max()) - self.med
                if d > LOUD_DB:
                    out.append(f"{{LOUD +{d:.0f}dB}}")
        if self.snd is not None:
            k0 = int(s / SOUND_STEP); k1 = max(int(math.ceil(e / SOUND_STEP)), k0 + 1)
            for g, name in TAGS:
                seg = self.snd[g][k0:k1]
                if len(seg) and seg.max() > sound.THRESH[g]:
                    out.append(f"{{{name}}}")
        return out

    def gap_events(self, g0, g1):
        """Tagged runs of 0.5 s windows lying fully inside a speech gap: [(s, e, tags)]."""
        n = len(self.snd["speech"]) if self.snd is not None else (int(len(self.loud) * LOUD_STEP / SOUND_STEP) if self.loud is not None else 0)
        k0, k1 = int(math.ceil(g0 / SOUND_STEP)), min(int(g1 / SOUND_STEP), n)
        runs, cur = [], None
        for k in range(k0, k1):
            tg = self.tags(k * SOUND_STEP, (k + 1) * SOUND_STEP)
            if tg:
                if cur and k * SOUND_STEP - cur[1] <= 1.0:
                    cur[1] = (k + 1) * SOUND_STEP
                    cur[2].update(tg)
                else:
                    cur = [k * SOUND_STEP, (k + 1) * SOUND_STEP, set(tg)]
                    runs.append(cur)
        order = lambda t: (0 if t.startswith("{LOUD") else 1 + [n for _, n in TAGS].index(t[1:-1]))
        out = []
        for a, b, tg in runs:
            louds = [t for t in tg if t.startswith("{LOUD")]
            tg = {t for t in tg if not t.startswith("{LOUD")} | ({max(louds, key=lambda x: int(x[7:-3]))} if louds else set())
            out.append((a, b, sorted(tg, key=order)))
        return out


def _rng(s, e):
    return f"[{fmt_ts(math.floor(s * 10) / 10)}-{fmt_ts(math.ceil(e * 10) / 10)}]"


def build_lines(tr, snd, loud, duration):
    """All timeline lines as (time, text), in time order."""
    words = tr.get("words", [])
    utts = _utterances(words)
    tag = Tagger(snd, loud, words)
    spk_names, lines = {}, []
    for u in utts:
        k = u["spk"] if u["spk"] is not None else u["ev_spk"]
        if k is not None and k not in spk_names:
            spk_names[k] = f"S{len(spk_names) + 1}"

    def gap(g0, g1):
        if g1 - g0 > SILENCE_LINE:
            lines.append((g0, f"-- silence {g1 - g0:.1f}s --"))
        if tag.snd is not None or tag.loud is not None:
            for a, b, tg in tag.gap_events(g0, g1):
                lines.append((a, f"{_rng(a, b)} (no speech)  {' '.join(tg)}"))

    prev = 0.0
    for u in utts:
        gap(prev, u["s"])
        who = spk_names.get(u["spk"] if u["spk"] is not None else u["ev_spk"], "S?")
        tg = tag.tags(u["s"], u["e"])
        lines.append((u["s"], f"{_rng(u['s'], u['e'])} {who}: {' '.join(u['toks'])}" + (f"  {' '.join(tg)}" if tg else "")))
        prev = max(prev, u["e"])
    if duration:
        gap(prev, duration)
    lines.sort(key=lambda x: x[0])
    return lines, tag.med, len(spk_names)


def _header(src, k, n, cs, ce, duration, med, nspk, lang):
    return (f"# Timeline {k + 1}/{n}: {Path(src).name}\n"
            f"chunk [{fmt_ts(cs)}-{fmt_ts(ce)}] of {fmt_ts(duration or 0)} total; times are source-file MM:SS.s"
            f" (minutes continue past 59); neighbouring chunks overlap {OVERLAP_S:.0f}s\n"
            f"language {lang or '?'}; {nspk} speaker label(s) S1..; median speech loudness "
            f"{'%.1f dBFS' % med if med is not None else 'n/a'}\n"
            f"line: [start-end] speaker: words (audio events heard by the transcriber)  {{signal tags}}\n"
            f"tags: {{LOUD +NdB}} peak N dB above median speech; {{LAUGH}} laughter; {{SHOUT}} shout/yell/scream; "
            f"{{CROWD}} crowd/cheer/applause/chatter; {{MUSIC}} music. '-- silence Ns --' = no speech for N s; "
            f"'(no speech)' lines = tagged sound with no words.\n\n")


def chunk_lines(lines, src, duration, med, nspk, lang):
    """Split lines into ~10 min chunks with 60 s overlap, shrinking a chunk until it fits MAX_BYTES."""
    duration = duration or (lines[-1][0] + 1 if lines else 0)
    times = np.array([t for t, _ in lines]) if lines else np.zeros(0)
    sizes = np.array([len(l.encode("utf-8")) + 1 for _, l in lines]) if lines else np.zeros(0)
    csum = np.concatenate([[0], np.cumsum(sizes)])
    hdr_len = len(_header(src, 99, 99, 0, duration, duration, med, nspk, lang).encode("utf-8"))
    spans, cs = [], 0.0
    while True:
        d = CHUNK_S
        while True:
            ce = cs + d
            if ce >= duration - OVERLAP_S * 1.5:   # avoid a tiny tail chunk
                ce = max(duration, cs + 1e-3)
            i0, i1 = np.searchsorted(times, [cs, ce])
            if hdr_len + csum[i1] - csum[i0] <= MAX_BYTES or d <= MIN_CHUNK_S:
                break
            d = max(MIN_CHUNK_S, d * 0.8)
        spans.append((cs, ce))
        if ce >= duration:
            break
        cs = ce - OVERLAP_S
    out = []
    for k, (cs, ce) in enumerate(spans):
        i0, i1 = np.searchsorted(times, [cs, ce])
        body = "".join(l + "\n" for _, l in lines[i0:i1]) or "-- no speech or tagged sound in this range --\n"
        out.append(_header(src, k, len(spans), cs, ce, duration, med, nspk, lang) + body)
    return out


def stage_timeline(src, wd, info, force=False):
    tp = wd / "transcript.json"
    if not tp.exists():
        return 0
    existing = sorted(wd.glob("timeline_*.md"))
    deps = [wd / f for f in ("transcript.json", "sound.csv", "loudness.csv") if (wd / f).exists()]
    if existing and not force and min(f.stat().st_mtime for f in existing) >= max(f.stat().st_mtime for f in deps):
        return len(existing)
    tr = read_json(tp)
    snd, loud = _load_sound(wd), _load_loudness(wd)
    med, nspk = None, 0
    if tr.get("no_audio"):
        lines = [(0.0, "-- no audio stream in this file --")]
    else:
        lines, med, nspk = build_lines(tr, snd, loud, info.get("duration"))
    chunks = chunk_lines(lines, src, info.get("duration"), med, nspk, tr.get("language"))
    for f in existing:
        f.unlink()
    for k, text in enumerate(chunks):
        write_atomic(wd / f"timeline_{k:03d}.md", text)
    return len(chunks)


# ---------------------------------------------------------------- driver
def ingest(src, work_root, language=None, transcribe=True, force_timeline=False):
    src = Path(src).resolve()
    wd = work_dir_for(src, work_root)
    t = time.time()
    log(f"== {src.name} -> {wd}")
    info = stage_probe(src, wd)
    stage_audio(src, wd, info)
    stage_sound_loudness(src, wd, info)
    if transcribe:
        stage_transcript(src, wd, info, language)
    n = stage_timeline(src, wd, info, force_timeline)
    log(f"   done in {time.time() - t:.1f}s: {n} timeline chunk(s)" + ("" if n else " (no transcript yet)"))
    return wd


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="media file or folder of media files")
    ap.add_argument("--work", default=str(WORK_DIR), help="work root; outputs go to <work>/<source-stem>/")
    ap.add_argument("--recursive", action="store_true", help="also take media files in subfolders")
    ap.add_argument("--no-transcribe", action="store_true", help="skip the ElevenLabs stage (no API cost)")
    ap.add_argument("--language", help="ISO language code for Scribe (default: auto-detect)")
    ap.add_argument("--force-timeline", action="store_true", help="rebuild timeline_*.md even if up to date")
    a = ap.parse_args()
    inp = Path(a.input)
    files = media_files(inp, a.recursive) if inp.is_dir() else [inp]
    if not files:
        sys.exit(f"no media files in {inp}")
    stems = [f.stem for f in files]
    dup = {s for s in stems if stems.count(s) > 1}
    if dup:
        sys.exit(f"duplicate source stems would share a work dir: {sorted(dup)}")
    failed = []
    for f in files:
        try:
            ingest(f, a.work, a.language, not a.no_transcribe, a.force_timeline)
        except Exception as e:  # keep going with the other files
            log(f"!! FAILED {f.name}: {type(e).__name__}: {e}")
            failed.append(f.name)
    log(f"ingest finished: {len(files) - len(failed)}/{len(files)} ok" + (f"; failed: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
