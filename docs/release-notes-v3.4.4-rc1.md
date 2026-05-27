## v3.4.4-rc1 — Loose Ends (Release Candidate 1)

**Test build.** First cut of the v3.4.4 changes. If you're on Android Companion and were still seeing the "unauthorized" message on v3.4.3, this is the one to test — please confirm on [#1153](https://github.com/mholzi/beatify/issues/1153) once you've installed it.

---

v3.4.3 was meant to be the end of the Android Companion saga. Then **@nelbs** updated to it and saw the same "unauthorized" message we'd just spent two weeks burying. One more corner case. v3.4.4 closes it, ships one new community playlist, grows an existing one, and corrects two song years.

### 🤖 Android Companion — fixed again, properly this time

A small piece of the login code wasn't routed through the new bypass we shipped in v3.4.3. On the phones where the previous fix didn't take, you opened Beatify and got the "unauthorized" alert instead of the admin screen. v3.4.4 closes that last gap. If you're on Android Companion and still seeing the error after updating, this should be it.

Thanks to **@nelbs** for catching it on day one of v3.4.3 and sending the screenshot.

### 🎸 essential-alternative — a new community playlist

100 tracks of 90s and 2000s alternative rock — Smashing Pumpkins, Radiohead, Nirvana, Foo Fighters, Weezer, Pearl Jam, Stone Temple Pilots, REM, and the rest of the canon. Spans 1991–2011, plays on all five music providers. Requested through the in-app "request a playlist" funnel and built into the curated catalog the same week.

### 🎌 anime-openings — 39 more tracks

The community anime-openings playlist grew from 101 to 140 songs this release. The new additions span twenty years of opening and ending themes — Code Geass, Fairy Tail, My Hero Academia, Demon Slayer, Attack on Titan, Suzume, and more.

### 📅 Two year corrections

- **Jennifer Rush — "The Power of Love"** is now tagged 1984 instead of 1985. The single came out in West Germany in December 1984; the famous UK release came in mid-1985, which is where the old tag came from. Reported in-game by Ingo.
- **Axwell /\ Ingrosso — "Sun Is Shining"** is now tagged 2015 instead of 2017. Reported in-game by Simon Herzog.

### 🙏 Thank you

To **@nelbs** for catching the Companion follow-up. To Ingo and Simon Herzog for using the in-game "wrong year" flag on the two songs above. To Kolja and Chelsia for three more reports that turned out to match how Beatify already tags those songs — every flag triggers a manual verification, and the ones that don't pan out are just as valuable as the ones that do.

---

**36 playlists · 4,112 songs · 5 music platforms · 5 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
