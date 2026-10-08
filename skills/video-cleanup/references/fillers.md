# Filler words

Matching is on the lowercased word with punctuation stripped. Always included for every
language: `um, uh, uhm, umm, hmm, mm, erm`.

| lang | default list |
|---|---|
| en | um, umm, uh, uhh, uhm, er, erm, ah, hmm, mm, mhm, and "like" when comma-delimited |
| de | äh, ähm, ähh, öh, öhm, hm |
| fr | euh, heu, bah, ben, hum |
| es | eh, em, este, mmm |
| it | ehm, eh, uhm, mmm |
| pt | é, éé, hum, ahn |
| nl | eh, ehm, uhm, uh |
| ru | э, ээ, эм, ну |
| tr | ııı, şey, eee |
| ar | اه, ام, اممم, يعني |
| ja | えーと, えっと, あの, あのー, えー, うーん |
| zh | 嗯, 呃, 那个, 额 |

Some entries are real words in context (es "este", ru "ну", ar "يعني", ja "あの", zh "那个", fr
"ben"). If the report shows them cut where they carry meaning, rerun with `--fillers` listing only
the pure hesitations, or delete those drop entries from the EDL.

Phrases ("you know", "I mean", "sort of") are not removed by default: they are often meaningful
and cutting them mid-sentence sounds choppy. Drop specific instances by adding
`{"start": ..., "end": ..., "reason": "filler"}` entries to the EDL by hand.
