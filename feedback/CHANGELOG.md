# Playbook change log

Newest first. Every change to `references/` or to selection and cutting behaviour gets an entry: what changed, the evidence, the file, and how to undo it. Patterns that are not yet strong enough to act on go under "Watching".

## Watching

- **Playback speed.** The creator's impression is that almost all of Lacy's reels are sped up. The audio check (entry of 2026-11-16 below) could judge only 7 of Lacy's 22 reels and found those at a normal speaking rate; the other 15 have too little clean speech, and video speed was not measured. Being tested on the creator's own clips: every moment has a 1.5x normal-pitch version (`_d`). Watch whether `_d` gets picked over `_b`; then either make the sped-up version a default or switch `speed.enabled` off.
- **Quote titles.** Visual QA rewrote 9 titles in the first run, mostly quoted lines that lacked context. One run is not enough to demote the quote template; see whether picks agree. First signal from picks points the other way: see the next item.
- **Vertical version with a quoted line as title.** In the first review round (2026-11-16, 4 moments picked, 14 not yet reviewed) 3 of the 4 picks were the vertical version, all 3 with a quoted line as the title, and no subtitled version was picked. Four moments is far below the threshold for changing a default. If the next round agrees, make vertical with a quote title the first version and consider dropping the subtitled one.
- **What a pick looks like.** The 4 first-round picks span all three QA tiers (A, B, B, C) and selector scores from 55 to 66, while the two highest-scored moments (70) are so far unpicked. Not yet evidence of anything, since unreviewed is not rejected; ask the creator which of the 14 were passes.

## 2026-11-16: 1.5x at normal pitch, and titles matched to the reference captions (creator's direct instructions)

- **Speed.** After watching the 1.7x versions the creator asked for 1.5x with normal pitch. `speed.factor` is 1.5 and `speed.pitch` is `keep`; the pitch-kept extra copy (`_e`) is no longer produced. File: `references/style.json`. Undo: change the two values.
- **Title look.** The creator asked again for the titles to match the reference reels. The first TikTok Sans attempt (Bold, 6 px outline, 58 to 64 px) was the right family but read heavier and smaller than the references. Compared by drawing our title directly on caption frames from the studied reels: the references are about semibold weight with a thin outline and soft shadow at 62 to 78 px on a 1080-wide frame. Now SemiBold (28pt cut) at 68 px, 3 px outline, soft shadow. Files: `references/style.json` (`fonts`, `title_look`), `scripts/render.py` (`title_shadow`), `scripts/plan.py`. Undo: edit `title_look` and `fonts.title`.
- **No font fallback.** `plan.py` now stops if a configured font file is missing, instead of quietly using Segoe UI Bold.
- **Faster re-plans.** Face detection results are cached in `<work>/_face_cache.json`; a re-plan that only changes settings dropped from about 5 minutes to 2 seconds.
- **Review page.** Previews are requested with a per-build id so a browser cannot keep showing an older cached preview under the same file name (a likely reason the first font change was not visible to the creator).

## 2026-11-16: TikTok Sans titles and a 1.7x speed version (creator's direct instructions)

- **Typeface.** Titles and subtitles now use TikTok Sans Bold (28pt cut) instead of Segoe UI Bold. Evidence: the creator's instruction, to match the reels they take as inspiration; the study measured caption size and position but never identified typefaces. Files: `references/style.json` (`fonts`), `scripts/plan.py` (`font_file`), `assets/fonts/TikTokSans/` (open licence, text included). Undo: point `fonts.title` and `fonts.subtitles` at another file, or remove the block to fall back to Segoe UI Bold.
- **Speed version.** Each moment gets `_d`: the vertical `_b` version at 1.7x with the voice rising with the speed (measured +9.2 semitones on a test clip, as expected for 1.7x). Moments listed under `speed_pitch_kept` in `overrides.json` also get `_e`, the same with the pitch kept. Evidence: the creator's instruction (1.7x, for comedic effect); the only measured support is 2 sped-up Marlon outliers, both with rising pitch. Speed versions are added on top of `--n`, so the existing versions are unchanged. Files: `references/style.json` (`speed`), `scripts/render.py` (`clip_speed`, `_audio_speed`), `scripts/plan.py`, `scripts/make_index.py`, `scripts/feedback.py` (records speed per version), `scripts/review/`. Undo: set `speed.enabled` to false.

## 2026-11-16: playback speed checked by audio (no playbook change)

Question from the creator: are the outliers sped up 1.5x to 2x for comedic effect? Method: speaking rate in syllables per second inside runs of speech, plus voice pitch against the same creator's other reels, validated on 1.25x and 1.5x copies made for the purpose. Result across 88 reels: 2 likely sped up (both Marlon outliers, about 1.4x and 1.85x), 31 likely normal (23 outliers, 8 flops), 55 cannot be judged (music, silence or sparse speech). Among reels that got a verdict the median speaking rate is 4.78 syllables/s for 25 outliers and 4.44 for 8 flops, so speed does not separate them. The check cannot see a 1.2x to 1.3x speed-up and did not use video. Files: `references/evidence/speed_check.md`, `speed_check.csv`, `scripts/study/speed_check.py`. Playbook: one line added to section 9 (gaps). No default changed.

## 2026-11-16: skill folder created

Playbook, rubric, edit defaults, pipeline scripts, study scripts and evidence were gathered into this skill folder, with a script that records review rounds (`scripts/feedback.py`) and a rule set for turning them into changes (`references/refining.md`). No playbook content changed.

## 2026-11-15: first run on the creator's footage (October 28 vlog, 78 minutes)

Changes made while tuning the pipeline on real footage:

- Start clips on the selector's exact hook line; end on the last sentence-final word after the payoff. Evidence: first test renders opened on stray words and ended mid-sentence. Files: `scripts/plan.py` (`snap`), `references/rubric.md` (hook_line field).
- Square 1080x1080 with a face-centred crop and one static title became the primary look for horizontal camera footage, with a vertical version on a blurred background as the second. Evidence: 18 of 33 IRL outliers in the study are square, 12 vertical. Files: `scripts/plan.py` (`recipe`), `references/style.json` (layout).
- Visual QA by subagents on contact sheets became a required step. Evidence: 27 keep, 18 fix, 5 drop on the first pass of 50 clips. Files: `references/qa_brief.md`, `scripts/qa_input.py`.

## 2026-11-15: playbook v1 from the reel study

Written from 88 reels (four creators, outliers against flops). Core findings: one self-contained event plus a reaction; open cold on the premise; less talk and fewer text changes than flops; one static premise title; hard cut one to three seconds after the payoff; length, loudness, music, emoji and caption position do not separate outliers from flops. Files: `references/PLAYBOOK.md`, `references/rubric.md`, `references/style.json`.
