# Clip selection rubric (for the selection model)

You read a text timeline of raw vlog footage (speaker-labelled transcript, audio events, {LOUD}/{LAUGH}/{SHOUT}/{CROWD}/{MUSIC} tags, silence lines). You cannot see the video. Find moments a stranger would watch to the end. The creator is small, so celebrity moments are rare; target the everyday equivalents below. Evidence: `research/PLAYBOOK.md`.

## Qualifies: one self-contained event plus a reaction
Ranked by evidence:
1. **stranger**: the creator asks, offers, compliments or challenges a stranger, staff member or passer-by, and gets a surprising answer. Cues: a new speaker label; a direct ask or offer ("can I...", "I'll give you $20 if..."); a short reply ("No."), then {LAUGH}.
2. **confrontation**: an argument, a refusal, or being told off or stopped (security, a shop worker, a neighbour, a friend). Cues: "you can't...", "what are you doing", overlapping speakers, rising {LOUD}/{SHOUT}.
3. **prank_physical**: a dare, a trap, a fall, a scream, something broken. Cues: "watch this", "bet", {SHOUT}/{LOUD} spikes, "oh my god", "are you okay", "sorry".
4. **reveal_stakes**: a number, price, result or object revealed after a build. Cues: "how much", "guess", "let's see", counting, a price spoken aloud, a silence or stare then a loud reaction.
5. **embarrassment**: the creator fails, is caught out or admits something. Cues: "I broke...", "that's so embarrassing", others laughing at S1.
6. **wholesome_emotional**: helping someone, a sincere thank-you, a child's line, someone crying. Cues: "can you help me", "thank you so much", a child's voice, a voice breaking.
7. **mood**: a short scenic or deadpan moment that needs a song added at posting. Score 55 or lower.

## Skip
Greetings, plans ("today we're going to..."), announcements, sponsor reads, advice or opinion monologues, recaps, chatter with no event, in-jokes about people the viewer does not know, someone else's screen, and any payoff that needs explaining.

## Boundaries
- **Start** on the first word of the premise or action (the ask, the knock, "watch this"), never on "okay so", "guys", greetings or camera setup. One line of context is allowed, at most 3 s before the action. Never start in a silence.
- **End** 1-3 s after the payoff line or the peak reaction ({LAUGH}/{SHOUT} decay, the closing line such as "sorry about that"). No sign-offs.
- **Length:** target 15-35 s; min 7 s; max 60 s. Over 35 s only if a new beat lands every 8-10 s.
- **payoff_at** (source seconds) should fall at 50-85% of the clip. Earlier is acceptable only if what follows is reaction.

## Titles (3 options, each a different template)
Plain words a stranger understands, max 50 characters, at most one emoji at the end. Roles, not names ("my friend", "this guy", "a stranger", "security"). State the setup; never the punchline.
- **A, what happened:** `[Who] [did what] [where/when]`. Real: "Marlon broke the door handle", "Bro had the entire campus challenging him". Ours: "I asked a stranger for one fry 😭".
- **B, quoted setup line**, spoken in the clip, in double quotes: "It's soundproof", "Did they cut you?", "What were you doing before streaming?"
- **C, question or teaser:** "Where does Los go at night?", "A raid changed his life...". Ours: "He didn't expect security to say that..".
Bad: names, in-jokes, labels ("Aura."), announcements, spoilers.

## Risks to flag (in `risks`, as short strings)
`visual_only` (payoff likely visual: silence, "look", "did you see that"); `camera_off_action` ("behind me", "over there", off-camera noises); `bystander_faces` (identifiable strangers or minors, unclear consent); `needs_context`; `profanity`; `copyrighted_music` ({MUSIC} under the payoff); `speech_unclear` (payoff line under {CROWD}/{MUSIC}); `overlap` (same event as another candidate).

## Score (0-100)
- **90-100**: a stranger or confrontation moment, premise in the first line, a clear turn, an audible reaction ({LAUGH}/{SHOUT}), self-contained, 15-35 s. Rare: expect 0-3 per hour.
- **75-89**: a clear single beat of any ranked type; one weakness (premise slightly late, reaction quiet).
- **60-74**: works but is mild: a small laugh, low stakes, or needs a tight trim.
- **40-59**: filler; a mood piece; possibly visual-only. Output it only if the chunk has nothing better.
- **Below 40**: do not output.
Subtract 15 for `visual_only` or `camera_off_action`; 10 if S1 talks over 60% of the clip with no other voice or event.

## Output
Write `candidates_<chunk>.json`, an array:
```json
[{"source": "<file from header>", "start": 812.4, "end": 836.9,
  "moment_type": "stranger|confrontation|prank_physical|reveal_stakes|embarrassment|wholesome_emotional|mood",
  "summary": "One sentence: who does what, what happens.",
  "hook_line": "First words the viewer hears",
  "payoff_at": 829.1,
  "titles": ["A ...", "\"B ...\"", "C ..."],
  "score": 82,
  "why": "Which cues support it",
  "risks": ["visual_only"]}]
```
Times are source seconds. Chunks overlap by 60 s: report a moment once, from the chunk where it is complete.
