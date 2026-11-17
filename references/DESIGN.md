# Raw footage -> clips pipeline: design

Goal: turn raw IRL vlog footage (hours, unscripted, phone or camera) into ready-to-post short vertical clips, using the principles in `PLAYBOOK.md` (written from a study of 88 creator reels). The first real run delivered 50 clips and variations overnight.

## Designed with the 5-step algorithm

1. **Question every requirement.**
   - "Analyze raw footage frame by frame": not needed. Clip-worthy moments are found from what is said and heard (transcript, laughter, shouting, crowd, loudness). Video is only inspected for the candidates that survive.
   - "50 clips": a deliverable count, not 50 distinct moments. Weak moments are not padded in; the count is met with variations (alternate title caption, alternate start point or length) of the strongest moments.
   - "Fancy edit": the studied IRL outliers are mostly one moment, trimmed tight, with a single static title caption. No motion graphics requirement exists.
2. **Delete.** No per-frame optical flow, no OCR, no database, no web UI, no project-file export, no music bed, no b-roll. JSON files on disk are the only state.
3. **Simplify.** One transcript pass (ElevenLabs Scribe: words + speakers + audio events), one local sound-label pass, one loudness pass. One LLM selection pass over a compact text timeline. One ffmpeg invocation per clip.
4. **Accelerate.** Upload a small mono audio proxy, never the video. Cache every stage by source file. NVENC encoding, renders in parallel. Test on a 5-clip batch before the full run.
5. **Automate.** Each stage is a CLI that reads and writes files, so the whole run is a short script. LLM selection is done by subagents now and can become an API call later.

## Layout

```
scripts/
  common.py     paths (from config.json), .env loading, ffprobe helpers
  ingest.py     media file -> audio proxy, transcript, sound labels, loudness, LLM-readable timeline
  plan.py       candidates -> clip specs (dedupe, snap boundaries, tighten silences, face-centred crop, variations)
  render.py     clip specs -> mp4 files + QA contact sheets
  qa_input.py   per-moment notes for visual QA reviewers
  make_index.py ranked index of the rendered clips
  sound.py      sound labeler (label_file / label_audio), reused by ingest.py
  feedback.py   records a review round and rebuilds feedback/SUMMARY.md
  review/       review page: previews, page builder, publish batches
references/     PLAYBOOK.md, rubric.md, style.json, qa_brief.md (the knowledge the scripts and subagents use)
```

Work data lives on the data drive, not the system drive (`data_root` in `config.json`), one folder per run:
```
<data_root>\<run>\
  work\<source-stem>\        probe.json, audio.mp3, transcript.json, sound.csv, loudness.csv, timeline_NNN.md, candidates_*.json
  clips\                     final mp4s, clips_square.json, clips_vertical.json, overrides.json, qa\<clip-id>.jpg
```
Source media is read-only and is never modified.

## Data contracts

### ingest.py
`python ingest.py <media-file-or-folder> --work <work-dir>` ; idempotent, skips finished stages.

- `probe.json`: `{path, duration, width, height (display, after rotation), fps, rotation, vcodec, pix_fmt, color_transfer, color_primaries, is_hdr, audio_streams, size_bytes}`
- `audio.mp3`: mono, 16 kHz, 64 kbps (upload proxy).
- `transcript.json`: `{source, language, words:[{w, s, e, speaker, type}], raw: <provider response>}` where type is `word` or `audio_event` (e.g. "(laughter)"); spacing tokens dropped. Times in seconds on the source timeline.
- `sound.csv`: per 0.5 s scores for speech, music, laughter, shout, crowd, sfx, vehicle (from scripts/sound.py). Must work on multi-hour audio without holding all frame probabilities in memory (aggregate per chunk).
- `loudness.csv`: `t, rms_db` every 0.1 s.
- `timeline_NNN.md`: the only thing the selection model reads. Chunks of about 10 minutes with 60 s overlap. One line per utterance (split on speaker change or a pause over 0.7 s):
  `[MM:SS.s-MM:SS.s] S1: text (laughter)  {LOUD +9dB} {LAUGH} {SHOUT} {CROWD} {MUSIC}`
  plus a line `-- silence 4.2s --` for gaps over 2 s. Tags come from sound.csv and loudness (LOUD = more than 8 dB above the file's median speech loudness). Header states source file, chunk time range, and tag legend. Target: under 9 KB per chunk.

### candidates (written by selection subagents)
`candidates_<chunk>.json`: `[{source, start, end, moment_type, summary, hook_line, payoff_at, titles:[3 options], score (0-100), why, risks}]`

### clips.json (written by plan.py, read by render.py)
```
{"output": {"width":1080, "height":1920, "fps":30},
 "clips": [{
   "id": "c01_a", "variation_of": null, "source": "<abs path>",
   "segments": [[start, end], ...],          // source-time ranges, concatenated in order (jump cuts)
   "layout": "crop" | "fit",                // crop: fill the frame; fit: whole source frame centered on blurred background
   "crop_x": 0.5,                            // 0-1 horizontal centre for crop (per clip; may also be given per segment as a 3rd element dict)
   "zoom": [1.0, 1.12, ...] | null,          // optional per-segment punch-in factor
   "title": {"text": "Marlon breaks the door handle 😭", "y": 0.72, "start": 0, "end": null} | null,
   "subtitles": true|false,                  // burn word-level subtitles from transcript
   "speed": 1.7,                             // optional playback speed, applied last so titles, subtitles and cuts scale with it
   "speed_pitch": "up" | "keep",             // with speed: "up" lets the voice rise with the speed, "keep" time-stretches
   "loudnorm": -14
 }]}
```

### render.py
`python render.py <clips.json> --out <dir> [--only id,id] [--jobs 3]`
- Writes `<id>.mp4` (H.264 NVENC, yuv420p, bt709, about 10 Mbps, AAC 160k, 30 fps unless the config says otherwise, faststart) and `qa/<id>.jpg` (contact sheet: first frame, a frame 0.5 s in, one frame per segment start, last frame; each stamped with output time).
- Must handle: iPhone HDR/Dolby Vision HEVC (tone-map to SDR bt709 so colors are not washed out), rotation metadata, variable frame rate, sources with no audio, 4K sources, segments that touch file start/end. Audio joins get 8-10 ms fades so jump cuts do not click.
- Title: rendered to a transparent PNG with Pillow (bold sans, white fill, black stroke, color emoji via Segoe UI Emoji, auto-wrapped to max 2-3 lines at about 80% width) and overlaid; style values live in one `STYLE` dict at the top so the lead can tune them from the playbook.
- Subtitles (when enabled): ASS file built from transcript words remapped onto the output timeline (after jump cuts), 2-4 words per line.

## Environment facts
- Windows 11, Git Bash + PowerShell, Python 3.12, RTX 3060 6 GB, 16 CPU threads. ffmpeg 8.1 full build: h264_nvenc, libx264, zscale, tonemap, libplacebo, ass/subtitles, loudnorm, cuda hwaccel.
- Fonts in C:\Windows\Fonts: arialbd.ttf, segoeuib.ttf, impact.ttf, seguiemj.ttf (color emoji).
- Installed: numpy, opencv (headless), librosa, Pillow 13, torch (CPU), panns-inference, faster-whisper (CUDA), onnxruntime (CPU).
- ElevenLabs key: variable `ELEVENLABS_API_KEY` in the `.env` file named by `env_path` in `config.json`. Loaded at run time. Never print it, log it, or copy it into another file.
- Hard rules: never read file contents recursively under the OneDrive folder (it force-downloads cloud files). Keep at least 10 GB free on the system drive. Do not modify or delete anything in the raw footage folder.
