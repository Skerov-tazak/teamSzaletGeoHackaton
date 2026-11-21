"""
Shared domain helpers for the assistant's tools and orchestrator (no LLM here).

* crop names (platform CropClass code -> Polish / RAG crop id)
* PROVISIONAL risk levels from the engine's 0-1 score (cut-offs are still open for Bartek/Kuba,
  docs/database.md "Open questions"); one place to change them
* trend of a risk series, computed in code
* threat resolution: free text (inflected, colloquial) -> core.Threat, keyed by Threat.code,
  matched by name + aliases with the same folding/prefix approach as rag.get_risk_conditions
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

# --- crops ------------------------------------------------------------------------------------
CROP_PL = {1110: "pszenica", 1130: "kukurydza"}           # CropClass.code -> Polish name (also the RAG crop id)
CROP_PL_FULL = {1110: "pszenica ozima", 1130: "kukurydza"}


def crop_pl(code: int | None) -> str:
    return CROP_PL.get(code or -1, "inna uprawa")


# --- risk levels (PROVISIONAL) ----------------------------------------------------------------
# (upper bound exclusive, level number, Polish label). Proposed in INTERFACE_PROPOSALS.md.
LEVELS = [(0.33, 1, "niskie"), (0.66, 2, "średnie"), (1.0001, 3, "wysokie")]
RELEVANT_SCORE = LEVELS[0][0]  # below this a threat is "not relevant now"


def level(score: float | None) -> tuple[int, str]:
    if score is None:
        return 0, "brak danych"
    for upper, n, label in LEVELS:
        if score < upper:
            return n, label
    return 3, "wysokie"


def trend(scores: list[float], min_delta: float = 0.05) -> str:
    """'rośnie' / 'maleje' / 'stały' from the last up-to-4 values (oldest first)."""
    s = [x for x in scores if x is not None][-4:]
    if len(s) < 2:
        return "brak danych"
    delta = s[-1] - s[0]
    return "rośnie" if delta > min_delta else "maleje" if delta < -min_delta else "stały"


def rising_days(scores: list[float]) -> int:
    """How many consecutive days (ending with the last value) the score went up."""
    n = 0
    for a, b in zip(reversed(scores[:-1]), reversed(scores[1:])):
        if b > a:
            n += 1
        else:
            break
    return n


# --- text folding -----------------------------------------------------------------------------
def fold(text: str) -> str:
    """lowercase, no Polish diacritics, letters/digits/spaces only."""
    t = text.lower().replace("ł", "l")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def stem5(text: str) -> str:
    return " ".join(w[:5] for w in text.split())


# --- threat aliases ---------------------------------------------------------------------------
# key: a fragment of the official Polish name (folded); value: colloquial / inflected forms.
# Matched against Threat.name, so it works whatever codes the platform's import uses.
ALIASES: dict[str, list[str]] = {
    "septorioza paskowana": ["septorioza", "septoria", "septoriozy", "paski na lisciach", "plamy z czarnymi kropkami",
                             "brunatne plamy z czarnymi kropkami"],
    "septorioza plew": ["septorioza plew", "plamy na plewach"],
    "rdza brunatna": ["rdza brunatna", "rdzy brunatnej", "rdzawe plamy", "pomaranczowe kropki", "rdzawy nalot"],
    "rdza zolta": ["rdza zolta", "rdzy zoltej", "zolte paski", "zolte smugi"],
    "rdza zdzblowa": ["rdza zdzblowa", "rdzy zdzblowej"],
    "maczniak prawdziwy": ["maczniak", "bialy nalot", "maczysty nalot", "bialy puszysty nalot"],
    "fuzarioza klosow": ["fuzarioza klosow", "bielenie klosow", "rozowy nalot na klosach", "bielejace klosy"],
    "lamliwosc zdzbla": ["lamliwosc", "plamy oczkowe", "lamiace sie zdzbla"],
    "plesn sniegowa": ["plesn sniegowa", "plesni sniegowej", "nalot po zimie"],
    "brunatna plamistosc lisci": ["brunatna plamistosc", "dtr"],
    "czern zboz": ["czern", "czarny nalot na klosach"],
    "sporysz": ["sporysz", "przetrwalniki na klosach"],
    "zgorzel siewek": ["zgorzel siewek", "gnijace siewki", "zamierajace siewki"],
    "zgorzel podstawy zdzbla": ["zgorzel podstawy", "czernienie podstawy zdzbla"],
    "fuzarioza kolb": ["fuzarioza kolb", "plesniejace kolby", "rozowa plesn na kolbach"],
    "fuzarioza lodyg": ["fuzarioza lodyg", "gnicie lodyg", "lamiace sie lodygi"],
    "omacnica": ["omacnica", "omacnicy", "gasienice w lodygach", "zlamane wiechy", "wygryzione lodygi"],
    "stonka kukurydziana": ["stonka", "stonki", "larwy na korzeniach"],
    "ploniarka": ["ploniarka", "ploniarki", "zdeformowane liscie siewek"],
    "mszyce": ["mszyce", "mszyca", "mszyc", "kolonie owadow na lisciach"],
    "drutowce": ["drutowce", "drutowcow", "wygryzione kielki"],
    "rdza kukurydzy": ["rdza kukurydzy", "rdza na kukurydzy"],
    "drobna plamistosc": ["drobna plamistosc"],
    "zolta plamistosc": ["zolta plamistosc"],
    "szalonych wiech": ["szalone wiechy", "szalonych wiech"],
    "glownia guzowata": ["glownia", "narosla na kolbach", "guzy na kolbach"],
}


@dataclass
class ThreatMatch:
    code: str
    name: str
    crop_code: int
    score: float
    matched: str


def resolve_threats(text: str, crop_code: int | None = None, limit: int = 3, min_score: float = 86) -> list[ThreatMatch]:
    """Threats mentioned in `text` (best first). Uses core.Threat (code, name) + ALIASES."""
    from core.models import Threat

    q = fold(text)
    if not q:
        return []
    qs = Threat.objects.all()
    if crop_code:
        qs = qs.filter(crop_id=crop_code)
    out: list[ThreatMatch] = []
    for t in qs.only("code", "name", "crop_id"):
        name = fold(re.sub(r"\(.*?\)", "", t.name))
        forms = [name] + [a for key, al in ALIASES.items() if key in name for a in al]
        best, how = 0.0, ""
        for f in forms:
            if not f:
                continue
            if re.search(rf"\b{re.escape(f)}\b", q):
                sc = 100 + len(f) / 100  # exact phrase; longer phrase wins
            else:
                sc = fuzz.partial_ratio(stem5(f), stem5(q)) if len(f) >= 6 else 0
            if sc > best:
                best, how = sc, f
        if best >= min_score:
            out.append(ThreatMatch(t.code, t.name, t.crop_id, round(best, 1), how))
    out.sort(key=lambda m: -m.score)
    return out[:limit]


def threat_by_code_or_name(value: str, crop_code: int | None = None):
    """A Threat from its code, exact name, or free text; None if nothing matches."""
    from core.models import Threat

    qs = Threat.objects.all()
    if crop_code:
        qs = qs.filter(crop_id=crop_code)
    t = qs.filter(code=value).first() or qs.filter(name__iexact=value).first()
    if t:
        return t
    m = resolve_threats(value, crop_code, limit=1)
    return qs.filter(code=m[0].code).first() if m else None
