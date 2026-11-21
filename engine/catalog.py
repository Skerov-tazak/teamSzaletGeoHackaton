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

from dataclasses import dataclass, field, replace

WHEAT = 1110
BARLEY = 1120
MAIZE = 1130
OTHER_CEREALS = 1150   # triticale, rye, oats (one class in the crop map)
POTATO = 1310
SUGAR_BEET = 1320
RAPESEED = 1430

CROP_NAMES = {WHEAT: "Wheat", BARLEY: "Barley", MAIZE: "Maize", OTHER_CEREALS: "Other cereals", POTATO: "Potatoes",
              SUGAR_BEET: "Sugar beet", RAPESEED: "Rapeseed"}



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
    same_crop: float = 1.0            # previous crop was the same crop (any crop)
    after_crops: tuple = ()           # ((crop code, multiplier, why), ...) previous crop raises the risk
    acid_soil: float = 1.0            # soil pH < 6.5
    rotation_hosts: tuple = ()        # pest_activity: host crops whose presence in the last `rotation_years` sets the pressure
    rotation_years: int = 3
    soil_temp: tuple = (None, 12.0)   # soil_days: topsoil temperature range (°C)
    soil_wet: float = 0.30            # soil_days: topsoil moisture at least (m³/m³)
    flight_c: float = 12.0            # vector_days: daily max temperature that lets the insect fly (°C)
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


# --- Other crops ------------------------------------------------------------------------------------
# Barley, other cereals (triticale, rye, oats), rapeseed, sugar beet and potatoes. Temperature and
# humidity ranges and thresholds follow the integrated protection guides for these crops; rapeseed has
# no guide in the package, so its numbers are general agronomy and listed under `assumptions`.


def _variant(code: str, new_code: str, crop: int, **changes) -> None:
    """A rule shared by several cereals: same biology, own code, crop and (optionally) numbers."""
    _add(replace(RULES[code], code=new_code, crop=crop, **changes))


# Barley (winter barley is the main form in the region)
_variant("wheat.powdery_mildew", "barley.powdery_mildew", BARLEY,
         stage_thresholds=((21, 29, "Tillering: 25-35 % of plants with first symptoms"), (30, 39, "Stem elongation: 10 % of stems with first symptoms")),
         action_threshold="Tillering: 25-35 % of plants with first symptoms; stem elongation: 10 % of stems.")
_variant("wheat.fusarium_head_blight", "barley.fusarium_head_blight", BARLEY, stage_min=55, stage_max=69, severity=0.10,
         notes=("Malting barley must be free of Fusarium; maize residue raises the risk.",))
_variant("wheat.eyespot", "barley.eyespot", BARLEY)
_variant("wheat.fusarium_foot_rot", "barley.fusarium_foot_rot", BARLEY)
_variant("wheat.take_all", "barley.take_all", BARLEY, severity=0.10)
_variant("wheat.snow_mould", "barley.snow_mould", BARLEY)
_variant("wheat.barley_yellow_dwarf", "barley.barley_yellow_dwarf", BARLEY, severity=0.18,
         action_threshold="Winter barley is the most exposed crop: aphids as vectors, about 5 weeks after emergence in autumn; first flights into the crop in spring.")
_variant("wheat.aphids", "barley.aphids", BARLEY, action_threshold="At or just after heading: 5 aphids per ear.")
_variant("wheat.cereal_leaf_beetle", "barley.cereal_leaf_beetle", BARLEY)
_add(Rule(
    code="barley.net_blotch", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="plamistość siatkowa jęczmienia", name_en="Net blotch",
    stage_min=21, stage_max=69, temp_min=15, temp_max=25, moisture="wet",
    window_days=7, hours_low=6, hours_high=24, cereal_after_cereal=1.3, severity=0.15,
    stage_thresholds=((21, 29, "Tillering: 15-20 % of the leaf area with symptoms"), (30, 39, "Stem elongation: 15-20 % of the leaf area with symptoms")),
    action_threshold="15-20 % of the leaf area with symptoms (tillering and stem elongation).",
    notes=("Survives on infected seed, volunteers and residue: barley after barley raises the risk.",),
    assumptions={"hours_low": 6, "hours_high": 24, "cereal_after_cereal": 1.3},
))
_add(Rule(
    code="barley.scald", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="rynchosporioza zbóż", name_en="Leaf scald (Rhynchosporium)",
    stage_min=21, stage_max=59, temp_min=5, temp_max=12, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, needs_rain_days=2, cereal_after_cereal=1.2, severity=0.12,
    stage_thresholds=((21, 29, "Tillering: 15-20 % of the leaf area with symptoms"), (30, 39, "Stem elongation: 15-20 % of the leaf area with symptoms")),
    action_threshold="15-20 % of the leaf area with symptoms (tillering and stem elongation).",
    notes=("A cool-weather disease spread by rain splash.",),
    assumptions={"hours_low": 15, "hours_high": 50, "needs_rain_days": 2},
))
_add(Rule(
    code="barley.brown_rust", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="rdza jęczmienia", name_en="Barley leaf rust",
    stage_min=21, stage_max=75, temp_min=10, temp_max=22, moisture="wet",
    window_days=7, hours_low=4, hours_high=16, severity=0.10,
    stage_thresholds=((21, 29, "Tillering: 10-15 % of leaves with first symptoms"), (30, 39, "Stem elongation: 10 % of stems with first symptoms")),
    action_threshold="Tillering: 10-15 % of leaves with first symptoms; stem elongation: 10 % of stems.",
    notes=("Infected volunteers are the source.",),
    assumptions={"hours_low": 4, "hours_high": 16},
))

# Other cereals: triticale, rye and oats share one crop-map class; rules follow triticale and rye
_variant("wheat.powdery_mildew", "other_cereals.powdery_mildew", OTHER_CEREALS)
_variant("wheat.fusarium_head_blight", "other_cereals.fusarium_head_blight", OTHER_CEREALS)
_variant("wheat.glume_blotch", "other_cereals.glume_blotch", OTHER_CEREALS)
_variant("wheat.yellow_rust", "other_cereals.yellow_rust", OTHER_CEREALS,
         notes=("Triticale is very susceptible to yellow rust; new pathotypes also develop at 10-28 °C in dry, warm weather.",))
_variant("wheat.tan_spot", "other_cereals.tan_spot", OTHER_CEREALS)
_variant("wheat.eyespot", "other_cereals.eyespot", OTHER_CEREALS)
_variant("wheat.fusarium_foot_rot", "other_cereals.fusarium_foot_rot", OTHER_CEREALS)
_variant("wheat.snow_mould", "other_cereals.snow_mould", OTHER_CEREALS, severity=0.15,
         notes=("Rye and triticale are the most exposed cereals; counted as days with 0-5 °C, snow cover and unfrozen soil.",))
_variant("wheat.barley_yellow_dwarf", "other_cereals.barley_yellow_dwarf", OTHER_CEREALS)
_variant("wheat.aphids", "other_cereals.aphids", OTHER_CEREALS)
_variant("wheat.cereal_leaf_beetle", "other_cereals.cereal_leaf_beetle", OTHER_CEREALS)
_variant("wheat.brown_rust", "other_cereals.brown_rust", OTHER_CEREALS, temp_min=15, temp_max=20,
         notes=("Periodic daily rise of air humidity (dew); counted as wet hours at 15-20 °C. Rye and triticale are very susceptible.",))
_variant("barley.scald", "other_cereals.scald", OTHER_CEREALS)

# Winter rapeseed (sown late August)
_add(Rule(
    code="rapeseed.phoma_stem_canker", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="sucha zgnilizna kapustnych (phoma)", name_en="Phoma stem canker (blackleg)",
    stage_min=10, stage_max=19, stage_ramp=3, temp_min=8, temp_max=20, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, needs_rain_days=2, same_crop=1.4, severity=0.15,
    action_threshold="Autumn: 10-20 % of plants with leaf spots at 4-8 leaves (BBCH 14-18).",
    notes=("Ascospores are released from rapeseed stubble after rain; infections in autumn grow into stem cankers in spring.",),
    assumptions={"temp_range_c": [8, 20], "hours_low": 20, "hours_high": 60, "needs_rain_days": 2, "threshold": "10-20 % plants", "same_crop": 1.4},
))
_add(Rule(
    code="rapeseed.light_leaf_spot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="cylindrosporioza", name_en="Light leaf spot",
    stage_min=14, stage_max=59, temp_min=5, temp_max=16, moisture="wet",
    window_days=14, hours_low=30, hours_high=90, needs_rain_days=3, same_crop=1.3, severity=0.10,
    action_threshold="Autumn or early spring: 15-25 % of plants with symptoms.",
    notes=("A cool, wet weather disease spread by rain splash; develops in mild winters.",),
    assumptions={"temp_range_c": [5, 16], "hours_low": 30, "hours_high": 90, "needs_rain_days": 3, "threshold": "15-25 % plants"},
))
_add(Rule(
    code="rapeseed.sclerotinia_stem_rot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="zgnilizna twardzikowa", name_en="Sclerotinia stem rot",
    stage_min=60, stage_max=69, stage_ramp=4, temp_min=10, temp_max=25, moisture="humid",
    window_days=5, hours_low=20, hours_high=60, same_crop=1.5, severity=0.20,
    after_crops=((1410, 1.3, "Previous crop was sunflower (sclerotia in the soil)"), (1420, 1.3, "Previous crop was soybean (sclerotia in the soil)")),
    action_threshold="Treatment only works preventively at the start to full flowering (BBCH 61-65); decide from the weather and the field's history.",
    notes=("Sclerotia survive in the soil for years; fallen petals in a humid canopy start the infection.",),
    assumptions={"temp_range_c": [10, 25], "hours_low": 20, "hours_high": 60, "window_days": 5, "same_crop": 1.5},
))
_add(Rule(
    code="rapeseed.alternaria_black_spot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="czerń krzyżowych", name_en="Alternaria black spot",
    stage_min=70, stage_max=85, stage_ramp=5, temp_min=18, temp_max=27, moisture="wet",
    window_days=7, hours_low=10, hours_high=36, severity=0.10,
    action_threshold="Pod development: 25 % of pods with spots.",
    notes=("Warm, wet weather during pod ripening; infected pods shatter early.",),
    assumptions={"temp_range_c": [18, 27], "hours_low": 10, "hours_high": 36, "threshold": "25 % pods"},
))
_add(Rule(
    code="rapeseed.clubroot", crop=RAPESEED, category="fungal", kind="soil_days",
    name_pl="kiła kapusty", name_en="Clubroot",
    stage_min=0, stage_max=19, stage_ramp=3, window_days=21, hours_low=5, hours_high=14,
    soil_temp=(15.0, 26.0), soil_wet=0.30, same_crop=1.5, acid_soil=1.5, severity=0.15,
    action_threshold="No in-season treatment: rotation (4-5 years without brassicas), liming of acid soils, resistant varieties.",
    notes=("Resting spores survive 10+ years; warm, wet, acid soil at sowing favours infection.",),
    assumptions={"soil_temp_c": [15, 26], "soil_moisture_min": 0.30, "days_low": 5, "days_high": 14, "acid_soil_ph": 6.5},
))
_add(Rule(
    code="rapeseed.cabbage_stem_flea_beetle", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="pchełka rzepakowa", name_en="Cabbage stem flea beetle",
    stage_min=10, stage_max=18, stage_ramp=2, window_days=21, hours_low=7, hours_high=18, flight_c=18.0, severity=0.10,
    action_threshold="Emergence to 4 leaves: 3 beetles per m² or 10 % of the leaf area eaten; later larvae in the stems.",
    notes=("Beetles fly to the emerging crop on warm autumn days.",),
    assumptions={"flight_max_c": 18, "days_low": 7, "days_high": 18},
))
_add(Rule(
    code="rapeseed.aphids_tuyv", crop=RAPESEED, category="viral", kind="vector_days",
    name_pl="mszyca brzoskwiniowa - wirus żółtaczki rzepy (TuYV)", name_en="Aphids and turnip yellows virus",
    stage_min=10, stage_max=19, stage_ramp=3, window_days=45, hours_low=10, hours_high=30, flight_c=15.0, severity=0.10,
    action_threshold="Autumn: watch for the first winged aphids (yellow traps); a long, warm autumn raises the risk.",
    notes=("A long, warm autumn favours aphid flights into the crop.",),
    assumptions={"flight_max_c": 15, "days_low": 10, "days_high": 30},
))
_add(Rule(
    code="rapeseed.stem_weevils", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="chowacze łodygowe", name_en="Stem weevils",
    stage_min=30, stage_max=50, stage_ramp=3, window_days=10, hours_low=2, hours_high=6, flight_c=12.0, severity=0.12,
    action_threshold="Start of stem elongation: about 20 beetles in a yellow trap in 3 days; treat before egg laying.",
    notes=("First spring flights on days above about 12 °C, while the stems start to elongate.",),
    assumptions={"flight_max_c": 12, "days_low": 2, "days_high": 6, "threshold": "20 beetles / trap / 3 days"},
))
_add(Rule(
    code="rapeseed.pollen_beetle", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="słodyszek rzepakowy", name_en="Pollen beetle",
    stage_min=50, stage_max=59, stage_ramp=2, window_days=7, hours_low=2, hours_high=5, flight_c=15.0, severity=0.15,
    stage_thresholds=((50, 53, "Green bud: 1 beetle per plant"), (54, 59, "Yellow bud: 3-5 beetles per plant")),
    action_threshold="Green bud: 1 beetle per plant; yellow bud: 3-5 beetles per plant.",
    notes=("Beetles feed on closed buds; once flowering starts they feed on pollen and do little damage.",),
    assumptions={"flight_max_c": 15, "days_low": 2, "days_high": 5},
))
_add(Rule(
    code="rapeseed.seed_weevil_pod_midge", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="chowacz podobnik i pryszczarek kapustnik", name_en="Seed weevil and pod midge",
    stage_min=60, stage_max=71, stage_ramp=3, window_days=7, hours_low=2, hours_high=5, flight_c=15.0, severity=0.08,
    action_threshold="Flowering: 1 weevil per 2 plants (weevil holes let the pod midge in).",
    assumptions={"flight_max_c": 15, "days_low": 2, "days_high": 5},
))

# Sugar beet (sown early April)
_add(Rule(
    code="sugar_beet.cercospora_leaf_spot", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="chwościk buraka", name_en="Cercospora leaf spot",
    stage_min=31, stage_max=49, stage_ramp=6, temp_min=16, temp_max=32, moisture="humid",
    window_days=7, hours_low=30, hours_high=90, same_crop=1.5, severity=0.20,
    action_threshold="South of Poland: the first spots on leaves; elsewhere up to 5 Aug no more than 5 % of plants with symptoms, 5-15 Aug 10-15 %, 15 Aug - 10 Sep 45 %.",
    notes=("The main beet disease in Poland: warm days (25-30 °C), nights above 15 °C and long humid periods; observe from early July (mid June in the south) after a few rainy, warm days.",
           "Counted as humid hours at 16-32 °C (warm nights included)."),
    assumptions={"temp_range_c": [16, 32], "hours_low": 30, "hours_high": 90, "same_crop": 1.5},
))
_add(Rule(
    code="sugar_beet.ramularia_leaf_spot", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="brunatna plamistość liści buraka", name_en="Ramularia leaf spot",
    stage_min=31, stage_max=49, stage_ramp=6, temp_min=15, temp_max=22, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, severity=0.08,
    notes=("Cooler (17-20 °C) and wet weather.",),
    assumptions={"temp_range_c": [15, 22], "hours_low": 15, "hours_high": 50},
))
_add(Rule(
    code="sugar_beet.powdery_mildew", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="mączniak prawdziwy buraka", name_en="Beet powdery mildew",
    stage_min=35, stage_max=49, stage_ramp=6, temp_min=20, temp_max=30, moisture="mild",
    window_days=7, hours_low=40, hours_high=100, severity=0.08,
    notes=("Warm (20-30 °C), dry and sunny weather.",),
    assumptions={"temp_range_c": [20, 30], "hours_low": 40, "hours_high": 100},
))
_add(Rule(
    code="sugar_beet.downy_mildew", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="mączniak rzekomy buraka", name_en="Beet downy mildew",
    stage_min=10, stage_max=39, stage_ramp=4, temp_min=5, temp_max=15, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, severity=0.05,
    notes=("Cool (up to 15 °C), wet and cloudy weather.",),
    assumptions={"temp_range_c": [5, 15], "hours_low": 20, "hours_high": 60},
))
_add(Rule(
    code="sugar_beet.seedling_damping_off", crop=SUGAR_BEET, category="fungal", kind="soil_days",
    name_pl="zgorzel siewek buraka", name_en="Seedling damping-off",
    stage_min=0, stage_max=14, stage_ramp=3, window_days=10, hours_low=3, hours_high=8, soil_temp=(None, 15.0), heavy_soil=1.3,
    severity=0.08,
    action_threshold="Prevention by seed treatment and sowing into warm soil; no in-season treatment.",
    notes=("Pre-emergence damping-off with soil up to 15 °C and high moisture; compacted, crusted soil makes it worse.",),
    assumptions={"soil_temp_max_c": 15, "soil_moisture_min": 0.30, "days_low": 3, "days_high": 8},
))
_add(Rule(
    code="sugar_beet.rhizoctonia_root_rot", crop=SUGAR_BEET, category="fungal", kind="soil_days",
    name_pl="zgnilizna brunatna korzeni buraka", name_en="Rhizoctonia root and crown rot",
    stage_min=31, stage_max=49, stage_ramp=6, window_days=21, hours_low=5, hours_high=14, soil_temp=(20.0, 30.0),
    same_crop=1.5, heavy_soil=1.3, severity=0.12,
    after_crops=((1130, 1.4, "Previous crop was maize (the same Rhizoctonia group infects maize)"),),
    action_threshold="No in-season treatment: rotation, tolerant varieties, avoiding compaction.",
    notes=("Warm (20-30 °C), wet soil in summer.",),
    assumptions={"soil_temp_c": [20, 30], "soil_moisture_min": 0.30, "days_low": 5, "days_high": 14, "after_maize": 1.4},
))
_add(Rule(
    code="sugar_beet.aphids_virus_yellows", crop=SUGAR_BEET, category="viral", kind="vector_days",
    name_pl="mszyce - wirusowe żółtaczki buraka", name_en="Aphids and virus yellows",
    stage_min=12, stage_max=39, stage_ramp=4, window_days=14, hours_low=4, hours_high=10, flight_c=17.0, severity=0.12,
    action_threshold="From 3-4 leaves: at least 15 % of plants with aphids or 15 wingless aphids per plant; against viruses, the first winged aphids.",
    notes=("Warm, dry springs bring early aphid flights.",),
    assumptions={"flight_max_c": 17, "days_low": 4, "days_high": 10},
))
_add(Rule(
    code="sugar_beet.flea_beetle", crop=SUGAR_BEET, category="pest", kind="vector_days",
    name_pl="pchełka burakowa", name_en="Beet flea beetle",
    stage_min=10, stage_max=15, stage_ramp=2, window_days=7, hours_low=2, hours_high=5, flight_c=18.0, severity=0.06,
    action_threshold="Emergence to 4-5 leaves: 5-10 beetles per m².",
    notes=("Warm, dry weather at emergence.",),
    assumptions={"flight_max_c": 18, "days_low": 2, "days_high": 5},
))
_add(Rule(
    code="sugar_beet.beet_leaf_miner", crop=SUGAR_BEET, category="pest", kind="pest_activity",
    name_pl="śmietka ćwiklanka", name_en="Beet leaf miner",
    stage_min=11, stage_max=19, stage_ramp=3, dd10_start=80, dd10_peak=(150, 300), dd10_end=450, warm_ramp=(12, 18),
    severity=0.05,
    stage_thresholds=((11, 12, "2 true leaves: 4 eggs or mines per plant"), (13, 14, "4 true leaves: 8 eggs or mines per plant"), (15, 19, "6 true leaves: more than 20 eggs or mines per plant")),
    action_threshold="From May: 4 eggs or mines per plant at 2 leaves, 8 at 4 leaves, more than 20 at 6 leaves.",
    assumptions={"dd10_start": 80, "dd10_peak": [150, 300], "dd10_end": 450},
))
_add(Rule(
    code="sugar_beet.beet_cyst_nematode", crop=SUGAR_BEET, category="pest", kind="pest_activity",
    name_pl="mątwik burakowy", name_en="Beet cyst nematode",
    stage_min=10, stage_max=49, stage_ramp=5, dd10_start=50, dd10_peak=(200, 900), dd10_end=1400,
    rotation_hosts=(SUGAR_BEET, RAPESEED), rotation_years=3, severity=0.15,
    action_threshold="Soil test before sowing: 500 eggs and larvae per 100 g of soil. No in-season treatment: rotation, tolerant varieties, nematode-resistant catch crops.",
    notes=("Rapeseed and other brassicas are hosts too: beet or rapeseed in the last 3 seasons keeps the population up.",),
    assumptions={"rotation_years": 3, "pressure_with_host": 1.0, "pressure_without_host": 0.1},
))

# Potato (planted late April)
_add(Rule(
    code="potato.late_blight", crop=POTATO, category="fungal", kind="infection_hours",
    name_pl="zaraza ziemniaka", name_en="Late blight",
    stage_min=21, stage_max=91, stage_ramp=5, temp_min=10, temp_max=25, moisture="rh90",
    window_days=2, hours_low=11, hours_high=22, same_crop=1.2, severity=0.30,
    action_threshold="Early varieties: start protection when the rows close; later varieties: when the first symptoms appear on early varieties. Treatments after symptoms rarely stop it.",
    notes=("The most important potato disease. Counted like a Smith period: hours at 10-25 °C with RH >= 90 % or rain over the last 2 days (2 x 11 h = full risk).",
           "Decision support systems (NegFry) set the spray dates from the weather."),
    assumptions={"hours_low": 11, "hours_high": 22, "window_days": 2, "rh": 90},
))
_add(Rule(
    code="potato.early_blight", crop=POTATO, category="fungal", kind="infection_hours",
    name_pl="alternarioza ziemniaka", name_en="Early blight (Alternaria)",
    stage_min=40, stage_max=91, stage_ramp=10, temp_min=18, temp_max=30, moisture="wet",
    window_days=7, hours_low=10, hours_high=40, same_crop=1.3, severity=0.12,
    action_threshold="Inspect older leaves from tuber bulking; stressed plants (drought, low nitrogen) are more exposed.",
    notes=("Warm weather with alternating wet and dry periods; residue in the soil carries it over.",),
    assumptions={"temp_range_c": [18, 30], "hours_low": 10, "hours_high": 40},
))
_add(Rule(
    code="potato.rhizoctonia", crop=POTATO, category="fungal", kind="soil_days",
    name_pl="rizoktonioza ziemniaka", name_en="Rhizoctonia stem canker",
    stage_min=0, stage_max=19, stage_ramp=3, window_days=14, hours_low=3, hours_high=10, soil_temp=(None, 10.0), same_crop=1.3,
    severity=0.08,
    action_threshold="Prevention by seed tuber treatment and planting into warm soil; no in-season treatment.",
    notes=("Cold, wet soil after planting slows emergence and lets the fungus attack sprouts and stems.",),
    assumptions={"soil_temp_max_c": 10, "soil_moisture_min": 0.30, "days_low": 3, "days_high": 10},
))
_add(Rule(
    code="potato.colorado_potato_beetle", crop=POTATO, category="pest", kind="pest_activity",
    name_pl="stonka ziemniaczana", name_en="Colorado potato beetle",
    stage_min=10, stage_max=79, stage_ramp=5, dd10_start=150, dd10_peak=(300, 650), dd10_end=950, warm_ramp=(15, 22),
    same_crop=1.4, severity=0.20,
    action_threshold="After emergence: 10 egg masses per 10 plants, or 15 larvae per plant, or 1-2 overwintered beetles per 25 plants; treat when most larvae are L2-L3.",
    notes=("Beetles overwinter in the soil and fly in from last year's potato fields; larvae cause most of the loss (20-30 % unprotected).",),
    assumptions={"dd10_start": 150, "dd10_peak": [300, 650], "dd10_end": 950, "same_crop": 1.4},
))
_add(Rule(
    code="potato.aphids", crop=POTATO, category="viral", kind="pest_activity",
    name_pl="mszyce - wektory wirusów ziemniaka", name_en="Aphids (virus vectors)",
    stage_min=10, stage_max=69, stage_ramp=5, dd10_start=150, dd10_peak=(250, 700), dd10_end=1000, warm_ramp=(14, 20),
    severity=0.08,
    action_threshold="After emergence, as virus vectors: 5-10 aphids per 100 leaves (seed crops), 10-20 per 100 leaves (ware crops); as a pest: 500 per 100 leaves.",
    assumptions={"dd10_start": 150, "dd10_peak": [250, 700], "dd10_end": 1000},
))
_add(Rule(
    code="potato.cyst_nematode", crop=POTATO, category="pest", kind="pest_activity",
    name_pl="mątwik ziemniaczany", name_en="Potato cyst nematode",
    stage_min=10, stage_max=79, stage_ramp=5, dd10_start=50, dd10_peak=(200, 800), dd10_end=1200,
    rotation_hosts=(POTATO,), rotation_years=3, severity=0.10,
    action_threshold="Soil test before planting: up to 10 eggs with live larvae per g of soil. No in-season treatment: rotation and resistant varieties.",
    notes=("Cysts stay viable for up to 20 years; potato in the last 3 seasons keeps the population up.",),
    assumptions={"rotation_years": 3, "pressure_with_host": 1.0, "pressure_without_host": 0.1},
))


CEREALS = {WHEAT, BARLEY, OTHER_CEREALS}
WINTER_CROPS = {WHEAT, BARLEY, OTHER_CEREALS, RAPESEED}  # dormant in winter: leaf diseases switch off in the cold

# Last season's risk on the same field that carries over in residue / soil (same pathogen or pest).
# Fusarium spp. infect both maize and wheat, so a bad maize year raises next year's head blight.
CARRYOVER = {
    "wheat.fusarium_head_blight": ("wheat.fusarium_head_blight", "barley.fusarium_head_blight", "other_cereals.fusarium_head_blight",
                                   "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "maize.fusarium_ear_rot": ("maize.fusarium_ear_rot", "maize.fusarium_stalk_rot", "wheat.fusarium_head_blight"),
    "maize.fusarium_stalk_rot": ("maize.fusarium_stalk_rot", "maize.fusarium_ear_rot", "wheat.fusarium_head_blight"),
    "wheat.septoria_leaf_blotch": ("wheat.septoria_leaf_blotch",),
    "wheat.tan_spot": ("wheat.tan_spot",),
    "wheat.take_all": ("wheat.take_all",),
    "maize.european_corn_borer": ("maize.european_corn_borer",),
    "barley.fusarium_head_blight": ("barley.fusarium_head_blight", "wheat.fusarium_head_blight", "other_cereals.fusarium_head_blight",
                                    "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "other_cereals.fusarium_head_blight": ("other_cereals.fusarium_head_blight", "wheat.fusarium_head_blight", "barley.fusarium_head_blight",
                                           "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "barley.net_blotch": ("barley.net_blotch",),
    "rapeseed.phoma_stem_canker": ("rapeseed.phoma_stem_canker",),
    "rapeseed.sclerotinia_stem_rot": ("rapeseed.sclerotinia_stem_rot",),
    "sugar_beet.cercospora_leaf_spot": ("sugar_beet.cercospora_leaf_spot",),
    "potato.late_blight": ("potato.late_blight",),
    "potato.colorado_potato_beetle": ("potato.colorado_potato_beetle",),
}


def rules_for_crop(crop_code: int) -> list[Rule]:
    return [r for r in RULES.values() if r.crop == crop_code]
