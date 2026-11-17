# irl-clipping

A Claude skill that turns raw IRL vlog footage into short clips for Reels, TikTok and Shorts. It holds three things:

- **A playbook**: what makes a moment worth clipping and how to cut it, from a study of 88 Instagram reels (outliers and flops from four creators).
- **A pipeline**: scripts that transcribe the footage, cut and title the chosen moments, render them, and build a review page.
- **A feedback loop**: every review round is recorded, and the playbook is edited from what gets picked and how posts perform.

This repository is private on purpose. It contains study notes and transcripts of other creators' reels, and descriptions of footage that has not been posted. Do not make it public.

## Set up (once)

Built and tested on Windows 11. Other systems would need the font paths in `scripts/render.py` changed.

1. Install Python 3.12 and ffmpeg (ffmpeg must be on your PATH).
2. Clone this repository into Claude's skills folder, so the folder is named `irl-clipping`:

   ```
   git clone https://github.com/marcoborghi56/irl-clipping.git "%USERPROFILE%\.claude\skills\irl-clipping"
   ```

3. Install the Python packages:

   ```
   pip install -r requirements.txt
   ```

4. Copy `config.example.json` to `config.json` and fill in:
   - `data_root`: a folder on a drive with plenty of space. Work files and rendered clips go here.
   - `env_path`: a `.env` file that contains `ELEVENLABS_API_KEY=...` (used for transcription).

`config.json` and `.env` are not part of the repository and must never be committed.

## Use

Open Claude Code and ask in plain words, for example:

> Clip this vlog: D:\footage\2026-11-20

Claude loads the skill by itself and follows `SKILL.md`: ingest, pick moments, plan, render, visual check, review page. To work on the playbook, ask it to record a review round or update the playbook from the picks.

## What is where

| Path | What it is |
|---|---|
| `SKILL.md` | The instructions Claude follows. Start here to understand a run |
| `references/PLAYBOOK.md` | The principles and the evidence behind them |
| `references/rubric.md` | What to select, how to score, how to write titles |
| `references/style.json` | Edit defaults: length, title look, fonts, speed version, layout |
| `references/qa_brief.md` | What the visual check looks for |
| `references/evidence/` | Numbers, reviews and one page per studied reel |
| `scripts/` | The pipeline (`ingest`, `plan`, `render`, `qa_input`, `make_index`, `feedback`) and the review page builder |
| `scripts/study/` | Tools used for the reel study |
| `feedback/` | Review rounds, what the picks show, and the change log |
| `assets/` | Fonts and the face-detection model |

## Working on it together

- Pull before a run and push after any change to the playbook, rubric, style or scripts.
- Every change to how clips are selected or cut gets an entry in `feedback/CHANGELOG.md`: what changed, the evidence, how to undo it. `references/refining.md` has the rules.
- Rendered clips, work files and raw footage stay out of the repository.

## Credits and licences

- TikTok Sans (`assets/fonts/TikTokSans/`) is licensed under the SIL Open Font License; the licence text is beside the font files.
- `assets/face_yunet.onnx` is the YuNet face detector from the OpenCV Zoo.
