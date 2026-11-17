# Visual QA brief for rendered clips

## Context
A pipeline cut short social clips out of a small creator's raw vlog footage (horizontal camera footage of him and friends at home, in a car, at the gym). The moments were chosen from the transcript alone, by a model that could not see the video, and the framing was set automatically by face detection. You are the first eyes on the result. Your job is to catch what a text-only selector cannot: the camera pointing away from the action, people cropped out, titles covering faces, private information on screen, a dead first frame. The creator will post the clips you pass, so be a strict, practical reviewer rather than a generous one.

## What you have
- `clips\qa_input.md`: one block per moment: what the clip is supposed to show, risk flags from selection, the variations (id, canvas, layout, title), and the words spoken in the cut with output timestamps.
- `clips\qa\<clip-id>.jpg`: a contact sheet per rendered clip: first frame, 0.5 s, a frame every 4 s, each jump-cut point, last frame, with the title as rendered, plus an audio waveform (red lines are jump cuts).
- Variations: `_a` is a square 1080x1080 crop with the title low in the frame. `_b` is a 1080x1920 vertical: usually a square picture centred on a blurred background with the title in the band above it. `_c` (only some moments) is the square crop with burned word subtitles and a third title. Variations of one moment share the same cut and the same horizontal crop position.

## What to check for each clip
1. **Subject on screen.** Is the person speaking or the thing being talked about visible for most of the clip? Note time ranges where the frame shows nothing useful (a chest, a ceiling, darkness, motion blur). If the spoken payoff happens while nothing useful is on screen, that matters most.
2. **Framing.** Is anyone important cut off at the edge of the square? If shifting the crop left or right would fix it, say which way and roughly how far as a fraction of the source width (e.g. "shift right 0.08"). If two people are too far apart to fit a square, say so.
3. **First frame.** Would the first frame make someone stop scrolling: a face, an action, an object of interest? Or is it empty, blurred, or someone's back?
4. **Title.** Readable? Does it cover a face or the key object? Does it honestly describe what the clip shows, in words a stranger understands, without spoiling the punchline? Flag any title that is misleading, confusing, or contains a name or in-joke. For `_b`, check the title sits cleanly in the top band. For `_c`, check subtitles do not collide with the title or cover faces.
5. **Privacy and safety.** Anything visible that should not be posted: phone or laptop screens with readable private content, API keys or passwords, addresses, licence plates, card details, people who are clearly not part of the group (strangers, minors), nudity.
6. **Is it a clip?** Having seen it, does the moment hold up as something a stranger would watch, given the transcript? Say so plainly if it reads as flat.

## Verdicts
- `keep`: postable as is.
- `fix`: worth posting after a specific change you name (crop shift, different title, trim range, drop subtitles).
- `drop`: not worth posting, or unsafe to post; say why in one line.

## Output
Write a JSON array to the path given in your task, one object per clip:
```json
{"id": "c03_a", "verdict": "keep|fix|drop", "subject_visible": "yes|mostly|no", "bad_ranges": ["12-20s camera on hoodie"],
 "framing": "ok | shift left 0.05 | shift right 0.08 | too wide for square", "first_frame": "one phrase",
 "title": "ok | problem and a better title", "privacy": "none | what and when", "holds_up": "yes|weak|no", "notes": "one or two sentences"}
```
Then reply with: counts of keep/fix/drop, the ids to drop with a few words each, and anything that looks systematically wrong across clips (for example titles always covering faces, or the crop always sitting too far left). Under 180 words; the reply is read by another model.
