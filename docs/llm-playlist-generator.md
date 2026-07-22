# LLM Playlist Generator — FAQ

The Playlist Generator turns a Spotify playlist into a Beatify playlist file. **Beatify never calls an LLM itself** — it hands you a prompt, you run it in whatever assistant you already use, and you paste the JSON back. Everything below is about that middle step, because that is where it goes wrong.

The admin UI carries a short version of this in the guide accordion at the top of the generator modal. This page exists so the same answers are findable *outside* the app — from a search engine, or as a link in a forum reply.

## The flow

1. Paste the Spotify playlist URL, click **Copy prompt**.
2. Run the prompt in ChatGPT, Claude, or a local model.
3. Paste the JSON back into Beatify.
4. Click **Validate** — you get a ✓/✗ per field, per song.
5. Then either **Save locally** (lands in `<config>/beatify/playlists/user/`, shows up in the Community tab) or **Submit as GitHub issue**.

---

## "It stops after about 30 songs"

**This is the single most common problem, and it is not a bug in Beatify or in your assistant.** It is the response length.

Beatify asks for 15 fields per song, and two of them are expensive: seven regional Apple Music IDs, and the same fun fact translated into five languages. One finished song looks like this — this is the gold-standard example from the prompt itself:

```json
{
  "artist": "U96",
  "title": "Das Boot",
  "year": 1991,
  "isrc": "DEPI81403435",
  "uri": "spotify:track:5A3IdgGphzKS2etiGFB73S",
  "uri_apple_music": "applemusic://track/965771834",
  "uri_apple_music_by_region": { "us": "…", "de": "…", "gb": "…", "fr": "…", "es": "…", "nl": "…", "it": "…" },
  "uri_youtube_music": "https://music.youtube.com/watch?v=0snTYLgg9w0",
  "uri_tidal": null,
  "uri_deezer": "deezer://track/94877938",
  "fun_fact": "A trance and dance-floor classic (1991).",
  "fun_fact_de": "…", "fun_fact_es": "…", "fun_fact_fr": "…", "fun_fact_nl": "…"
}
```

That is **roughly 920 characters, or about 260 tokens, for one song**. Which means:

| Songs | Rough output size |
|---|---|
| 30 | ~7 900 tokens |
| 32 | ~8 400 tokens |
| 50 | ~13 100 tokens |
| 100 | ~26 300 tokens |

Many chat assistants cap a single reply at around 8 000 tokens. That is why the wall sits near 30–32 songs and not somewhere random — you are not hitting a Beatify limit, you are hitting the assistant's maximum reply length.

**What it looks like when you hit it**

- The JSON simply stops mid-song, often mid-string. Pasting it back gives a parse error.
- Some assistants end the reply cleanly but silently short — you get 30 songs out of a 100-song playlist and no warning.
- ChatGPT sometimes aborts with an error message that does not mention length at all. Length is still almost always the cause.

**The fix: run it in batches**

Split the playlist into **batches of about 30 songs**, run the prompt once per batch, then merge the `songs` arrays into one file. Keep the top-level fields (`name`, `version`, `tags`, `language`, `author`, `added_date`, `description`) from the first batch and drop them from the rest.

If your assistant offers a "continue" button, prefer restarting with a clean batch instead. Continuations tend to re-emit or skip a song at the seam, and a duplicate or a hole is harder to spot afterwards than a clean batch boundary.

---

## "The JSON does not validate even though it looks fine"

A few things travel along with copy-paste that are not part of the JSON. Beatify already strips the common ones automatically and shows you what it changed, so try **Validate** first — but if it still fails, these are the usual suspects:

- **Markdown fences.** Assistants add ```json around the object although the prompt asks them not to. Beatify extracts what is between the fences.
- **Angle brackets around URLs.** Some chat renderers turn a bare URL into `<https://…>`, and the brackets end up inside the string value. Beatify strips these on the known URI fields only — stripping them everywhere would silently mutate a `fun_fact` that legitimately contains `<…>`.
- **A preamble or a closing sentence.** Beatify trims everything before the first `{` and after the last `}`.

## "Some IDs are flagged as suspicious"

The validator checks shape, and it also flags values that match patterns typical of a guessed identifier. Shape-valid does not mean correct: an assistant can produce a well-formed Apple Music ID that points at a different recording, or an ISRC that belongs to another release of the same song.

If you cannot verify an identifier against the actual service, leave the field as it is and add `(LLM-generated identifiers — verify with the Beatify URI resolver)` to the playlist `description`. That is what the prompt asks for, and it tells the reviewer what still needs a pass.

## "Which assistant should I use?"

Any of them. The prompt is deliberately plain English and asks for nothing model-specific. The only property that matters in practice is how much the assistant will emit in one reply — which is exactly what the batching advice above is about.

## "Does Beatify send my data anywhere?"

No. The generator builds a prompt string and puts it on your clipboard. What happens after that happens in your assistant, under your account. Beatify sees the JSON only when you paste it back, and it is validated in your browser.

---

## Known limitations

- **No automatic merging of batches.** You merge the `songs` arrays yourself. Beatify validates whatever single JSON object you paste.
- **`uri_tidal` may be `null`.** It is the one URI field the prompt allows to be empty; Beatify's Tidal backfill fills these in later.
- **Apple Music identifiers are the weakest link.** Seven regional IDs per song is a lot to ask of a model that cannot query the store. Expect to verify these.
