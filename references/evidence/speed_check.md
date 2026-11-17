# Speed-up check (88 study reels)

Script: `scripts/study/speed_check.py`. Per-reel data: `speed_check.csv`.

## Method
- Re-transcribed with faster-whisper medium (word timestamps, VAD, English) and dropped words with probability under 0.4.
- Articulation rate: syllables/s inside speech runs (gaps under 0.35 s, at least 4 words), duration-weighted median. Judged only with at least 25 words in 3 or more runs, and a rate of at least 3.0.
- Pitch: 20th-percentile pyin F0 on in-word, speech-dominant frames, vs the creator's low reels. A lift counts only if undoing it leaves at least 3.3 syl/s.
- Video was not used.

## Sanity check
1.25x and 1.5x copies of lacy flop04, lacy out14 and tjr flop02, made with atempo (pitch kept) and asetrate (pitch raised):
- Rate: x1.19-1.30 at 1.25x and x1.43-1.59 at 1.5x.
- F0: flat under atempo; +4 st at 1.25x and +7.5 st at 1.5x under asetrate.
- On a music-bed reel (marlon out06) the rate did not track the speed.
- Normal speech here: 3.8-5.4 syl/s.

Thresholds: sped up = rate of 7.0 or more, or 6.0 or more with a consistent lift of 3 st or more. Normal = under 5.5.

## Results (sped up / normal / cannot tell)

| creator | outliers | flops | median rate (out / flop) |
|---|---|---|---|
| lacy.himself | 0/5/11 | 0/2/4 | 4.9 / 5.2 |
| marlon3lg | 2/4/10 | 0/1/5 | 5.4 / 5.0 |
| stableronaldo | 0/6/10 | 0/2/4 | 5.1 / 5.1 |
| tjr | 0/8/8 | 0/3/3 | 4.2 / 5.1 |

The two sped-up reels are estimated at about 1.4x and 1.85x. 55 of 88 reels cannot be judged (music, silence, sparse speech).

**lacy.himself:** "almost all sped up" is not supported. No reel reaches the sped-up bar. His 7 judgeable reels read 3.7-5.2 syl/s, including out12 (863 words). Three reels (flop05, flop06, out06) sit at 6.3-6.45 and are possible mild speed-ups. 15 of 22 reels are unjudgeable.

**Outliers vs flops:** no separation. Median rate is 4.85 for 31 judged outliers and 5.05 for 17 judged flops.

## Uncertain
- A 1.2-1.3x speed-up looks like fast natural talk. "Likely normal" rules out about 1.4x and above only.
- Pitch is noisy: shouting, other voices and octave errors give implausible lifts of 9 to 24 st.
- Reels without speech need a video-side check.

## Check by watching
Most likely sped up (only 1 and 2 meet the bar):
1. marlon3lg out13, 6.7 syl/s, +5.6 st, about 1.4x: https://www.instagram.com/reel/DbJwCAmvGm6/
2. marlon3lg out04, 6.45, +10.6 st, about 1.85x: https://www.instagram.com/reel/DcUJcFKh_ka/
3. lacy.himself flop06, 6.45: https://www.instagram.com/reel/DfAyRz4BxD_/
4. lacy.himself out06, 6.33: https://www.instagram.com/reel/Dc-AliNscqb/
5. lacy.himself flop05, 6.3: https://www.instagram.com/reel/DegGU6nhw-R/
6. marlon3lg flop06, 6.23: https://www.instagram.com/reel/Dd9mPm3v0Um/

Confidently normal:
1. lacy.himself out12, 5.24: https://www.instagram.com/reel/Dea0_-6hZMZ/
2. lacy.himself flop04, 4.01: https://www.instagram.com/reel/Dd1QqiBxh2l/
3. tjr flop02, 4.75: https://www.instagram.com/reel/DdSIOHRuVDr/
4. tjr out01, 3.96: https://www.instagram.com/reel/DdpZ3ZMudxu/
