"""render.py - clip specs (clips.json) -> vertical mp4s + QA contact sheets.

Usage:
    python render.py <clips.json> --out <dir> [--only id,id] [--jobs 3]
                     [--work <work-dir>] [--skip-existing] [--hwdec auto|off] [--keep-tmp]

One ffmpeg invocation per clip. Each segment is its own input (-ss/-t), normalised to
exact CFR frame counts, tone-mapped if HDR, laid out (crop/fit/zoom) and concatenated
with exactly matching audio sample counts, so A/V cannot drift across jump cuts.
Title = Pillow PNG overlay; subtitles = ASS (libass); audio = loudnorm single pass.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------------------
# STYLE: every visual number lives here (the lead tunes these from the style study).
# Sizes are in output pixels for a 1080-wide frame; they are scaled for other widths.
# --------------------------------------------------------------------------------------
STYLE = {
    # title caption
    "title_font": r"C:\Windows\Fonts\arialbd.ttf",
    "emoji_font": r"C:\Windows\Fonts\seguiemj.ttf",
    "emoji_render_size": 109,         # Segoe UI Emoji is rendered at this size, then resized
    "emoji_scale": 1.05,              # emoji height relative to title font size
    "title_size": 66,                 # starting font size (px)
    "title_min_size": 44,             # shrink down to this before allowing more lines
    "title_max_lines": 3,
    "title_max_width": 0.80,          # fraction of frame width
    "title_line_spacing": 1.18,       # line height = size * this
    "title_fill": (255, 255, 255, 255),
    "title_stroke_width": 6,
    "title_stroke_fill": (0, 0, 0, 255),
    "title_shadow": None,             # e.g. {"blur": 5, "dy": 2, "strength": 1.8}: soft dark halo under the text
    "title_box": None,                # e.g. {"fill": (0, 0, 0, 150), "pad_x": 28, "pad_y": 18, "radius": 22}
    "title_safe_top": 0.08,           # keep the title block inside these vertical margins
    "title_safe_bottom": 0.80,

    # burned subtitles (ASS / libass)
    "sub_font": r"C:\Windows\Fonts\arialbd.ttf",
    "sub_size": 70,
    "sub_fill": (255, 255, 255),
    "sub_highlight": (255, 230, 0),   # colour of the word being spoken; None = no highlight
    "sub_outline": 5,
    "sub_outline_color": (0, 0, 0),
    "sub_shadow": 0,
    "sub_y": 0.64,                    # centre of the subtitle line (fraction of height)
    "sub_uppercase": False,
    "sub_max_words": 3,
    "sub_max_chars": 18,
    "sub_gap_break": 0.45,            # start a new line after a pause longer than this (s)
    "sub_title_margin": 30,           # px gap kept between subtitles and title block

    # fit layout background
    "fit_bg_blur": 14,                # boxblur radius at 1/4 resolution
    "fit_bg_brightness": -0.12,       # eq brightness (-1..1)
    "fit_bg_saturation": 1.0,
    "fit_fg_y": 0.5,                  # vertical centre of the foreground frame

    # audio
    "audio_fade_ms": 9,               # fade in/out at every jump cut
    "loudnorm_tp": -1.5,
    "loudnorm_lra": 11,

    # QA sheet
    "qa_thumb_w": 300,
    "qa_cols": 6,
}

ENCODE = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-profile:v", "high",
              "-rc", "vbr", "-b:v", "10M", "-maxrate", "15M", "-bufsize", "20M",
              "-spatial_aq", "1", "-temporal_aq", "1", "-rc-lookahead", "20", "-bf", "2", "-pix_fmt", "yuv420p"],
    # Windows Media Foundation H.264 encoder. On NVIDIA this is NVENC through the driver's
    # own MFT, so it works even when ffmpeg's h264_nvenc needs a newer driver (this machine:
    # driver 565.90, ffmpeg 8.1 nvenc wants >= 570). profile 100 = High.
    "mf": ["-c:v", "h264_mf", "-hw_encoding", "1", "-profile:v", "100", "-rate_control", "pc_vbr",
           "-b:v", "10M", "-maxrate", "15M", "-scenario", "archive", "-pix_fmt", "nv12"],
    "x264": ["-c:v", "libx264", "-preset", "faster", "-profile:v", "high", "-crf", "19",
             "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p"],
    "audio": ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"],
}
VRAM_BUDGET_MB = 4200          # NVDEC surface budget shared by all parallel jobs
HDR_TRC = {"arib-std-b67", "smpte2084"}
HW_CODECS = {"h264", "hevc", "av1", "vp9"}
AUDIO_SR = 48000

_print_lock = threading.Lock()
_enc_lock = threading.Lock()
_encoders: list | None = None


def _try_encoder(name) -> tuple[bool, str]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=s=1080x1920:r=30:d=0.5"] + ENCODE[name] +
                       ["-f", "mp4", "-y", os.devnull if os.name != "nt" else "NUL"],
                       capture_output=True, text=True, timeout=90)
    return p.returncode == 0, " ".join(p.stderr.split())[:200]


def video_encoders() -> list:
    """Working encoders in preference order (probed once): nvenc, mf (hardware), x264."""
    global _encoders
    with _enc_lock:
        if _encoders is None:
            _encoders = []
            for name in ("nvenc", "mf"):
                try:
                    ok, err = _try_encoder(name)
                except Exception as e:
                    ok, err = False, str(e)
                if ok:
                    _encoders.append(name)
                else:
                    log(f"encoder {name} unavailable: {err}")
            _encoders.append("x264")
            log(f"video encoders in order of use: {_encoders}")
    return _encoders


def log(*a):
    with _print_lock:
        print(*a, flush=True)


# --------------------------------------------------------------------------------------
# probing (own helper; common.py belongs to the ingest agent)
# --------------------------------------------------------------------------------------
_probe_cache: dict[str, dict] = {}
_probe_lock = threading.Lock()


def _ratio(s, default=1.0):
    try:
        a, b = str(s).split(":") if ":" in str(s) else str(s).split("/")
        a, b = float(a), float(b)
        return a / b if a > 0 and b > 0 else default
    except Exception:
        return default


def probe(path: str) -> dict:
    with _probe_lock:
        if path in _probe_cache:
            return _probe_cache[path]
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {out.stderr.strip()[:300]}")
    j = json.loads(out.stdout)
    vs = [s for s in j.get("streams", []) if s.get("codec_type") == "video"
          and not (s.get("disposition", {}) or {}).get("attached_pic")]
    if not vs:
        raise RuntimeError(f"no video stream in {path}")
    v = vs[0]
    aud = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    rot = 0
    dovi = False
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(round(float(sd["rotation"])))
            except Exception:
                pass
        if "DOVI" in str(sd.get("side_data_type", "")) or "Dolby" in str(sd.get("side_data_type", "")):
            dovi = True
    if not rot and "rotate" in (v.get("tags") or {}):
        rot = -int(v["tags"]["rotate"])
    w, h = int(v["width"]), int(v["height"])
    sar = _ratio(v.get("sample_aspect_ratio", "1:1"))
    if abs(rot) % 180 == 90:
        w, h = h, w
        sar = 1.0 / sar
    dur = None
    for src in (j.get("format", {}).get("duration"), v.get("duration")):
        try:
            dur = float(src)
            break
        except Exception:
            pass
    trc = v.get("color_transfer", "") or ""
    pix = v.get("pix_fmt", "") or ""
    info = {
        "path": path, "duration": dur or 0.0, "width": w, "height": h, "sar": sar,
        "rotation": rot, "vcodec": v.get("codec_name", ""), "pix_fmt": pix,
        "color_transfer": trc, "color_primaries": v.get("color_primaries", ""),
        "dovi": dovi, "is_hdr": trc in HDR_TRC or dovi,
        "bit10": "10" in pix or "12" in pix,
        "fps": _ratio(v.get("avg_frame_rate", "0/1"), 0) or _ratio(v.get("r_frame_rate", "30/1"), 30),
        "has_audio": bool(aud),
    }
    with _probe_lock:
        _probe_cache[path] = info
    return info


# --------------------------------------------------------------------------------------
# title PNG (Pillow) - mixed text + colour emoji, balanced wrap
# --------------------------------------------------------------------------------------
def _is_emoji_cp(cp: int) -> bool:
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF
            or cp in (0x231A, 0x231B, 0x2328, 0x23CF, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D)
            or 0x23E9 <= cp <= 0x23FA or 0x2194 <= cp <= 0x21AA or 0x25AA <= cp <= 0x25FE
            or 0x2934 <= cp <= 0x2935)


def _tokenize(text: str):
    """-> list of (kind, str) with kind 'text' or 'emoji'. Without libraqm Pillow cannot
    shape ZWJ / skin-tone / flag sequences, so they degrade to their base emoji."""
    out = []
    cps = [ord(c) for c in text]
    i = 0
    buf = ""
    while i < len(cps):
        cp = cps[i]
        if 0x1F1E6 <= cp <= 0x1F1FF:            # regional indicators (flags): not in Segoe UI Emoji
            i += 1
            continue
        keycap = (i + 1 < len(cps) and cps[i + 1] in (0xFE0F, 0x20E3)
                  and (chr(cp).isdigit() or cp in (0x23, 0x2A))
                  and 0x20E3 in cps[i + 1:i + 3])
        if _is_emoji_cp(cp) or keycap:
            if buf:
                out.append(("text", buf))
                buf = ""
            base = chr(cp) + ("\ufe0f\u20e3" if keycap else "")
            i += 1
            # swallow modifiers / ZWJ continuations
            while i < len(cps):
                c = cps[i]
                if c in (0xFE0F, 0xFE0E, 0x20E3) or 0x1F3FB <= c <= 0x1F3FF or 0xE0020 <= c <= 0xE007F:
                    i += 1
                elif c == 0x200D and i + 1 < len(cps):
                    i += 2
                else:
                    break
            out.append(("emoji", base))
        elif cp in (0xFE0F, 0x200D):
            i += 1
        else:
            buf += chr(cp)
            i += 1
    if buf:
        out.append(("text", buf))
    return out


_emoji_cache: dict[tuple, Image.Image] = {}


def _emoji_img(ch: str, px: int) -> Image.Image:
    key = (ch, px)
    if key in _emoji_cache:
        return _emoji_cache[key]
    rs = STYLE["emoji_render_size"]
    f = ImageFont.truetype(STYLE["emoji_font"], rs)
    im = Image.new("RGBA", (rs * 3, rs * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((rs // 2, rs // 3), ch, font=f, embedded_color=True)
    bb = im.getbbox()
    if not bb:
        im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    else:
        im = im.crop(bb)
        sc = px / max(im.height, 1)
        im = im.resize((max(1, round(im.width * sc)), px), Image.LANCZOS)
    _emoji_cache[key] = im
    return im


class _Word:
    def __init__(self, toks):
        self.toks = toks  # list of (kind, s)


def _split_words(text: str):
    words = []
    for raw in text.split():
        words.append(_tokenize(raw))
    return [w for w in words if w]


def _measure(tokens, font, size):
    w = 0.0
    for kind, s in tokens:
        if kind == "text":
            w += font.getlength(s)
        else:
            em = round(size * STYLE["emoji_scale"])
            w += _emoji_img(s, em).width + size * 0.06
    return w


def _layout_lines(words, font, size, max_w):
    space = font.getlength(" ")
    widths = [_measure(t, font, size) for t in words]
    n = len(words)

    def line_w(a, b):
        return sum(widths[a:b]) + space * (b - a - 1)

    best = None
    for k in range(1, min(STYLE["title_max_lines"], n) + 1):
        # balanced: choose breakpoints minimising the widest line
        import itertools
        for cuts in itertools.combinations(range(1, n), k - 1):
            idx = (0,) + cuts + (n,)
            lw = [line_w(idx[i], idx[i + 1]) for i in range(k)]
            if max(lw) <= max_w:
                score = max(lw)
                if best is None or score < best[0]:
                    best = (score, idx)
        if best:
            idx = best[1]
            return [words[idx[i]:idx[i + 1]] for i in range(len(idx) - 1)], [line_w(idx[i], idx[i + 1]) for i in range(len(idx) - 1)]
        if n > 14 and k >= 2:
            break
    return None, None


def render_title_png(text: str, out_w: int, png_path: Path):
    """Returns (w, h) of the PNG (tight around the text block incl. stroke/box)."""
    k = out_w / 1080.0
    words = _split_words(text)
    if not words:
        return None
    max_w = STYLE["title_max_width"] * out_w
    size = round(STYLE["title_size"] * k)
    min_size = round(STYLE["title_min_size"] * k)
    lines = None
    while size >= min_size:
        font = ImageFont.truetype(STYLE["title_font"], size)
        lines, lws = _layout_lines(words, font, size, max_w)
        if lines:
            break
        size -= 2
    if not lines:  # too long even at min size: greedy wrap at min size, allow overflow lines
        size = min_size
        font = ImageFont.truetype(STYLE["title_font"], size)
        lines, cur, lws = [], [], []
        for w in words:
            trial = cur + [w]
            if cur and _measure([t for x in trial for t in x + [("text", " ")]], font, size) > max_w:
                lines.append(cur)
                cur = [w]
            else:
                cur = trial
        if cur:
            lines.append(cur)
        lws = [_measure([t for i, x in enumerate(l) for t in (x if i == 0 else [("text", " ")] + x)], font, size) for l in lines]
    sw = max(1, round(STYLE["title_stroke_width"] * k))
    lh = round(size * STYLE["title_line_spacing"])
    ascent, descent = font.getmetrics()
    box = STYLE.get("title_box")
    shadow = STYLE.get("title_shadow") or None
    sh_pad = round((shadow["blur"] * 3 + abs(shadow.get("dy", 0))) * k) if shadow else 0  # room for the blur
    pad_x = round((box or {}).get("pad_x", 0) * k) + sw + 4 + sh_pad
    pad_y = round((box or {}).get("pad_y", 0) * k) + sw + 4 + sh_pad
    block_w = int(max(lws)) + 2 * pad_x
    block_h = lh * (len(lines) - 1) + ascent + descent + 2 * pad_y
    im = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if box:
        d.rounded_rectangle([0, 0, block_w - 1, block_h - 1], radius=round(box.get("radius", 0) * k),
                            fill=tuple(box.get("fill", (0, 0, 0, 150))))
    em_px = round(size * STYLE["emoji_scale"])
    space = font.getlength(" ")
    for li, (line, lw) in enumerate(zip(lines, lws)):
        x = (block_w - lw) / 2
        base_y = pad_y + li * lh + ascent  # baseline
        for wi, word in enumerate(line):
            if wi:
                x += space
            for kind, s in word:
                if kind == "text":
                    d.text((x, base_y), s, font=font, anchor="ls", fill=STYLE["title_fill"],
                           stroke_width=sw, stroke_fill=STYLE["title_stroke_fill"])
                    x += font.getlength(s)
                else:
                    e = _emoji_img(s, em_px)
                    # centre emoji on the cap-height band
                    cy = base_y - ascent * 0.40
                    im.alpha_composite(e, (round(x + size * 0.03), round(cy - e.height / 2)))
                    x += e.width + size * 0.06
    if shadow and not box:
        from PIL import ImageFilter
        st = float(shadow.get("strength", 1.8))
        halo = im.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, round(shadow["blur"] * k))))
        halo = halo.point(lambda v: min(255, int(v * st)))
        under = Image.new("RGBA", im.size, (0, 0, 0, 0))
        black = Image.new("RGBA", im.size, (0, 0, 0, 255)); black.putalpha(halo)
        under.alpha_composite(black, (0, round(shadow.get("dy", 0) * k)))
        under.alpha_composite(im)
        im = under
    im.save(png_path)
    return im.size


# --------------------------------------------------------------------------------------
# subtitles (ASS)
# --------------------------------------------------------------------------------------
def _ass_color(rgb, alpha=0):
    r, g, b = rgb[:3]
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def build_ass(words_out, out_w, out_h, sub_y_px, font_family, ass_path: Path):
    """words_out: [(text, start, end, seg_index)] already on the output timeline."""
    k = out_w / 1080.0
    lines, cur = [], []
    for wd in words_out:
        if cur:
            prev = cur[-1]
            chars = sum(len(x[0]) + 1 for x in cur) + len(wd[0])
            if (len(cur) >= STYLE["sub_max_words"] or chars > STYLE["sub_max_chars"]
                    or wd[1] - prev[2] > STYLE["sub_gap_break"] or wd[3] != prev[3]
                    or prev[0].rstrip()[-1:] in ".?!,"):
                lines.append(cur)
                cur = []
        cur.append(wd)
    if cur:
        lines.append(cur)
    fill = _ass_color(STYLE["sub_fill"])
    hl = STYLE.get("sub_highlight")
    hlc = _ass_color(hl) if hl else None
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_family},{round(STYLE['sub_size'] * k)},{fill},{fill},{_ass_color(STYLE['sub_outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{STYLE['sub_outline'] * k:.1f},{STYLE['sub_shadow'] * k:.1f},5,{round(60 * k)},{round(60 * k)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def clean(s):
        s = s.replace("\\", "/").replace("{", "(").replace("}", ")")
        return s.upper() if STYLE["sub_uppercase"] else s

    ev = []
    pos = f"{{\\an5\\pos({out_w // 2},{int(sub_y_px)})}}"
    for li, ln in enumerate(lines):
        start = ln[0][1]
        end = max(ln[-1][2] + 0.25, start + 0.4)
        if li + 1 < len(lines):  # never overlap the next line
            end = min(end, lines[li + 1][0][1])
        texts = [clean(w[0]) for w in ln]
        if not hlc:
            ev.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,{pos}{' '.join(texts)}")
            continue
        for wi, w in enumerate(ln):
            ws = start if wi == 0 else w[1]
            we = ln[wi + 1][1] if wi + 1 < len(ln) else end
            if we <= ws:
                continue
            parts = [(f"{{\\c{hlc}}}{t}{{\\c{fill}}}" if j == wi else t) for j, t in enumerate(texts)]
            ev.append(f"Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Sub,,0,0,0,,{pos}{' '.join(parts)}")
    ass_path.write_text(hdr + "\n".join(ev) + "\n", encoding="utf-8")
    return len(lines)


def remap_words(transcript: dict, segs, fps):
    """Map source-time words into output time. segs: list of dicts with s, n (frames), o (out offset)."""
    out = []
    for w in transcript.get("words", []):
        if w.get("type", "word") != "word":
            continue
        txt = str(w.get("w", "")).strip()
        if not txt:
            continue
        s, e = float(w["s"]), float(w["e"])
        mid = (s + e) / 2
        for i, sg in enumerate(segs):
            a = sg["s"]
            b = a + sg["n"] / fps
            if a <= mid < b:
                os_ = sg["o"] + max(s, a) - a
                oe = sg["o"] + min(e, b) - a
                out.append((txt, os_, max(oe, os_ + 0.05), i))
                break
    out.sort(key=lambda x: x[1])
    return out


# --------------------------------------------------------------------------------------
# filtergraph
# --------------------------------------------------------------------------------------
def _even(x):
    return max(2, int(round(x / 2.0)) * 2)


def _geom(info, layout, crop_x, crop_y, zoom, OW, OH, fg_aspect=None):
    """Crop rectangle (in post-rotation coded pixels) + scaled size for stage A."""
    W, H, sar = info["width"], info["height"], info["sar"]
    Wd = W * sar
    zoom = max(1.0, float(zoom or 1.0))
    if layout == "crop":
        A = OW / OH
        if Wd / H > A:
            ch, cw = H, H * A
        else:
            cw, ch = Wd, Wd / A
        out_w, out_h = OW, OH
    elif fg_aspect:  # fit, but the foreground is first cropped to this aspect (w/h), e.g. 1.0 = square picture
        A = float(fg_aspect)
        if Wd / H > A:
            ch, cw = H, H * A
        else:
            cw, ch = Wd, Wd / A
        sc = min(OW / cw, OH / ch)
        out_w, out_h = _even(cw * sc), _even(ch * sc)
    else:
        cw, ch = Wd, H
        sc = min(OW / Wd, OH / H)
        out_w, out_h = _even(Wd * sc), _even(H * sc)
    cw, ch = cw / zoom, ch / zoom
    cx = min(max(crop_x * Wd - cw / 2, 0), Wd - cw)
    cy = min(max(crop_y * H - ch / 2, 0), H - ch)
    # back to coded pixels
    rect = (int(round(cw / sar)), int(round(ch)), int(round(cx / sar)), int(round(cy)))
    rect = (min(rect[0], W), min(rect[1], H), max(0, rect[2]), max(0, rect[3]))
    return rect, (out_w, out_h)


def _stage_a(info, rect, size, tonemap):
    cw, ch, cx, cy = rect
    ow, oh = size
    full = (cw, ch, cx, cy) == (info["width"], info["height"], 0, 0)
    if info["is_hdr"] and tonemap == "placebo":
        return (f"libplacebo=crop_x={cx}:crop_y={cy}:crop_w={cw}:crop_h={ch}:w={ow}:h={oh}"
                f":format=yuv420p:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
                f":tonemapping=bt.2390:gamut_mode=perceptual:peak_detect=1:reset_sar=1:downscaler=ewa_lanczos")
    chain = [] if full else [f"crop={cw}:{ch}:{cx}:{cy}"]
    if info["is_hdr"]:  # CPU fallback
        chain += [f"scale={ow}:{oh}:flags=lanczos", "format=yuv420p10le",
                  "zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
                  "tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p"]
    else:
        chain += [f"scale={ow}:{oh}:flags=lanczos:in_color_matrix=auto:out_color_matrix=bt709:out_range=tv",
                  "format=yuv420p"]
    chain.append("setsar=1")
    return ",".join(chain)


def clip_speed(clip) -> float:
    """Playback speed factor of a clip spec ("speed": 1.7). 1.0 when absent or out of range."""
    try:
        sp = float(clip.get("speed") or 1.0)
    except (TypeError, ValueError):
        sp = 1.0
    return sp if 0.25 <= sp <= 4.0 else 1.0


def _audio_speed(clip, sp: float) -> str:
    """Audio filters for a speed change, with a trailing comma. "speed_pitch": "up" (default) resamples, so the voice
    rises with the speed the way in-app speed-ups sound; "keep" time-stretches and holds the pitch."""
    if sp == 1.0:
        return ""
    if str(clip.get("speed_pitch", "up")) == "keep":
        parts, r = [], sp
        while r > 2.0:
            parts.append("atempo=2.0"); r /= 2.0
        while r < 0.5:
            parts.append("atempo=0.5"); r /= 0.5
        parts.append(f"atempo={r:.4f}")
        return ",".join(parts) + ","
    return f"asetrate={int(round(AUDIO_SR * sp))},aresample={AUDIO_SR},"


def build_graph(clip, segs, info, OW, OH, fps, tonemap, title_png, title_xy, title_win, ass_name):
    g = []
    labels = []
    fade = STYLE["audio_fade_ms"] / 1000.0
    k = OW / 1080.0
    for i, sg in enumerate(segs):
        n = sg["n"]
        nsamp = n * AUDIO_SR // fps if (n * AUDIO_SR) % fps == 0 else int(round(n * AUDIO_SR / fps))
        d = nsamp / AUDIO_SR
        rect, size = _geom(info, sg["layout"], sg["crop_x"], sg["crop_y"], sg["zoom"], OW, OH, sg.get("fg_aspect"))
        a = _stage_a(info, rect, size, tonemap)
        v = (f"[{i}:v:0]fps={fps}:start_time=0:round=near,{a},"
             f"tpad=stop_mode=clone:stop=-1,trim=end_frame={n},setpts=N/({fps}*TB)")
        if sg["layout"] == "fit":
            bw, bh = _even(OW / 4), _even(OH / 4)
            fy = f"(H-h)*{STYLE['fit_fg_y'] / 0.5:.4f}/2" if STYLE["fit_fg_y"] != 0.5 else "(H-h)/2"
            v += (f",split=2[f{i}][b{i}];[b{i}]scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                  f"crop={bw}:{bh},boxblur={max(1, round(STYLE['fit_bg_blur']))}:2,"
                  f"eq=brightness={STYLE['fit_bg_brightness']}:saturation={STYLE['fit_bg_saturation']},"
                  f"scale={OW}:{OH}:flags=bilinear,format=yuv420p[bg{i}];"
                  f"[bg{i}][f{i}]overlay=x=(W-w)/2:y={fy}:format=yuv420,setsar=1")
        g.append(v + f"[v{i}]")
        if info["has_audio"]:
            src = f"[{i}:a:0]aresample={AUDIO_SR},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,"
        else:
            src = f"anullsrc=r={AUDIO_SR}:cl=stereo,"
        g.append(src + f"atrim=end_sample={nsamp},asetpts=PTS-STARTPTS,"
                 f"afade=t=in:st=0:d={fade:.4f},afade=t=out:st={max(0.0, d - fade):.5f}:d={fade:.4f}[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    g.append("".join(labels) + f"concat=n={len(segs)}:v=1:a=1[vc][ac]")
    cur = "vc"
    if title_png:
        ti = len(segs)  # title image is the input after the segments
        s, e = title_win
        en = f":enable='between(t,{s:.3f},{e:.3f})'"
        g.append(f"[{cur}][{ti}:v]overlay=x={title_xy[0]}:y={title_xy[1]}:format=yuv420{en}[vt]")
        cur = "vt"
    post = []
    if ass_name:
        post.append(f"ass={ass_name}:fontsdir=fonts")
    post += ["format=yuv420p", "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"]
    sp = clip_speed(clip)
    if sp != 1.0:  # speed goes last, so the title window, subtitles and cut points all scale with it
        post += [f"setpts=PTS/{sp:.4f}", f"fps={fps}"]
    g.append(f"[{cur}]" + ",".join(post) + "[vout]")
    g.append(f"[ac]{_audio_speed(clip, sp)}loudnorm=I={float(clip.get('loudnorm', -14))}:TP={STYLE['loudnorm_tp']}:LRA={STYLE['loudnorm_lra']},"
             f"aresample={AUDIO_SR},aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
    return ";\n".join(g)


# --------------------------------------------------------------------------------------
# per clip
# --------------------------------------------------------------------------------------
def normalise_segments(clip, info, fps):
    dur = info["duration"]
    base_layout = clip.get("layout", "crop")
    zooms = clip.get("zoom") or []
    segs, o = [], 0
    for i, sg in enumerate(clip["segments"]):
        s, e = float(sg[0]), float(sg[1])
        extra = sg[2] if len(sg) > 2 and isinstance(sg[2], dict) else {}
        if dur:
            s, e = max(0.0, s), min(e, dur)
        if e - s < 1.0 / fps:
            log(f"  [{clip['id']}] segment {i} [{sg[0]}, {sg[1]}] empty after clamping to source, skipped")
            continue
        n = max(1, int(round((e - s) * fps)))
        z = extra.get("zoom", zooms[i] if i < len(zooms) and zooms[i] else 1.0)
        segs.append({"s": s, "e": e, "n": n, "o": o / fps,
                     "layout": extra.get("layout", base_layout),
                     "crop_x": float(extra.get("crop_x", clip.get("crop_x", 0.5) if clip.get("crop_x") is not None else 0.5)),
                     "crop_y": float(extra.get("crop_y", clip.get("crop_y", 0.5) if clip.get("crop_y") is not None else 0.5)),
                     "zoom": float(z or 1.0),
                     "fg_aspect": extra.get("fg_aspect", clip.get("fg_aspect"))})
        o += n
    return segs, o


def _decoder_mb(info):
    return info["width"] * info["height"] * 1.5 * (2 if info["bit10"] else 1) * 22 / 1e6 + 80


def run_ffmpeg(cmd, cwd, logf, timeout):
    with open(logf, "a", encoding="utf-8", errors="replace") as lf:
        lf.write("\n\n$ " + subprocess.list2cmdline(cmd) + "\n")
        lf.flush()
        try:  # subprocess.run kills the child when the timeout expires
            p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=lf, timeout=timeout)
        except subprocess.TimeoutExpired:
            lf.write(f"\n!! killed after {timeout:.0f}s watchdog timeout\n")
            return -999
    return p.returncode


def verify_output(path, expect_dur):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=codec_type,codec_name,profile,pix_fmt,color_transfer:format=duration",
                              "-of", "json", str(path)], capture_output=True, text=True)
        j = json.loads(out.stdout)
        types = {s["codec_type"] for s in j.get("streams", [])}
        d = float(j["format"]["duration"])
        ok = {"video", "audio"} <= types and abs(d - expect_dur) < 0.25
        return ok, f"streams={sorted(types)} dur={d:.3f} expected={expect_dur:.3f}"
    except Exception as e:
        return False, f"verify error {e}"


def render_clip(clip, cfg, args, work_dir, n_jobs):
    cid = clip["id"]
    OW, OH, fps = int(cfg.get("width", 1080)), int(cfg.get("height", 1920)), int(round(cfg.get("fps", 30)))
    out_dir = Path(args.out).resolve()
    final = out_dir / f"{cid}.mp4"
    tmp = out_dir / "_tmp" / cid
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    logf = tmp / "ffmpeg.log"
    t0 = time.time()
    info = probe(clip["source"])
    segs, nframes = normalise_segments(clip, info, fps)
    if not segs:
        raise RuntimeError("no usable segments")
    total = nframes / fps          # duration at source speed (title and subtitle timing live here)
    sp = clip_speed(clip)
    out_total = total / sp         # duration of the rendered file

    # title
    title = clip.get("title")
    title_png = None
    title_xy = (0, 0)
    title_win = (0, total)
    title_box = None
    if title and str(title.get("text", "")).strip():
        title_png = tmp / "title.png"
        tw, th = render_title_png(str(title["text"]), OW, title_png)
        cy = float(title.get("y", 0.72)) * OH
        top = cy - th / 2
        top = min(max(top, STYLE["title_safe_top"] * OH), STYLE["title_safe_bottom"] * OH - th)
        title_xy = ((OW - tw) // 2, int(round(max(0, top))))
        ts = float(title.get("start") or 0)
        te = title.get("end")
        te = total + 1 if te is None else float(te)
        title_win = (ts, te)
        title_box = (title_xy[1], title_xy[1] + th, ts, te)

    # subtitles
    ass_name = None
    if clip.get("subtitles"):
        tpath = Path(work_dir) / Path(clip["source"]).stem / "transcript.json" if work_dir else None
        if tpath and tpath.exists():
            tr = json.loads(tpath.read_text(encoding="utf-8"))
            words = remap_words(tr, segs, fps)
            if words:
                (tmp / "fonts").mkdir(exist_ok=True)
                shutil.copy(STYLE["sub_font"], tmp / "fonts" / Path(STYLE["sub_font"]).name)
                fam = ImageFont.truetype(STYLE["sub_font"], 20).getname()[0]
                sub_y = STYLE["sub_y"] * OH
                line_h = STYLE["sub_size"] * OW / 1080 * 1.3
                if title_box:
                    t_top, t_bot = title_box[0], title_box[1]
                    m = STYLE["sub_title_margin"] * OW / 1080
                    if sub_y + line_h / 2 + m > t_top and sub_y - line_h / 2 - m < t_bot:
                        above = t_top - m - line_h / 2
                        sub_y = above if above > OH * 0.15 else t_bot + m + line_h / 2
                build_ass(words, OW, OH, sub_y, fam, tmp / "subs.ass")
                ass_name = "subs.ass"
            else:
                log(f"  [{cid}] subtitles requested but no transcript words fall inside the segments")
        else:
            log(f"  [{cid}] subtitles requested but transcript not found: {tpath}")

    # attempts: fastest first, then safer fallbacks
    want_hw = args.hwdec != "off" and info["vcodec"] in HW_CODECS and "422" not in info["pix_fmt"] \
        and "444" not in info["pix_fmt"]
    budget = VRAM_BUDGET_MB / max(1, n_jobs)
    n_hw = min(len(segs), int(budget // _decoder_mb(info))) if want_hw else 0
    encs = video_encoders()
    enc = encs[0]
    attempts = []
    if n_hw:
        attempts.append(dict(n_hw=n_hw, enc=enc, tm="placebo"))
    attempts.append(dict(n_hw=0, enc=enc, tm="placebo"))
    if info["is_hdr"]:
        attempts.append(dict(n_hw=0, enc=enc, tm="zscale"))
    if enc != "x264":
        attempts.append(dict(n_hw=0, enc="x264", tm="zscale"))
    # watchdog: a hung ffmpeg must not stall the batch (generous: busy CPU, parallel jobs)
    big = info["width"] * info["height"] > 2.5e6
    timeout = 300 + total * (15 if big else 8) * max(1, n_jobs)

    part = tmp / "out.mp4"
    last = ""
    for at in attempts:
        graph = build_graph(clip, segs, info, OW, OH, fps, at["tm"], title_png, title_xy, title_win, ass_name)
        (tmp / "graph.txt").write_text(graph, encoding="utf-8")
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning"]
        if info["is_hdr"] and at["tm"] == "placebo":
            cmd += ["-init_hw_device", "vulkan"]
        for i, sg in enumerate(segs):
            if i < at["n_hw"]:
                cmd += ["-hwaccel", "cuda"]
            cmd += ["-ss", f"{sg['s']:.6f}", "-t", f"{sg['n'] / fps + 0.5:.6f}", "-i", str(Path(clip["source"]).resolve())]
        if title_png:
            cmd += ["-i", str(title_png.resolve())]
        cmd += ["-/filter_complex", "graph.txt", "-map", "[vout]", "-map", "[aout]",
                "-r", str(fps), "-fps_mode", "cfr"]
        cmd += ENCODE[at["enc"]] + ["-g", str(fps * 2),
                                    "-colorspace", "bt709", "-color_primaries", "bt709",
                                    "-color_trc", "bt709", "-color_range", "tv"]
        cmd += ENCODE["audio"] + ["-map_metadata", "-1", "-map_chapters", "-1",
                                  "-movflags", "+faststart", str(part.resolve())]
        rc = run_ffmpeg(cmd, str(tmp), logf, timeout)
        if rc == 0:
            ok, msg = verify_output(part, out_total)
            if ok:
                break
            last = f"verify failed ({msg})"
        else:
            last = f"ffmpeg exit {rc}"
        log(f"  [{cid}] attempt {at} failed: {last}; see {logf}")
    else:
        raise RuntimeError(f"all render attempts failed: {last}; log {logf}")

    os.replace(part, final)
    wall = time.time() - t0
    qa = None
    try:
        qa = qa_sheet(clip, segs, out_total, fps, final, out_dir / "qa" / f"{cid}.jpg", info, at, sp)
    except Exception as e:
        log(f"  [{cid}] QA sheet failed: {e}")
    if not args.keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"id": cid, "dur": out_total, "wall": wall, "segments": len(segs), "attempt": at, "qa": str(qa)}


# --------------------------------------------------------------------------------------
# QA contact sheet
# --------------------------------------------------------------------------------------
def _font(size, bold=True):
    for p in ((r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
              r"C:\Windows\Fonts\segoeui.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def qa_sheet(clip, segs, total, fps, mp4, out_jpg, info, attempt, speed=1.0):
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    nlast = int(round(total * fps)) - 1
    picks = {0: "start", min(int(0.5 * fps), nlast): "0.5s"}
    for i, sg in enumerate(segs):
        f = min(nlast, int(round(sg["o"] / speed * fps)))
        if f not in picks:
            picks[f] = f"seg{i + 1}"
        elif i:
            picks[f] += f"/seg{i + 1}"
    for t in range(4, int(total) - 1, 4):  # plus a frame every 4 s so framing can be checked across the clip
        picks.setdefault(int(t * fps), f"{t}s")
    picks[nlast] = picks.get(nlast, "") + ("/" if nlast in picks else "") + "last"
    frames = sorted(picks)
    tw = STYLE["qa_thumb_w"]
    try:
        _pm = probe(str(mp4)); th = int(round(tw * _pm["height"] / _pm["width"]))
    except Exception:
        th = int(round(tw * 16 / 9))
    tmpd = out_jpg.parent / f"_{clip['id']}_frames"
    shutil.rmtree(tmpd, ignore_errors=True)
    tmpd.mkdir()
    sel = "+".join(f"eq(n\\,{f})" for f in frames)
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(mp4), "-vf",
                    f"select='{sel}',scale={tw}:{th}", "-fps_mode", "passthrough", str(tmpd / "f_%03d.png")],
                   check=True)
    wav = tmpd / "wave.png"
    cols = min(STYLE["qa_cols"], len(frames))
    rows = math.ceil(len(frames) / cols)
    lab_h, head_h, wave_h, gap = 26, 74, 90, 6
    W = cols * (tw + gap) + gap
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(mp4), "-filter_complex",
                    f"[0:a]aformat=channel_layouts=mono,showwavespic=s={W - 2 * gap}x{wave_h}:colors=0x66ccff:scale=sqrt",
                    "-frames:v", "1", str(wav)], check=False)
    H = head_h + rows * (th + lab_h + gap) + wave_h + 2 * gap + 20
    sheet = Image.new("RGB", (W, H), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    title = (clip.get("title") or {}).get("text", "") if clip.get("title") else ""
    title = "".join(ch for ch in title if ord(ch) < 0x2190)
    f1, f2 = _font(22), _font(17, bold=False)
    d.text((gap, 6), f"{clip['id']}  |  {total:.2f}s  |  {len(segs)} seg  |  layout={clip.get('layout', 'crop')}"
                     f"  |  subs={'on' if clip.get('subtitles') else 'off'}" + (f"  |  speed={speed:g}x pitch={clip.get('speed_pitch', 'up')}" if speed != 1.0 else ""), font=f1, fill=(255, 255, 255))
    src = f"{Path(clip['source']).name}  {info['width']}x{info['height']}  rot={info['rotation']}  " \
          f"{info['vcodec']} {info['pix_fmt']} trc={info['color_transfer'] or '-'}{' HDR' if info['is_hdr'] else ''}" \
          f"{'' if info['has_audio'] else ' NO-AUDIO'}  enc={attempt['enc']}"
    d.text((gap, 32), src, font=f2, fill=(190, 190, 190))
    d.text((gap, 52), f"title: {title}", font=f2, fill=(255, 220, 120))
    for idx, fnum in enumerate(frames):
        r, c = divmod(idx, cols)
        x = gap + c * (tw + gap)
        y = head_h + r * (th + lab_h + gap)
        p = tmpd / f"f_{idx + 1:03d}.png"
        if p.exists():
            sheet.paste(Image.open(p).convert("RGB"), (x, y + lab_h))
        d.rectangle([x, y, x + tw, y + lab_h - 1], fill=(50, 50, 50))
        d.text((x + 4, y + 3), f"t={fnum / fps:6.2f}s  {picks[fnum]}", font=f2, fill=(255, 255, 255))
    wy = head_h + rows * (th + lab_h + gap) + gap
    if wav.exists():
        sheet.paste(Image.open(wav).convert("RGB"), (gap, wy))
    else:
        d.text((gap, wy + 30), "no audio waveform", font=f2, fill=(255, 80, 80))
    ww = W - 2 * gap
    for sg in segs[1:]:  # jump cut markers
        xx = gap + int(sg["o"] / speed / total * ww)
        d.line([xx, wy, xx, wy + wave_h], fill=(255, 80, 80), width=2)
    d.text((gap, wy + wave_h + 2), "audio waveform (red = jump cuts)", font=_font(14, False), fill=(150, 150, 150))
    sheet.save(out_jpg, quality=88)
    shutil.rmtree(tmpd, ignore_errors=True)
    return out_jpg


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Render clips.json into vertical mp4s + QA sheets")
    ap.add_argument("clips_json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="comma separated clip ids")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--work", default=None, help="work dir holding <source-stem>/transcript.json "
                                                 "(default: ../work next to clips.json)")
    ap.add_argument("--skip-existing", action="store_true", help="skip clips whose mp4 already exists")
    ap.add_argument("--hwdec", choices=["auto", "off"], default="auto")
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.clips_json).read_text(encoding="utf-8"))
    cfg = spec.get("output", {}) or {}
    for k, v in (spec.get("style") or {}).items():  # optional per-file STYLE overrides
        STYLE[k] = tuple(v) if isinstance(v, list) and isinstance(STYLE.get(k), tuple) else v
    clips = spec["clips"]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        clips = [c for c in clips if c["id"] in want]
    out = Path(args.out)
    (out / "qa").mkdir(parents=True, exist_ok=True)
    if args.skip_existing:
        clips = [c for c in clips if not (out / f"{c['id']}.mp4").exists()]
    work = args.work
    if work is None:
        cand = Path(args.clips_json).resolve().parent.parent / "work"
        work = str(cand) if cand.exists() else None
    log(f"rendering {len(clips)} clips with {args.jobs} jobs -> {out}")
    t0 = time.time()
    results, failed = [], []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(render_clip, c, cfg, args, work, args.jobs): c["id"] for c in clips}
        for fu in as_completed(futs):
            cid = futs[fu]
            try:
                r = fu.result()
                results.append(r)
                log(f"OK   {cid}: {r['dur']:.1f}s out, {r['segments']} seg, {r['wall']:.1f}s wall "
                    f"({r['dur'] / max(r['wall'], 1e-6):.2f}x), enc={r['attempt']['enc']} hwdec={r['attempt']['n_hw']}")
            except Exception as e:
                failed.append(cid)
                log(f"FAIL {cid}: {e}")
                if os.environ.get("RENDER_DEBUG"):
                    traceback.print_exc()
    wall = time.time() - t0
    tot = sum(r["dur"] for r in results)
    log(f"done: {len(results)} ok, {len(failed)} failed, {tot:.1f}s of video in {wall:.1f}s "
        f"({tot / max(wall, 1e-6):.2f}x realtime)" + (f"; failed: {','.join(failed)}" if failed else ""))
    try:
        (out / "_tmp").rmdir()
    except OSError:
        pass
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
