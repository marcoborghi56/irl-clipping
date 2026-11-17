# The reel study: how it was done and how to extend it

The playbook rests on a study of 88 Instagram reels run on 2026-11-15. This file records the method so the study can be checked, repeated on new creators, or refreshed when styles change.

## What was studied

Four creators the user named: `lacy.himself`, `marlon3lg`, `stableronaldo`, `tjr`. Per creator: 16 outliers and 6 flops (one Lacy flop had no usable audio, so some tables show 5).

**Picking outliers that mean something.** Raw view counts reward old posts and big accounts, so each reel is scored against its own neighbours:

- View counts for about the last 200 reels per creator (`deep/<creator>.txt`, lines of `shortcode:views`).
- Post time decoded from the shortcode: base64-decode the shortcode to an integer id, then `(id >> 23) + 1314220021721` is the post time in milliseconds.
- Score = views divided by the median views of the 10 reels posted before and the 10 after. A score of 4 means four times that creator's typical reel at that time.
- Only reels at least 7 days old (views have settled).
- Outliers: the 16 highest scores. Flops: 6 reels scoring 0.35 to 0.65 (clearly under, but not a broken post).
- Every pick was screened on a contact sheet for format (`formats.json`: irl, talking, stream, edit, produced, ad, repost). Ads, reposts and produced pieces stay in the set but are excluded from the format tables, and the playbook weights the IRL format.

Post descriptions were ignored at the user's request.

## What was measured per reel

| Script | Measures |
|---|---|
| `scripts/study/analyze.py` | Cuts (scene detection), contact sheets (hook frame, shots, timeline), speech with word timestamps (faster-whisper medium), loudness (EBU R128), onsets |
| `scripts/study/frames.py` | Per-frame change, zoom and camera motion (optical flow), face position and size 5 times a second, on-screen text by OCR 5 times a second |
| `scripts/sound.py` | Sound events per half second (music, speech, laughter, shout, crowd, effects) with PANNs, and whether cuts fall on the beat |
| `scripts/study/packet.py` | One compact `packet.md` per reel and the aggregate tables (`aggregate.csv`, `aggregate.md`) |

Two reviewers per creator (subagents, briefed with `references/evidence/review_brief.md`) read the packets and contact sheets and wrote `references/evidence/reviews/<creator>_A.md` and `_B.md`. A synthesis pass over the eight reviews and the aggregate tables produced `references/PLAYBOOK.md`.

## What was not measured

- Playback speed was not part of the original study. It was checked afterwards by audio only (speaking rate and pitch; `references/evidence/speed_check.md`): 55 of 88 reels could not be judged and video speed is still unmeasured.
- Voice pitch, colour grade, transitions between shots beyond cut counts.
- Comments, shares, posting time of day, description text.
- Anything about the audience: the study shows what the reels look and sound like, not who watched.

## Where the data is

`study_root` in `config.json` (on D:): `set/<creator>/*.mp4` (the 88 reels, 576 MB), `analysis_set/<creator>/<reel>/` (per-reel measurements and sheets, 90 MB), `deep/`, `scored.json`, `views.json`, `formats.json`, `selected_reels.tsv`. The skill folder carries only the distilled parts under `references/evidence/`.

## Extending the study

The study scripts read and write under the folder named by the `STUDY_ROOT` environment variable (or the current folder), never inside the skill folder.

1. **View counts.** Collected in the built-in browser from each creator's public reels grid with the user signed in to Instagram, scrolling and reading the counts into `deep/<creator>.txt`. Calling Instagram's private API from the page was refused by the safety check; do not try to route around that.
2. **Score and pick.** `python scripts/study/rescore.py` from the study root writes `scored.json`; choose outliers and flops as above and screen formats with `scripts/study/screen.py`.
3. **Download.** `scripts/study/download_set.ps1 -Cookies <path>` shows the pattern (yt-dlp, 2 to 5 second pauses). It needs the user's own exported `cookies.txt`; treat that file like a password and never copy it.
4. **Analyse.** `analyze.py --dir set`, `frames.py --dir set`, `sound.py --dir set`, then `packet.py`. All skip reels already done and stop if C: has under 10 GB free.
5. **Review and fold in.** Reviewers per creator with the review brief, then update the playbook through the change log like any other refinement.

After the move into this skill folder the scripts were checked for syntax and `packet.py` was rerun against the stored data; a full fresh run (download through analysis) has not been repeated from here.
