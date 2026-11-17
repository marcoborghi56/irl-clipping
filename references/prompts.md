# Subagent prompts

Selection and visual QA are done by subagents so the lead never loads timelines or contact sheets. Fill in the bracketed parts. Give each subagent only the paths it needs; it has none of your context.

## Selection (one subagent per about 40 minutes of footage; use a strong model)

```
You are choosing moments worth cutting into short social clips from the raw vlog footage of a small creator.
You cannot see the video. You have a text timeline: a speaker-labelled transcript with audio events and
{LOUD}/{LAUGH}/{SHOUT}/{CROWD}/{MUSIC} tags, and "-- silence Ns --" lines. Lines look like
[MM:SS.s-MM:SS.s] S1: text (laughter)  {LOUD +9dB} {LAUGH}

Read the rules first: [skill]\references\rubric.md
Then read these timeline files in order: [list of timeline_NNN.md paths for one source or a group of short sources]

For each timeline file write candidates_NNN.json beside it (same number), following the schema at the end
of the rubric. If a file has no moment that scores 40 or more, write an empty array.

Details that matter:
- Times in the JSON are source seconds as numbers. Convert MM:SS.s yourself (12:07.4 -> 727.4) and check
  that end > start and that payoff_at lies inside the clip.
- hook_line must be the exact first words the viewer should hear, copied from the timeline. The planner
  uses it to find the cut point.
- Chunks overlap by 60 seconds. Report a moment once, from the chunk where it is complete.
- Add "profanity" to risks when the clip contains swearing. Do not output a moment that contains a slur.
- If the talk suggests a screen, document, card, address or password is being shown or read out, add
  "sensitive_on_screen" to risks and say what in "why". If it is clearly a secret, do not output it.
- Do not pad. An hour of ordinary footage may hold two good moments or none. Score honestly against the
  rubric's bands; a 60 is a mild clip, not a good one.

Reply in under 150 words: number of candidates per file, the three best with score and one line each, and
anything about the footage the lead should know (wrong language, mostly silence, a tutorial rather than a vlog).
```

Cues the first run taught us to pass along when they apply: who S1 is (the creator), names of recurring friends so they are written as roles in titles, and any topic the user wants avoided.

## Visual QA (one subagent per about 17 clips; a cheaper model is fine)

```
You are the first person to look at clips that were chosen from a transcript by a model that could not
see the video. Be a strict, practical reviewer: the creator will post what you pass.

Read the brief: [skill]\references\qa_brief.md
Read the per-moment notes: [run]\clips\qa_input.md
Review these clips by opening their contact sheets in [run]\clips\qa\ : [list of clip ids]

Write your verdicts as a JSON array to [run]\clips\qa_result_[N].json in the format the brief gives,
then reply as the brief asks.
```

Turn the verdicts into `overrides.json`: `drop` for drops, `crop_x` for "shift left/right" (add or subtract the stated fraction from the value in `plan.md`), `title` for rewritten titles, `max_out_s` for earlier endings, and `rank: 0` for moments every version of which was kept with `holds_up: yes`. Then re-plan and re-render. After the second render, spot-check the changed clips yourself or send them through QA again; the first run only spot-checked two, which is thinner than it should be.
