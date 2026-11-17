# Refining the playbook from review rounds

The playbook started as a study of other creators. It becomes this creator's playbook by absorbing two things over time: which clips they pick, and how the clips they post perform. This file says how to do that without fooling ourselves.

## Three kinds of evidence

| Evidence | What it tells you | Weight |
|---|---|---|
| Posted results: views of the creator's own clips against their own typical views (`feedback/posted.csv`) | What performs for this creator and audience | Highest. Outranks everything once there are about 10 posted clips |
| Reel study: 64 outliers against 24 flops from four large creators (`references/evidence/`) | What performed for other people's audiences | The base of the playbook. Strong on structure, weak on anything that depends on fame |
| Picks: which rendered clips the creator chose on the review page (`feedback/rounds/`) | What the creator is willing to post: taste, brand fit, what they find funny | Decides defaults and breaks ties. It is not proof a clip will perform |

A pick is a creator saying "I'd post this". They can be wrong about what their audience wants, and the study can be wrong about what suits them. When the two disagree, do not overwrite a studied principle with a preference: record the preference as theirs, apply it to their clips, and tell them the two disagree so posted results can settle it.

## After each review round

1. **Get the picks.** Read the review page's database (collection `picks`, the page slug is in `feedback/rounds.md`) and save the documents as JSON, or save the text the creator pasted from "Copy picks". Either goes in `feedback/picks/<run>.json` or `.txt` (raw picks; `feedback/rounds/` holds only what `feedback.py` writes).
2. **Record the round.** `python scripts/feedback.py "<run>\clips" "<picks file>" --round <run>`. This writes `feedback/rounds/<run>.json` and rebuilds `feedback/SUMMARY.md` across all rounds.
3. **Read `feedback/SUMMARY.md` and every note.** The notes are the most valuable part: one sentence from the creator about why a clip works is worth more than a pick-rate table built on 18 moments.
4. **Decide what changes** using the rules below.
5. **Log it** in `feedback/CHANGELOG.md`: date, round, what changed, the evidence in numbers, the file, and how to undo it. Patterns that are not yet strong enough go under "Watching" in the same file so the next round can confirm or kill them.
6. **Rebuild the playbook page** (`python scripts/build_playbook_page.py --out <dir>`) and republish it to the page recorded in `config.json` under `playbook_page`.
7. **Hand over the picks**: copy the picked full-quality files into `<run>\clips\selected\`.

## Rules for changing things

- **A direct instruction applies now.** "Never use quote titles", "no subtitles", "stop clipping gym footage": edit the file, log it, done. No threshold.
- **A pattern in picks changes a default only when it is solid**: at least 8 reviewed moments behind it in one round, or the same direction in two rounds. Eighteen moments split five ways is noise. Until then it goes under "Watching".
- **Check the selector's score first.** If picked and passed moments have about the same mean score, the rubric's scoring is not tracking the creator's taste. Read the passed moments' summaries and notes, find what they share, and adjust the score guidance in `rubric.md` (a deduction, a new skip rule, a re-ranked moment type).
- **Version preferences are cheap wins.** If one shape or title style wins clearly inside picked moments, make it the first version in `plan.py`'s recipe and consider dropping the loser to save render and review time.
- **Change the smallest thing.** One rule, one number or one sentence per finding. A rewrite hides what moved.
- **Posted results override.** With about 10 logged posts, compare views against the account's typical views by moment type, title style, shape and length. Where this contradicts picks or the study, the posted results win, and the change log says so.
- **Unreviewed is not rejected.** Only "picked" and "None of these" count. Ask before reading silence as a no.

## Which file a finding belongs in

- `references/rubric.md`: what to select, what to skip, how to score, how to write titles. Changes here alter which moments come out next time.
- `references/style.json`: numbers and switches for the cut (length, pause tightening, title position, subtitles, layout). `plan.py` reads it directly.
- `references/qa_brief.md`: what reviewers look for on the contact sheets.
- `references/PLAYBOOK.md`: principles and evidence. Change the studied sections rarely. Creator-specific findings go in their own section at the end ("What the creator's own picks and posts have shown") with the round and numbers.
- `references/lessons.md`: operational lessons (what broke, what to check).
- `scripts/`: only when a finding needs new behaviour, for example a new version type.

## Logging posted results

`feedback/posted.csv` has one row per posted clip: `clip_id, round, platform, posted_date, views_7d, account_median_views_7d, notes`. Views at 7 days against the account's median for the same period is the same outlier measure the reel study used, so the creator's own results can be read on the same scale. Ask the user for the numbers; do not scrape the creator's accounts without being asked.
