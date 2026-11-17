---
name: irl-clipping
description: Turn raw IRL vlog footage into short social clips (Reels, TikTok, Shorts) using the creator's own evidence-based playbook and local pipeline - transcribe, pick moments, cut, title, crop, render, visually check, publish a review page, and learn from which clips the creator picks. Use this whenever the user asks to clip, cut, mass-clip or find moments in raw vlog or IRL footage, make reels or shorts from a vlog, rerun or tune the clipping pipeline, review or pick clips, read the picks, update the playbook or rubric from picks or posted results, or study other creators' reels for what works - even if the request does not say "pipeline", "playbook" or "skill".
---

# IRL clipping

This skill holds everything learned from a frame-by-frame study of 88 Instagram reels (outliers and flops from Lacy, Marlon, TJR and Stable Ronaldo) and from running a clipping pipeline on the creator's own raw footage. It has three parts:

- **The playbook** (`references/`): what makes a moment worth clipping and how to cut it, with the evidence.
- **The pipeline** (`scripts/`): raw file in, rendered clips and a review page out.
- **The feedback loop** (`feedback/`): every review round is recorded, and the playbook is edited from it.

The skill folder is the source of truth. When the playbook changes, change the files here, log it in `feedback/CHANGELOG.md`, and rebuild the playbook page. Do not keep a private improved copy in a session folder: the next session will not see it.

## Read first

1. `references/PLAYBOOK.md` (about 1,900 words). It is the reasoning behind every rule below, and you will make better calls on edge cases having read it than by following the steps blind.
2. `feedback/CHANGELOG.md`: what has changed since the study and why, plus open questions.
3. `config.json`: where the data, the `.env` file and the study data live on this machine. It is not in the repository; if it is missing, copy `config.example.json` to `config.json` and ask the user for the paths.

## Ground rules, and why

- **Raw footage is read-only.** Nothing in the pipeline needs to write next to the source files.
- **No recursive reads or searches under a OneDrive folder.** OneDrive downloads every cloud-only file a tool touches; one stray recursive grep pulled 96 GB onto the system drive. List single folders, never walk the tree.
- **Keep at least 10 GB free on C:.** Work folders, renders and previews go on D: (`data_root` in `config.json`).
- **The ElevenLabs key never appears anywhere.** `common.get_secret` loads it at run time. Do not print, log, echo or copy it.
- **Ingest uploads audio to ElevenLabs.** Only ingest footage the user named for clipping. If you fall back to other footage, say so before you transcribe it.
- **Private information never ships.** Do not clip a moment where keys, passwords, cards, addresses or private messages are readable on screen (this happened: a tutorial recording showed live API keys). Skip slurs. Flag swearing rather than removing the clip.
- **Check running processes with PowerShell** (`Get-CimInstance Win32_Process`). Git Bash `ps` does not see Windows processes, and a wrong "nothing is running" once started a duplicate batch.
- **Use subagents for the reading-heavy steps** (selection, visual QA, synthesis) and keep only their summaries. The user asked for this to control token cost; it also keeps the lead's context free for decisions.
- **Report quality honestly.** If nothing scores above 75, say the footage was thin. Meet a clip count with variations of strong moments, never by padding in weak ones.

## The run

Give each shoot its own run folder so caches never collide (camera file names repeat across days):

```
<data_root>\<run>\work\    per-source analysis, cached
<data_root>\<run>\clips\   rendered clips, plans, QA sheets
```

(The first run predates this layout and lives in `<data_root>\work` and `<data_root>\clips`.) Run every script from `scripts/`.

| Step | What | Command or actor |
|---|---|---|
| 0 | Preflight: footage finished copying (no `.crdownload`), disk space, key present | `python -c "import common; print(bool(common.load_env().get('ELEVENLABS_API_KEY')))"` |
| 1 | Ingest each raw file: transcript with speakers and audio events, sound labels, loudness, text timeline. Cached, about 4x faster than real time | `python ingest.py "<file or folder>" --work "<run>\work"` |
| 2 | Select moments from the text timelines | Subagents, one per about 40 minutes of footage. Prompt in `references/prompts.md`. They write `candidates_NNN.json` beside each timeline |
| 3 | Plan clip specs: dedupe, start on the hook line, end on a sentence, cut dead air, face-centred crop, variations | `python plan.py --work "<run>\work" --out "<run>\clips" --n 50 --min-score 55` |
| 4 | Render both shapes with QA contact sheets | `python render.py "<run>\clips\clips_square.json" --out "<run>\clips" --work "<run>\work" --jobs 3`, then the same with `clips_vertical.json` |
| 5 | Visual QA | `python qa_input.py "<run>\clips" "<run>\work"`, then subagents (about 17 clips each) with the prompt in `references/prompts.md`; they write `qa_result_N.json` |
| 6 | Apply QA | Write `<run>\clips\overrides.json` (below), rerun steps 3 and 4 |
| 7 | Index | `python make_index.py "<run>\clips"` writes `README.md` with tiers |
| 8 | Review page | See "Review page" below |
| 9 | Learn | See "Refining the playbook" below |

Step 5 is not optional. Selection reads text only and cannot see where the camera points: in the first run 2 of 20 moments were unusable on screen (camera on a hoodie during the punchline; whip-pans), and 18 of 50 clips needed a crop shift, a new title or an earlier ending.

Run a 5-clip test (`--n 5`) before a full batch when anything in `plan.py`, `render.py` or `style.json` has changed.

### overrides.json

QA decisions, keyed by moment key `<source stem>@<candidate start in whole seconds>` (shown in `plan.md` and in each clip's `_meta.key`):

```json
{
  "drop":      {"C9543@125": "camera on a hoodie while the payoff is spoken"},
  "crop_x":    {"C9555@857": [0.515, 0.515, 0.515]},
  "max_out_s": {"C9548@31": 29.0},
  "title":     {"C9550@126": {"a": "His therapist's trick for panic attacks"}},
  "rank":      {"C9547@188": 0}
}
```

`crop_x` is one value per segment of the cut (0 = left edge, 1 = right edge of the source). `title` replaces the title of one version letter. `rank` 0 marks a moment the reviewers judged strong on screen (tier A); 1 is the default.

### What comes out

For horizontal camera footage each moment is rendered in several versions, so one cut can be tested in different shapes, titles and speeds:

- `_a` square 1080x1080, face-centred crop, one static title low in the frame. This is the look most of the studied IRL outliers use.
- `_b` vertical 1080x1920: a square picture on a blurred background with a different title in the band above (or a full 9:16 crop when one subject fits).
- `_c` square with burned word subtitles and a third title.
- `_d` the `_b` version sped up (`speed` in `references/style.json`: factor 1.5, normal voice pitch). Added at the creator's request for comedic effect.
- `_e` appears only when `speed.pitch` is set to `up` (voice rising with the speed): it is then the pitch-kept copy for moments listed under `speed_pitch_kept` in `overrides.json`. The creator chose normal pitch, so it is normally absent.

`_a` to `_c` count against `--n`; the speed versions are added on top, so switching them on never changes the others. Titles and subtitles are set in the typeface named under `fonts` in `style.json` (TikTok Sans, bundled in `assets/fonts/`), drawn as `title_look` describes: about semibold weight, thin dark outline, soft shadow, matched against caption frames from the studied reels. A missing font file stops the plan instead of falling back to another typeface.

Tell the user to post one version per moment per platform. No music is added; guidance for adding a sound at posting time is in `references/style.json` under `music`.

## Review page

The creator reviews clips on a hosted page and their picks are saved where you can read them.

1. `python review/make_previews.py "<run>\clips" "<site>"` (small copies; originals are too large to host).
2. `python review/build.py "<run>\clips" "<site>" --title "<Month day> clip picks" --run <run>`.
3. `python review/publish_batches.py "<site>"` prints the file lists. Publish batch 1 as a new page with the artifact file-publishing tool, then each further batch as a republish (limits: 20 MiB per file, 64 MiB per call). `<site>` must sit inside the session's working folder or the upload is refused.
4. Declare the page's capabilities as `{"db": {}, "user": {}}` so picks are saved. Give the user the link.
5. Add the page to `feedback/rounds.md`: run name, clips folder, page link and slug.

Picks land in the page's database: collection `picks`, one document per moment (`picks/c01`) holding `{good: ["c01_a"], none: bool, note: str, at: ms}`. If saving was unavailable the user pastes the text from the page's "Copy picks" button instead; `feedback.py` reads both.

## Refining the playbook

After each review round, follow `references/refining.md`. In short: save the picks to a file, run `python feedback.py "<run>\clips" <picks file> --round <run>`, read `feedback/SUMMARY.md` and every note, make the smallest justified edit to `rubric.md`, `style.json` or `PLAYBOOK.md`, log it in `feedback/CHANGELOG.md`, rebuild and republish the playbook page (`python build_playbook_page.py --out <dir>`), and copy the picked full-quality clips into `<run>\clips\selected\`.

Keep three kinds of evidence apart, because they answer different questions: the reel study says what performed for other creators, the picks say what this creator will post, and posted results (`feedback/posted.csv`) say what performs for this creator. The last outranks the other two as soon as it exists.

## Where things are

| Need | Read |
|---|---|
| Why a rule exists, the principles, confidence and gaps | `references/PLAYBOOK.md` |
| What to select, how to score, title templates | `references/rubric.md` (handed to selection subagents) |
| Edit defaults: length, tightening, title, subtitles, layout, audio | `references/style.json` (read by `plan.py`) |
| What visual QA checks | `references/qa_brief.md` (handed to QA subagents) |
| Subagent prompts for selection and QA | `references/prompts.md` |
| How to turn picks into changes | `references/refining.md` |
| Pipeline design and file formats | `references/DESIGN.md` |
| The numbers behind the playbook | `references/evidence/aggregate.md`, `aggregate.csv` |
| Per-creator reel reviews, one packet per studied reel | `references/evidence/reviews/`, `references/evidence/packets/` (read only the ones you need) |
| How the reel study was run, and how to extend it to new creators | `references/study.md`, `scripts/study/` |
| Lessons from past runs | `references/lessons.md` |

## Known limits

- Selection is text-only, so a visual payoff with no words can be missed and a spoken payoff can land while the camera points elsewhere. Visual QA catches the second; nothing yet catches the first.
- Framing uses the area-weighted centre of detected faces and misses people in profile or with their back to the camera. QA crop shifts fix these per clip.
- ffmpeg's NVENC encoder needs NVIDIA driver 570 or newer (565.90 was installed at the first run). The renderer falls back to another GPU encoder by itself; 50 clips took about 6 minutes.
- The reel study covers four large creators. Section 8 of the playbook lists what does not transfer to a small creator's ordinary-day footage.
