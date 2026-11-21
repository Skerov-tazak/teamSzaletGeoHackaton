"""
The threat catalogue: every rule the engine applies, with its numbers.

Each entry is keyed by the Threat.code the platform stores (refer to threats by code, never by id).
Numbers listed in `assumptions` are the team's own calibration; the rest follow the integrated pest
management guides. The rules are stored here; no document is read at run time.

Kinds of rules (see engine/scoring.py):
- "infection_hours": hours with temperature in range and wet / humid air, summed over a trailing
  window, during a susceptible growth stage.
- "soil_days", "snow_days", "flood": day counts of a soil / snow / waterlogging condition.
- "pest_activity": activity window (degree days or calendar) x local pressure (crop history).
"""

from __future__ import annotations

from dataclasses import dataclass, field

WHEAT = 1110
MAIZE = 1130



@dataclass(frozen=True)
class Rule:
    code: str
    crop: int
    name_pl: str
    name_en: str
    category: str  # fungal / bacterial / viral / pest (Threat.Category)
    kind: str
    # growth stage window (BBCH): full weight inside [stage_min, stage_max], ramps to 0 over `stage_ramp`
    stage_min: int = 0
    stage_max: int = 99
    stage_ramp: int = 5
    # infection_hours
    temp_min: float | None = None
    temp_max: float | None = None
    moisture: str = "wet"  # wet: RH >= 90 % or dew point gap <= 2 °C or rain; humid: RH >= 80 %; mild: 50 <= RH < 95 % and no rain
    window_days: int = 7
    hours_low: float = 5.0   # hours in the window at which the weather starts to count
    hours_high: float = 20.0  # hours in the window at which the weather alone gives score 1
    needs_rain_days: int = 0  # rain-splash diseases: days with >= 1 mm in the window
    # pest_activity: degree days base 10 °C since 1 January
    dd10_start: float | None = None
    dd10_peak: tuple[float, float] | None = None
    dd10_end: float | None = None
    # multipliers from crop history / soil (applied inside the rule, explained as drivers)
    after_maize: float = 1.0          # previous crop was maize
    cereal_after_cereal: float = 1.0  # previous crop was a cereal (wheat, barley, other cereals)
    maize_monoculture: float = 1.0    # maize also last year
    heavy_soil: float = 1.0           # clay >= 30 %
    severity: float = 0.1             # potential yield loss if the threat materialises, 0-1 (assumption)
    action_threshold: str = ""        # monitoring / economic threshold
    stage_thresholds: tuple = ()      # ((bbch_from, bbch_to, text), ...) threshold for the current stage
    warm_ramp: tuple | None = None    # pests: activity x (0.5 + 0.5 x ramp(7-day mean temperature, lo, hi))
    notes: tuple[str, ...] = ()
    assumptions: dict = field(default_factory=dict)


RULES: dict[str, Rule] = {}


def _add(rule: Rule) -> None:
    RULES[rule.code] = rule


# --- Wheat ---------------------------------------------------------------------------------------

_add(Rule(
    code="wheat.fusarium_head_blight", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="fuzarioza kłosów", name_en="Fusarium head blight",
    stage_min=61, stage_max=69, stage_ramp=6, temp_min=15, temp_max=25, moisture="wet",
    window_days=5, hours_low=4, hours_high=16, needs_rain_days=1, after_maize=1.5, severity=0.15,
    action_threshold="Infection happens at flowering (BBCH 61-69); treatment only works preventively around flowering.",
    notes=("Maize residue (previous crop maize) and reduced tillage raise the risk.",
           "Species differ: F. graminearum 16-18 °C, F. culmorum 20-22 °C, F. avenaceum 5-10 °C with dew, fog or 2-5 mm rain.",
           "Each 1 % of infected ears can add about 0.3 mg/kg DON (mycotoxin) to the grain.",
           "Fields with head blight in past seasons and cereal monocultures are at higher risk."),
    assumptions={"hours_low": 4, "hours_high": 16, "window_days": 5, "after_maize": 1.5},
))
_add(Rule(
    code="wheat.septoria_leaf_blotch", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="septorioza paskowana liści pszenicy", name_en="Septoria leaf blotch",
    stage_min=30, stage_max=59, temp_min=4, temp_max=18, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, needs_rain_days=2, cereal_after_cereal=1.2, severity=0.15,
    stage_thresholds=((21, 29, "Tillering: 30-50 % of leaves with first symptoms or 1 % of leaves with fruiting bodies"), (30, 39, "Stem elongation: 10-20 % of the area of the leaf below the flag leaf or 1 % of leaves with fruiting bodies"), (51, 59, "Heading: 5-10 % of the flag leaf area or 1 % of leaves with fruiting bodies")),
    action_threshold="Tillering: 30-50 % of leaves with first symptoms, or 1 % of leaves with fruiting bodies.",
    notes=("Spread by rain splash: rain days in the window are required.",),
    assumptions={"hours_low": 15, "hours_high": 50, "window_days": 10, "needs_rain_days": 2},
))
_add(Rule(
    code="wheat.brown_rust", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="rdza brunatna pszenicy", name_en="Brown (leaf) rust",
    stage_min=30, stage_max=75, temp_min=15, temp_max=18, moisture="wet",
    window_days=7, hours_low=3, hours_high=12, severity=0.10,
    stage_thresholds=((21, 29, "Tillering: 10-15 % of leaves with first symptoms"), (30, 39, "Stem elongation: 10 % of stems with first symptoms"), (51, 59, "Heading: first symptoms on the flag leaf or the leaf below it")),
    action_threshold="Tillering: 10-15 % of leaves with first symptoms; stem elongation: 10 % of stems.",
    notes=("Source condition: periodic daily rise of air humidity (dew); counted as wet hours at 15-18 °C.",),
    assumptions={"hours_low": 3, "hours_high": 12},
))
_add(Rule(
    code="wheat.powdery_mildew", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="mączniak prawdziwy zbóż i traw", name_en="Powdery mildew",
    stage_min=21, stage_max=59, temp_min=5, temp_max=30, moisture="mild",
    window_days=7, hours_low=90, hours_high=150, severity=0.08,
    stage_thresholds=((21, 29, "Tillering: 50-70 % of plants with first symptoms"), (30, 39, "Stem elongation: 10 % of plants with first symptoms"), (51, 59, "Heading: first symptoms on the flag leaf, the leaf below it or the ear")),
    action_threshold="Tillering: 50-70 % of plants with first symptoms.",
    notes=("Warm, sunny weather with humid but not rainy air favours spore production.",
           "Excess nitrogen and a dense canopy raise the risk (not in our data)."),
    assumptions={"hours_low": 90, "hours_high": 150},
))
_add(Rule(
    code="wheat.yellow_rust", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="rdza żółta", name_en="Yellow (stripe) rust",
    stage_min=29, stage_max=69, temp_min=10, temp_max=15, moisture="wet",
    window_days=7, hours_low=5, hours_high=20, severity=0.15,
    stage_thresholds=((21, 29, "Tillering: 30 % of plants with first symptoms"), (30, 39, "Stem elongation: 10 % of the area of the leaf below the flag leaf"), (51, 59, "Heading: first symptoms on the flag leaf or the leaf below it")),
    action_threshold="Tillering: 30 % of plants with first symptoms; stem elongation: 10 % of the 2nd leaf area.",
    notes=("New pathotypes (Warrior, Kranich) also develop at 10-28 °C in dry, warm weather.",),
    assumptions={"hours_low": 5, "hours_high": 20},
))
_add(Rule(
    code="wheat.tan_spot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="brunatna plamistość liści", name_en="Tan spot (DTR)",
    stage_min=37, stage_max=75, temp_min=18, temp_max=28, moisture="wet",
    window_days=7, hours_low=5, hours_high=20, cereal_after_cereal=1.3, severity=0.10,
    stage_thresholds=((21, 29, "Tillering: 10-15 % of plants with first symptoms"), (30, 39, "Stem elongation: 5 % of leaves with first symptoms"), (51, 59, "Heading: 5 % of leaves with first symptoms")),
    action_threshold="Tillering: 10-15 % of plants with first symptoms; stem elongation: 5 % of leaves.",
    notes=("Needs wet leaves to infect; survives on wheat residue (wheat after wheat raises the risk).",),
    assumptions={"hours_low": 5, "hours_high": 20, "cereal_after_cereal": 1.3},
))
_add(Rule(
    code="wheat.take_all", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="zgorzel podstawy źdźbła", name_en="Take-all",
    stage_min=21, stage_max=39, temp_min=12, temp_max=20, moisture="humid",
    window_days=10, hours_low=40, hours_high=120, cereal_after_cereal=1.5, severity=0.15,
    action_threshold="No fungicide during the season; prevention by rotation and seed treatment.",
    notes=("Cereal after cereal is the main driver: a 3-4 year break from cereals strongly reduces it.",),
    assumptions={"hours_low": 40, "hours_high": 120, "cereal_after_cereal": 1.5},
))
_add(Rule(
    code="wheat.snow_mould", crop=WHEAT, category="fungal", kind="snow_days",
    name_pl="pleśń śniegowa", name_en="Snow mould",
    stage_min=10, stage_max=30, temp_min=0, temp_max=5, window_days=21, hours_low=3, hours_high=14,
    severity=0.10,
    action_threshold="Seed treatment and autumn agronomy; no in-season treatment under snow.",
    notes=("Counted as days with 0-5 °C, snow cover and unfrozen soil.",),
    assumptions={"days_low": 3, "days_high": 14, "snow_depth_mm_we": 5},
))

# --- Maize ---------------------------------------------------------------------------------------
_add(Rule(
    code="maize.seedling_blight", crop=MAIZE, category="fungal", kind="soil_days",
    name_pl="zgorzel siewek", name_en="Seedling blight",
    stage_min=0, stage_max=14, stage_ramp=3, window_days=10, hours_low=2, hours_high=7, severity=0.08,
    action_threshold="Prevention by seed treatment; highest monitoring priority at the start of the season.",
    notes=("Counted as days with cold (< 12 °C) and wet (>= 0.30 m³/m³) topsoil (0-7 cm).",),
    assumptions={"soil_temp_max_c": 12, "soil_moisture_min": 0.30, "days_low": 2, "days_high": 7},
))
_add(Rule(
    code="maize.fusarium_ear_rot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="fuzarioza kolb", name_en="Fusarium ear rot",
    stage_min=63, stage_max=89, stage_ramp=8, temp_min=15, temp_max=30, moisture="humid",
    window_days=14, hours_low=60, hours_high=180, maize_monoculture=1.3, severity=0.12,
    action_threshold="Timely harvest and shredding of residue are key (mycotoxins).",
    notes=("European corn borer damage and drought stress raise the risk; a wet autumn and late harvest raise mycotoxins.",),
    assumptions={"hours_low": 60, "hours_high": 180, "maize_monoculture": 1.3},
))
_add(Rule(
    code="maize.fusarium_stalk_rot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="fuzarioza łodyg", name_en="Fusarium stalk rot",
    stage_min=51, stage_max=89, stage_ramp=10, temp_min=18, temp_max=30, moisture="humid",
    window_days=14, hours_low=60, hours_high=180, maize_monoculture=1.3, severity=0.10,
    action_threshold="Rotation, residue management, balanced K fertilisation.",
    notes=("Drought stress weakens plants and raises susceptibility.",),
    assumptions={"hours_low": 60, "hours_high": 180},
))
_add(Rule(
    code="maize.crazy_top", crop=MAIZE, category="fungal", kind="flood",
    name_pl="choroba szalonych wiech", name_en="Crazy top",
    stage_min=0, stage_max=16, stage_ramp=3, window_days=14, hours_low=1, hours_high=3, heavy_soil=1.3,
    severity=0.05,
    action_threshold="Remove and destroy affected plants before spores are released.",
    notes=("Needs the field flooded for 24-48 h: counted as days with saturated topsoil or >= 30 mm rain.",),
    assumptions={"saturated_moisture": 0.40, "heavy_rain_mm": 30, "days_low": 1, "days_high": 3},
))
_add(Rule(
    code="maize.european_corn_borer", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="omacnica prosowianka", name_en="European corn borer",
    stage_min=30, stage_max=79, stage_ramp=10, dd10_start=150, dd10_peak=(420, 650), dd10_end=900,
    maize_monoculture=1.4, severity=0.10,
    action_threshold="Tasseling (BBCH 51-59): 6-8 egg masses per 100 plants, or 15 % plants damaged last year.",
    notes=("Moths fly from early/mid June, peak in the 1st-2nd ten days of July; eggs from the 2nd half of June, most in mid July; caterpillars hatch from mid June.",
           "Hot, dry summers shorten the flight (ends late July / early August), cool rainy ones extend it to the end of August.",
           "Local maize intensity also matters; we only know this field's own history."),
    assumptions={"dd10_start": 150, "dd10_peak": [420, 650], "dd10_end": 900, "base_pressure": 0.6, "maize_monoculture": 1.4},
))
_add(Rule(
    code="maize.western_corn_rootworm", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="stonka kukurydziana", name_en="Western corn rootworm",
    stage_min=14, stage_max=79, stage_ramp=5, dd10_start=150, dd10_peak=(250, 700), dd10_end=1000,
    severity=0.15,
    action_threshold="Monoculture fields: sample larvae weekly from 9 leaves to tasseling (BBCH 19-59).",
    notes=("Only a real threat in at least the second year of maize on the same field (eggs overwinter in the soil).",),
    assumptions={"dd10_start": 150, "dd10_peak": [250, 700], "dd10_end": 1000, "pressure_first_year_maize": 0.05},
))
_add(Rule(
    code="maize.aphids", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="mszyce", name_en="Aphids",
    stage_min=10, stage_max=85, stage_ramp=5, dd10_start=250, dd10_peak=(380, 900), dd10_end=1200,
    severity=0.03,
    action_threshold="From tasseling (BBCH 51): 300 aphids per plant. Also virus vectors.",
    notes=("Warm weather (7-day mean >= 18 °C) raises activity.",),
    assumptions={"dd10_start": 250, "dd10_peak": [380, 900], "dd10_end": 1200, "warm_mean_c": 18},
))
_add(Rule(
    code="maize.frit_fly", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="ploniarka zbożówka", name_en="Frit fly",
    stage_min=10, stage_max=14, stage_ramp=2, severity=0.05,
    action_threshold="Emergence to 4 leaves (BBCH 10-14): 15 % plants damaged last year.",
    notes=("Cool springs and nearby winter cereals raise the risk; counted as a cool 7-day mean (< 15 °C).",),
    assumptions={"cool_mean_c": 15},
))

# --- More wheat and maize threats ---------------------------------------------------------------
_add(Rule(
    code="wheat.eyespot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="łamliwość źdźbła zbóż", name_en="Eyespot",
    stage_min=21, stage_max=32, stage_ramp=4, temp_min=5, temp_max=15, moisture="humid",
    window_days=14, hours_low=60, hours_high=200, cereal_after_cereal=1.5, severity=0.15,
    action_threshold="From stem elongation to the first node (BBCH 30-31): 20-30 % of stems with symptoms.",
    notes=("High air and soil humidity at 5-15 °C; builds up in cereal monocultures.",),
    assumptions={"hours_low": 60, "hours_high": 200, "window_days": 14, "cereal_after_cereal": 1.5},
))
_add(Rule(
    code="wheat.fusarium_foot_rot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="fuzaryjna zgorzel podstawy źdźbła i korzeni", name_en="Fusarium foot and root rot",
    stage_min=21, stage_max=39, temp_min=5, temp_max=25, moisture="humid",
    window_days=14, hours_low=100, hours_high=250, cereal_after_cereal=1.3, after_maize=1.3, severity=0.12,
    action_threshold="No threshold; prevention by rotation, residue management and seed treatment.",
    notes=("Wet air and soil, or a dried-out soil, favour it.",),
    assumptions={"hours_low": 100, "hours_high": 250, "window_days": 14},
))
_add(Rule(
    code="wheat.glume_blotch", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="septorioza plew", name_en="Septoria glume blotch",
    stage_min=37, stage_max=75, temp_min=10, temp_max=20, moisture="wet",
    window_days=10, hours_low=12, hours_high=40, needs_rain_days=2, severity=0.10,
    stage_thresholds=((21, 29, "Tillering: 20 % of plants with first symptoms"), (30, 39, "Stem elongation: 20 % of the area of the leaf below the flag leaf or 1 % of leaves with fruiting bodies"), (51, 59, "Heading: 10 % of the leaf below the flag leaf, at full heading 1 % of the flag leaf")),
    action_threshold="See the stage thresholds.",
    notes=("Spread by rain splash onto leaves and ears.",),
    assumptions={"hours_low": 12, "hours_high": 40, "needs_rain_days": 2},
))
_add(Rule(
    code="wheat.barley_yellow_dwarf", crop=WHEAT, category="viral", kind="vector_days",
    name_pl="żółta karłowatość jęczmienia (wirus przenoszony przez mszyce)", name_en="Barley yellow dwarf (aphid-borne virus)",
    stage_min=10, stage_max=29, stage_ramp=3, window_days=60, hours_low=8, hours_high=30, severity=0.12,
    action_threshold="Aphids as virus vectors: watch for the first flights into the crop in autumn and in spring; yellow traps help. No cure once infected.",
    notes=("Counted as autumn days warm enough for aphids to fly (max >= 12 °C) since the crop emerged.",),
    assumptions={"aphid_flight_max_c": 12, "days_low": 8, "days_high": 30},
))
_add(Rule(
    code="wheat.aphids", crop=WHEAT, category="pest", kind="pest_activity",
    name_pl="mszyce (na kłosach)", name_en="Grain aphids",
    stage_min=51, stage_max=75, stage_ramp=4, dd10_start=0, dd10_peak=(0, 1e9), dd10_end=2e9, warm_ramp=(14, 20),
    severity=0.08,
    action_threshold="At or just after heading: 5 aphids per ear.",
    notes=("Warm weather speeds up aphid build-up.",),
    assumptions={"warm_mean_c": [14, 20]},
))
_add(Rule(
    code="wheat.cereal_leaf_beetle", crop=WHEAT, category="pest", kind="pest_activity",
    name_pl="skrzypionki", name_en="Cereal leaf beetle",
    stage_min=37, stage_max=59, stage_ramp=4, dd10_start=0, dd10_peak=(0, 1e9), dd10_end=2e9, warm_ramp=(12, 18),
    severity=0.10,
    action_threshold="When the flag leaf appears: 1-1.5 larvae per stem. One larva can destroy 10 % of the flag leaf, about 10 % yield.",
    assumptions={"warm_mean_c": [12, 18]},
))
_add(Rule(
    code="maize.northern_leaf_blight", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="żółta plamistość liści kukurydzy", name_en="Northern corn leaf blight",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=18, temp_max=27, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, maize_monoculture=1.3, severity=0.08,
    action_threshold="Inspect lower leaves; residue shredding and rotation limit it.",
    assumptions={"temp_range_c": [18, 27], "hours_low": 15, "hours_high": 50},
))
_add(Rule(
    code="maize.eyespot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="drobna plamistość liści kukurydzy", name_en="Maize eyespot (Kabatiella)",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=10, temp_max=20, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, maize_monoculture=1.3, severity=0.06,
    action_threshold="Inspect leaves after cool, rainy spells; residue shredding and rotation limit it.",
    assumptions={"temp_range_c": [10, 20], "hours_low": 20, "hours_high": 60},
))
_add(Rule(
    code="maize.common_rust", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="rdza kukurydzy", name_en="Common rust",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=16, temp_max=25, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, severity=0.05,
    action_threshold="Inspect leaves in warm, humid weather.",
    assumptions={"temp_range_c": [16, 25], "hours_low": 15, "hours_high": 50},
))


CEREALS = {1110, 1120, 1150}

# Last season's risk on the same field that carries over in residue / soil (same pathogen or pest).
# Fusarium spp. infect both maize and wheat, so a bad maize year raises next year's head blight.
CARRYOVER = {
    "wheat.fusarium_head_blight": ("wheat.fusarium_head_blight", "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "maize.fusarium_ear_rot": ("maize.fusarium_ear_rot", "maize.fusarium_stalk_rot", "wheat.fusarium_head_blight"),
    "maize.fusarium_stalk_rot": ("maize.fusarium_stalk_rot", "maize.fusarium_ear_rot", "wheat.fusarium_head_blight"),
    "wheat.septoria_leaf_blotch": ("wheat.septoria_leaf_blotch",),
    "wheat.tan_spot": ("wheat.tan_spot",),
    "wheat.take_all": ("wheat.take_all",),
    "maize.european_corn_borer": ("maize.european_corn_borer",),
}


def rules_for_crop(crop_code: int) -> list[Rule]:
    return [r for r in RULES.values() if r.crop == crop_code]
