"""
Question type without an LLM: keyword rules on folded text (lowercase, no Polish letters), plus
detection of field names, crop and threats. Priority:

  pending draft + yes/no -> potwierdzenie
  "pokaż / wykres / trend / jak się zmieniało" -> wykres
  "widzę / zauważyłem / pojawiły się / znalazłem / zapisz obserwację" -> obserwacja
  "wszystkie pola / moich polach / co najpilniejsze / gospodarstwo" (or >= 2 fields compared, or "raport"
      with no field selected or named) -> podsumowanie_farmy
  complex (>= 2 fields, several threats, explicit date ranges) and ASSISTANT_AGENT_MODE=1 -> zlozone
  field reference ("to pole", a field name, a selected field) + risk / what-to-do words -> pytanie_o_pole
  nothing agricultural -> poza_zakresem
  otherwise -> pytanie_ogolne
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from assistant import domain

CONFIRM_YES = {"tak", "zapisz", "potwierdzam", "ok", "okej", "zgadza sie", "dobrze", "jasne", "tak zapisz", "zapisuj"}
CONFIRM_NO = {"nie", "anuluj", "nie zapisuj", "rezygnuje", "odrzuc", "stop", "nie trzeba"}

CHART = [r"\bpokaz", r"\bwykres", r"\btrend", r"jak sie zmienial", r"\bprzebieg", r"\bnarysuj", r"\bzobrazuj"]
OBSERVATION = [r"\bwidze\b", r"zauwazyl", r"pojawil\w* sie", r"znalazl", r"zapisz obserwacj", r"\bdostrzegl",
               r"na polu (sa|jest|maja)", r"mam na polu", r"zaobserwowal", r"odnotuj",
               r"oprysk\w*al\w*", r"\bpryskal", r"wykonal\w* zabieg", r"\b(zasial|posial|sialem|sialam|wysial)",
               r"\b(przeszedl|przeszlam|obszedl|obeszlam|sprawdzil)\w*", r"\bgrad\b", r"wylegl|polegl", r"zalal\w*|podtopi",
               r"nie oral|bez orki"]
OBSERVATION_STATEMENT = [r"\bsasiad\w*"]   # only when it is a statement, not a question
FARM = [r"wszystkie pola", r"wszystkich pol", r"najpilniejsz", r"gospodarstw", r"ktore pole", r"na ktorym polu",
        r"podsumuj", r"przeglad pol", r"cala farm", r"wszystkich uprawach",
        r"\bmoich pol", r"\bmoje pola\b", r"\bmoich upraw", r"\bmoje uprawy", r"\bnaszych pol", r"\bnasze pola\b",
        r"\bw gospodarstwie"]
FARM_IF_NO_FIELD = [r"\braport", r"\bpodsumowani", r"\bzestawieni"]   # "raport ryzyk" with no field selected or named
FIELD_REF = [r"\bto pole", r"\btym polu", r"\btego pola", r"\bmoje pole", r"\bmoim polu", r"\bmojego pola",
             r"\bna polu\b", r"\bpola\b", r"\bpole\b"]
RISK_INTENT = [r"ryzyk", r"zagroz", r"dlaczego", r"\bco (\w+ ){0,3}(robic|zrobic)",
               r"czy grozi", r"\bstan\b", r"niebezpiecz", r"\bgrozi", r"co mu dolega", r"co sie dzieje", r"\bjak (jest|wyglada)",
               r"\balarm", r"\bostrzez", r"czy (musze|trzeba|nalezy)"]
AGRO = [r"choro", r"szkodni", r"\bpol[aeiuo]?\b", r"upraw", r"pszen", r"kukurydz", r"zboz", r"ryzyk", r"opryskiw",
        r"nawo", r"\bsiew", r"\bplon", r"lisc", r"klos", r"metodyk", r"ochron", r"chwast", r"grzyb", r"pogod",
        r"deszcz", r"opad", r"temperatur", r"wilgot", r"bbch", r"odmian", r"gleb", r"termin", r"\bprog",
        r"lustrac", r"objaw", r"plam", r"mszyc", r"rdz", r"septori", r"fuzari", r"maczni", r"omacni", r"herbicyd",
        r"fungicyd", r"insektycyd", r"srodek", r"srodk", r"\bdawk", r"hektar", r"/ha\b", r"zgnili", r"zgorzel",
        r"agrotechn", r"plodozmian", r"przedplon", r"\bph\b", r"susz", r"przymroz", r"gospodarstw", r"zagroz",
        r"obserwac", r"wykres", r"trend", r"\bzbior", r"ziarn", r"kolb", r"lodyg", r"korzen", r"siewk"]
OFF_TOPIC = [r"przepis na", r"kto wygral", r"napisz wiersz", r"bitcoin", r"\bfilm", r"pilk\w* noz", r"\bpolityk",
             r"opowiedz (mi )?dowcip", r"\bkawal\b"]
DATE_RANGE = [r"\bod \d{1,2}[ .]\w+ do\b", r"\bod (stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia)",
              r"\bw (marcu|kwietniu|maju|czerwcu|lipcu|sierpniu)\b", r"\bcaly sezon", r"\bod poczatku sezonu"]
COMPARE = [r"porownaj", r"porownani", r"roznic", r"\bvs\b", r"\bczy bardziej"]
FOLLOW_UP = [r"^a\b", r"\btam\b", r"\btego\b", r"\btym\b", r"\bto\b", r"\bzmniejsz", r"\bograniczyc",
             r"\bzapobiec", r"\bpomoc", r"\bco dalej", r"\bkiedy\b"]
CROP_WORDS = {"pszenic": "pszenica", "kukurydz": "kukurydza", "zboz": "zboza"}


@dataclass
class Route:
    type: str
    field_id: int | None = None
    field_ids: list[int] = field(default_factory=list)
    crop: str | None = None
    threats: list[str] = field(default_factory=list)   # Threat codes
    reason: str = ""
    field_source: str = ""                             # selected | named | ""


def _any(patterns, text) -> str | None:
    for p in patterns:
        if re.search(p, text):
            return p
    return None


def find_fields(text_f: str) -> list[tuple[int, str]]:
    """Fields whose (folded) name appears in the text: exact phrase, or all name words by 4-letter prefix."""
    from core.models import Field
    hits = []
    words = text_f.split()
    for fid, name in Field.objects.values_list("id", "name"):
        nf = domain.fold(name)
        if re.search(rf"\b{re.escape(nf)}\b", text_f):
            hits.append((fid, name))
            continue
        nw = [w for w in nf.split() if w not in ("pole", "pola", "polu", "przy", "na", "w")]
        if nw and all(any(t.startswith(w[:4]) for t in words) for w in nw):
            hits.append((fid, name))
    return hits


def route(message: str, selected_field=None, state=None) -> Route:
    t = domain.fold(message)
    agent = os.getenv("ASSISTANT_AGENT_MODE", "0") == "1"
    named = find_fields(t)
    crop = next((v for k, v in CROP_WORDS.items() if k in t), None)
    crop_code = {"pszenica": 1110, "kukurydza": 1130}.get(crop or "")
    if crop_code is None and len(named) == 1:
        from core.models import Field
        crop_code = Field.objects.filter(pk=named[0][0]).values_list("crop_id", flat=True).first()
    if crop_code is None and selected_field is not None:
        crop_code = selected_field.crop_id
    if crop is None and crop_code:
        crop = domain.crop_pl(crop_code)
    matches = domain.resolve_threats(message, crop_code)
    threats = [m.code for m in matches]
    if crop is None and matches:  # "septorioza paskowana" alone -> wheat
        crop_code = crop_code or matches[0].crop_code
        crop = domain.crop_pl(crop_code)
    field_id, field_source = None, ""
    if len(named) == 1:
        field_id, field_source = named[0][0], "named"
    elif selected_field is not None:
        field_id, field_source = selected_field.id, "selected"
    elif state is not None and state.data.get("last_field_id") and not named and (
            _any(RISK_INTENT, t) or _any(FOLLOW_UP, t) or _any(CHART, t)):
        # a follow-up ("co mogę zrobić?", "a dlaczego?") continues with the field of the previous answer
        from core.models import Field
        last = Field.objects.filter(pk=state.data["last_field_id"]).first()
        if last is not None:
            field_id, field_source = last.id, "conversation"
            if crop is None:
                crop = domain.crop_pl(last.crop_id)
                if not threats:
                    threats = [m.code for m in domain.resolve_threats(message, last.crop_id)]
    base = dict(field_id=field_id, field_ids=[f for f, _ in named], crop=crop, threats=threats,
                field_source=field_source)

    # 1. pending observation draft
    if state is not None and state.draft:
        if t in CONFIRM_YES or t.split(" ")[0] in {"tak", "zapisz", "potwierdzam"}:
            return Route("potwierdzenie", reason="draft pending + yes", **base)
        if t in CONFIRM_NO or t.split(" ")[0] in {"nie", "anuluj"}:
            return Route("potwierdzenie", reason="draft pending + no", **base)
    # 2. chart
    if p := _any(CHART, t):
        return Route("wykres", reason=f"chart word {p}", **base)
    # 3. observation
    if p := _any(OBSERVATION, t):
        return Route("obserwacja", reason=f"observation word {p}", **base)
    if not message.strip().endswith("?") and (p := _any(OBSERVATION_STATEMENT, t)):
        return Route("obserwacja", reason=f"observation statement {p}", **base)
    # 4. farm overview
    complex_q = len(named) >= 2 or (len(threats) >= 2 and _any(COMPARE, t)) or bool(_any(DATE_RANGE, t))
    if agent and complex_q:
        return Route("zlozone", reason="complex question (agent mode)", **base)
    if p := (_any(FARM, t) or (len(named) >= 2 and "compare") or (field_id is None and _any(FARM_IF_NO_FIELD, t))):
        return Route("podsumowanie_farmy", reason=f"farm word {p}", **base)
    # 5. question about a field
    field_ref = field_id is not None or bool(_any(FIELD_REF, t))
    if field_ref and (p := _any(RISK_INTENT, t)):
        return Route("pytanie_o_pole", reason=f"field ref ({field_source or 'phrase'}) + intent {p}", **base)
    # 6. out of scope
    if _any(OFF_TOPIC, t) or not (_any(AGRO, t) or named or threats):
        return Route("poza_zakresem", reason="no agricultural words", **base)
    return Route("pytanie_ogolne", reason="default", **base)
