# Lessons from past runs

Short, dated, practical. Add a line when something breaks or a check proves its worth. Playbook findings go in `feedback/CHANGELOG.md`, not here.

## Selection and cutting
- 2026-11-15: Text-only selection cannot see the camera. Two of 20 moments were unusable on screen (camera on a hoodie through the punchline; whip-pans). Visual QA of contact sheets is required every run.
- 2026-11-15: Clips started on stray words from the previous sentence until the planner anchored the start on the selector's `hook_line`. Selection subagents must copy the hook line exactly from the timeline.
- 2026-11-15: Clips ended mid-sentence until the planner snapped the end to the last sentence-final word after the payoff.
- 2026-11-15: Quote-style titles often lack context for a stranger. Reviewers rewrote 9 titles, mostly quotes; "what happened" titles were the safest.
- 2026-11-15: Centring the crop on the span of all faces looked worse than the area-weighted mean of faces. Keep the weighted mean; fix the exceptions with QA crop shifts.
- 2026-11-15: A tutorial or screen-recording day yields almost nothing (3 weak candidates from the November 1 files) and can show secrets on screen. Ask what the footage is before spending a transcription on it.
- 2026-11-15: Ordinary-day banter with friends topped out at a selection score of 70. The rubric's high bands need strangers, confrontations or reveals; say so rather than inflating scores.

## Machine and tooling
- 2026-11-15: A recursive `grep` under OneDrive forced a 96 GB download. Never walk that tree. To send files back to online-only: `attrib +U -P <file>` with OneDrive running.
- 2026-11-15: Git Bash `ps` does not list Windows processes; a false "all done" launched a duplicate batch. Use PowerShell `Get-CimInstance Win32_Process`.
- 2026-11-15: A large browser download (the designated test footage, about 41 GB in) vanished mid-run. Check for `.crdownload` files and confirm the footage is complete before planning a run around it.
- 2026-11-15: NVENC is unavailable below NVIDIA driver 570; the renderer falls back by itself.
- 2026-11-16: Hosted review pages allow 20 MiB per file and 64 MiB per publish call. Previews at 480 px and about 450 kbps put 50 clips at 63 MiB, published in two calls.
- 2026-11-16: The built-in browser is not signed in to claude.ai, so a published page cannot be checked there. Test pages on a local preview server before publishing.
- 2026-11-16: The first `plan.py` run on a shoot takes about 5 minutes (it reads the source video for face-centred framing). Results are cached in `<work>/_face_cache.json`, so later runs take seconds. Do not run two first-time plans at once, and wait for one before test renders (they compete for the CPU).
- 2026-11-16: Re-rendering replaces files of the same name. Move the previous renders into a dated subfolder first (as with `_v1_segoe`) so the creator can compare looks.
- 2026-11-16: "Use this font" is not done when the family is right. Draw the title on top of a reference frame and compare weight, size and outline before rendering a full batch: the first TikTok Sans pass used Bold with a heavy outline and did not look like the references.
- 2026-11-16: When re-rendered files keep their names, a browser may keep showing the old preview. The review page now adds a build id to preview requests.
