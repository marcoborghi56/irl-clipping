# Reel review brief

## Why this exists
A creator films raw IRL vlog footage (hours of handheld, unscripted, real-world video) and wants to mass-produce short clips from it. We are studying Instagram reels from four big creators to learn (1) which *moments* are worth clipping and (2) how they are *edited*. Your notes feed a moment-selection rubric and an edit spec. Reels are tagged `outNN` (performed far above that creator's neighbouring posts; the multiplier is in the folder name) or `flopNN` (performed at roughly half of neighbouring posts). The contrast between the two is the point: we want what outliers have that flops lack, not a description of the creator's general style.

## What you have per reel
Each reel has a folder `analysis_set/<creator>/<reel>/` containing:
- `packet.md`: metrics, timed transcript (Whisper, can mishear names/slang), on-screen text timeline from OCR (can contain garbage strings; `y` is vertical position, 0 top to 1 bottom), cut times, zoom events, face/text coverage. Read this first.
- `hook.jpg`: a frame every 0.25s for the first 3 seconds.
- `shots.jpg`: one frame per detected shot, in order, timestamped.
- `timeline.jpg`: one frame per second across the whole reel.
- `energy.png`, `motion.png`: loudness and motion charts. Open only if the packet leaves a question (e.g. where the loud moment is).

Read `packet.md`, `hook.jpg` and `shots.jpg` for every assigned reel. Open `timeline.jpg` when shots.jpg has few frames or the structure is unclear. Do not open the video files, do not run analysis commands, and do not read or search anything outside the `research` folder.

## What to write per reel (keep each reel to about 90-120 words, this exact field order)
```
### <reel> (<outlier|flop> <score>x, <format>, <duration>s)
moment: what actually happens, in one sentence, and the reason a stranger would watch or share it (conflict, embarrassment, reveal, absurdity, skill, wholesome, status, relatable, celebrity/crossover, etc.)
hook 0-3s: what is on screen and said in the first 3 seconds; is the payoff teased, is it a cold open mid-action, is there a title caption
structure: beats with timestamps (setup -> escalation -> payoff); where the payoff lands (seconds and % of runtime); how it ends (hard cut on reaction, loop, fade, outro)
footage: one continuous take or multiple clips; who holds the camera (selfie, friend/cameraman, stream cam, security/phone footage); how raw it looks
edit: caption style (static title vs word-by-word subtitles, position, quotes, emoji), layout (full 9:16, square, letterboxed with bars, split screen, blurred background), punch-ins/zooms, inserted memes/reactions/b-roll, music or sound effects, speed changes
raw-footage signal: what in hours of raw footage would have flagged this moment for a clipper (a spoken line, shouting/laughter spike, a stranger entering, a sudden movement, a reveal)
```
For flops add one line: `why weaker:` your best explanation versus this creator's outliers (be specific, and say "unclear" if it is).

Be concrete and literal: quote the caption text and the key spoken line. If a format tag in the packet looks wrong (tags: irl, talking, stream, edit, produced, ad, repost), say so. If you cannot tell something from the material, write "can't tell" rather than guessing.

## After the per-reel notes
End the file with `## Patterns in this batch`: 5-8 bullets on what the outliers share that the flops lack, covering moment type, hook, length, structure, and edit treatment. Mark each bullet with how many of your reels support it (e.g. "6 of 8 outliers").

## Output
Write the notes to the file path given in your task, in Markdown. Then reply with only: the file path, and the 3 strongest patterns in under 80 words. Your reply is read by another model, so keep it plain and factual.
