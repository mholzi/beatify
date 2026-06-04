"""Localized TTS announcement phrases.

Game TTS announcements were hardcoded English: the game's ``language`` setting
(en/de/es/fr/nl) was wired only to the web UI, so spoken announcements always
came out in English regardless of the selected language. This module holds the
spoken-phrase templates per language.

English is authoritative — its strings MUST stay byte-identical to the original
announcement code (the announcement tests pin them). Any missing language or
missing key falls back to English, and a translation that fails to format (e.g.
a stray placeholder) also falls back to English so a bad string can never break
a live game.

Templates are ``str.format`` strings; placeholders like ``{name}`` are filled by
the caller. ``{names}`` may hold a single name or several joined by
``join_names`` (the language's "and" word).
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

# Languages the game accepts (matches the validation in the WS/REST handlers).
SUPPORTED_LANGUAGES = ("en", "de", "es", "fr", "nl")

# Word joining names in a spoken list ("Marco and Anna"). The English form uses
# " and ".join(...) verbatim, so two names read "A and B" and the rare 3+ case
# reads "A and B and C" exactly as before.
_AND: dict[str, str] = {
    "en": "and",
    "de": "und",
    "es": "y",
    "fr": "et",
    "nl": "en",
}

# Spoken difficulty labels inserted into the game_start template via {difficulty}.
_DIFFICULTY: dict[str, dict[str, str]] = {
    "en": {"easy": "easy", "normal": "normal", "hard": "hard"},
    "de": {"easy": "leicht", "normal": "normal", "hard": "schwer"},
    "es": {"easy": "fácil", "normal": "normal", "hard": "difícil"},
    "fr": {"easy": "facile", "normal": "normale", "hard": "difficile"},
    "nl": {"easy": "makkelijk", "normal": "normaal", "hard": "moeilijk"},
}

# Podium place labels, used as "{label}: {name}" in the top-3 readout.
_PLACE: dict[str, dict[int, str]] = {
    "en": {1: "1st place", 2: "2nd place", 3: "3rd place"},
    "de": {1: "erster Platz", 2: "zweiter Platz", 3: "dritter Platz"},
    "es": {1: "primer puesto", 2: "segundo puesto", 3: "tercer puesto"},
    "fr": {1: "première place", 2: "deuxième place", 3: "troisième place"},
    "nl": {1: "eerste plaats", 2: "tweede plaats", 3: "derde plaats"},
}

# str.format templates per language. Keys must be identical across languages;
# English is the fallback for any missing language or key.
_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "game_start": "Let's play Beatify! {rounds} rounds, {difficulty} difficulty.",
        "winner_single": "And the winner is... {name} with {points} points!",
        "winner_tie": "It's a tie between {names} with {points} points!",
        "round_start": "Round {round} — get ready!",
        "countdown": "Three, two, one — go!",
        "time_up": "Time's up!",
        "player_join": "{name} has joined the game!",
        "player_reconnect": "Welcome back, {name}!",
        "last_round": "This is the final round!",
        "rematch": "Rematch! Get ready!",
        "intro_round": "Intro round — quick, you only get the opening seconds!",
        "steal_used": "{stealer} stole the answer from {target}!",
        "answer": "The answer was {year}.",
        "exact": "{names} got it exactly right.",
        "closest": "{name} was closest.",
        "nobody": "Nobody got it this round.",
        "streak_milestone": "{name} is on a {streak}-song streak.",
        "streak_broken": "{name}'s streak ends at {previous}.",
        "bet_won": "{name} doubled their points.",
        "bet_lost": "{name} loses the bet.",
        "steal_unlocked": "{name} unlocked steal.",
        "tie_at_top": "It's a tie at the top.",
        "leader_change": "{name} just took the lead.",
    },
    "de": {
        "game_start": "Auf geht's mit Beatify! {rounds} Runden, Schwierigkeit {difficulty}.",
        "winner_single": "Und der Sieger ist... {name} mit {points} Punkten!",
        "winner_tie": "Gleichstand zwischen {names} mit je {points} Punkten!",
        "round_start": "Runde {round} — macht euch bereit!",
        "countdown": "Drei, zwei, eins — los!",
        "time_up": "Zeit ist um!",
        "player_join": "{name} ist jetzt im Spiel dabei!",
        "player_reconnect": "Willkommen zurück, {name}!",
        "last_round": "Das ist die letzte Runde!",
        "rematch": "Revanche! Macht euch bereit!",
        "intro_round": "Intro-Runde — schnell, ihr hört nur die ersten Sekunden!",
        "steal_used": "{stealer} hat {target} die Antwort geklaut!",
        "answer": "Die Antwort war {year}.",
        "exact": "Goldrichtig: {names}.",
        "closest": "{name} war am nächsten dran.",
        "nobody": "Diese Runde hatte niemand richtig.",
        "streak_milestone": "{name} ist auf einer Serie von {streak} Songs!",
        "streak_broken": "{name}s Serie endet bei {previous}.",
        "bet_won": "{name} hat die Punkte verdoppelt.",
        "bet_lost": "{name} verliert die Wette.",
        "steal_unlocked": "{name} hat Klauen freigeschaltet.",
        "tie_at_top": "Gleichstand an der Spitze.",
        "leader_change": "{name} geht in Führung!",
    },
    "es": {
        "game_start": "¡A jugar a Beatify! {rounds} rondas, dificultad {difficulty}.",
        "winner_single": "Y el ganador es... ¡{name} con {points} puntos!",
        "winner_tie": "¡Empate entre {names} con {points} puntos!",
        "round_start": "Ronda {round}: ¡preparados!",
        "countdown": "Tres, dos, uno... ¡ya!",
        "time_up": "¡Se acabó el tiempo!",
        "player_join": "¡{name} entra en juego!",
        "player_reconnect": "¡Bienvenido de nuevo, {name}!",
        "last_round": "¡Esta es la ronda final!",
        "rematch": "¡Revancha! ¡Preparados!",
        "intro_round": "¡Ronda intro! Rápido, ¡solo suenan los primeros segundos!",
        "steal_used": "¡{stealer} le robó la respuesta a {target}!",
        "answer": "La respuesta era {year}.",
        "exact": "{names}: ¡respuesta exacta!",
        "closest": "{name} fue quien más se acercó.",
        "nobody": "Nadie acertó esta ronda.",
        "streak_milestone": "{name} lleva una racha de {streak} canciones.",
        "streak_broken": "La racha de {name} se corta en {previous}.",
        "bet_won": "{name} dobla sus puntos.",
        "bet_lost": "{name} pierde la apuesta.",
        "steal_unlocked": "{name} desbloquea el robo.",
        "tie_at_top": "¡Empate en la cima!",
        "leader_change": "¡{name} se pone en cabeza!",
    },
    "fr": {
        "game_start": "On joue à Beatify ! {rounds} manches, difficulté {difficulty}.",
        "winner_single": "Et le gagnant est... {name} avec {points} points !",
        "winner_tie": "Égalité entre {names} avec {points} points !",
        "round_start": "Manche {round} — préparez-vous !",
        "countdown": "Trois, deux, un — partez !",
        "time_up": "Temps écoulé !",
        "player_join": "{name} rejoint la partie !",
        "player_reconnect": "Bon retour, {name} !",
        "last_round": "C'est la dernière manche !",
        "rematch": "Revanche ! Préparez-vous !",
        "intro_round": "Manche intro — vite, vous n'avez que les premières secondes !",
        "steal_used": "{stealer} a volé la réponse de {target} !",
        "answer": "La réponse était {year}.",
        "exact": "{names}, dans le mille !",
        "closest": "{name} était le plus proche.",
        "nobody": "Personne n'a trouvé cette manche.",
        "streak_milestone": "{name} enchaîne {streak} titres d'affilée.",
        "streak_broken": "La série de {name} s'arrête à {previous}.",
        "bet_won": "{name} double ses points.",
        "bet_lost": "{name} perd son pari.",
        "steal_unlocked": "{name} débloque le vol.",
        "tie_at_top": "Égalité en tête.",
        "leader_change": "{name} prend la tête !",
    },
    "nl": {
        "game_start": "We spelen Beatify! {rounds} rondes, moeilijkheid {difficulty}.",
        "winner_single": "En de winnaar is... {name} met {points} punten!",
        "winner_tie": "Gelijkspel tussen {names} met {points} punten!",
        "round_start": "Ronde {round} — maak je klaar!",
        "countdown": "Drie, twee, een — go!",
        "time_up": "De tijd is om!",
        "player_join": "{name} doet mee!",
        "player_reconnect": "Welkom terug, {name}!",
        "last_round": "Dit is de laatste ronde!",
        "rematch": "Revanche! Maak je klaar!",
        "intro_round": "Introronde — snel, je hoort alleen de eerste seconden!",
        "steal_used": "{stealer} jatte het antwoord van {target}!",
        "answer": "Het antwoord was {year}.",
        "exact": "{names} had het precies goed.",
        "closest": "{name} zat er het dichtst bij.",
        "nobody": "Niemand had het deze ronde goed.",
        "streak_milestone": "{name} heeft een reeks van {streak} nummers.",
        "streak_broken": "De reeks van {name} eindigt op {previous}.",
        "bet_won": "{name} verdubbelt de punten.",
        "bet_lost": "{name} verliest de weddenschap.",
        "steal_unlocked": "{name} heeft jatten vrijgespeeld.",
        "tie_at_top": "Het is gelijkspel aan kop.",
        "leader_change": "{name} neemt de leiding.",
    },
}


def normalize_language(language: str | None) -> str:
    """Return a language we have phrases for, defaulting to English."""
    if language and language in _PHRASES:
        return language
    return DEFAULT_LANGUAGE


def phrase(language: str | None, key: str, **kwargs: object) -> str:
    """Render a localized announcement phrase, falling back to English.

    Falls back to the English template when the language/key is missing, and
    again if a (translated) template fails to format — a malformed string must
    never break a live game.
    """
    lang = normalize_language(language)
    template = _PHRASES.get(lang, {}).get(key)
    if template is None:
        template = _PHRASES[DEFAULT_LANGUAGE][key]
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return _PHRASES[DEFAULT_LANGUAGE][key].format(**kwargs)


def join_names(language: str | None, names: list[str]) -> str:
    """Join names for speech ("Marco and Anna") using the language's word.

    Mirrors the original ``" and ".join(...)`` so English output is unchanged.
    """
    lang = normalize_language(language)
    and_word = _AND.get(lang, _AND[DEFAULT_LANGUAGE])
    return f" {and_word} ".join(names)


def difficulty_label(language: str | None, difficulty: str) -> str:
    """Localized label for a difficulty value (easy/normal/hard)."""
    lang = normalize_language(language)
    table = _DIFFICULTY.get(lang, _DIFFICULTY[DEFAULT_LANGUAGE])
    en = _DIFFICULTY[DEFAULT_LANGUAGE]
    return table.get(difficulty) or en.get(difficulty, difficulty)


def place_label(language: str | None, place: int) -> str:
    """Localized podium label for a 1-based place (1/2/3)."""
    lang = normalize_language(language)
    table = _PLACE.get(lang, _PLACE[DEFAULT_LANGUAGE])
    en = _PLACE[DEFAULT_LANGUAGE]
    return table.get(place) or en.get(place, str(place))


def spoken_number(language: str | None, value: int, kind: str = "cardinal") -> str:
    """Render a number as words so neural TTS engines don't swallow bare digits.

    Some engines (observed with ElevenLabs) read digits cleanly in English but
    drop a bare multi-digit number in other languages. Spelling it out in the
    game language avoids relying on the engine's number normalization.

    English keeps digits — engines read them fine and the English announcement
    strings are pinned. ``kind`` is ``"year"`` for a natural year reading (e.g.
    "neunzehnhunderteinundneunzig") or ``"cardinal"`` for counts. Falls back to
    digits if num2words is unavailable or errors, so an announcement is never
    lost over a number.
    """
    lang = normalize_language(language)
    if lang == DEFAULT_LANGUAGE:
        return str(value)
    try:
        from num2words import num2words  # noqa: PLC0415

        return num2words(value, lang=lang, to=kind)
    except Exception:  # noqa: BLE001 — never let a number break the announcement
        return str(value)
