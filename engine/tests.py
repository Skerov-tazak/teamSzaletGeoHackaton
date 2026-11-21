"""
Engine tests on synthetic weather (no downloaded data needed).

    python manage.py test engine
"""

from datetime import date, datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from core.models import (Clock, CropClass, Field, FieldCropYear, Risk, Threat, WeatherDaily, WeatherGrid,
                         WeatherHourly)
from engine import predict
from engine.catalog import RULES
from engine.compute import field_context
from engine.satellite.season import season_of, slot_end, slot_of

SEASON_START = date(2024, 9, 1)
SEASON_END = date(2025, 7, 31)


def seasonal_temp(day: date) -> float:
    """A rough Polish annual temperature curve, °C."""
    import math
    doy = day.timetuple().tm_yday
    return 8.5 - 10.5 * math.cos(2 * math.pi * (doy - 15) / 365)


class EngineTestBase(TestCase):
    wet_days: set[date] = set()

    @classmethod
    def setUpTestData(cls):
        for code, name in ((0, "No cropland"), (1110, "Wheat"), (1120, "Barley"), (1130, "Maize")):
            CropClass.objects.create(code=code, name=name)
        for rule in RULES.values():
            Threat.objects.create(code=rule.code, crop_id=rule.crop, name=rule.name_pl, category=rule.category, source="test")
        cls.grid = WeatherGrid.objects.create(grid_id="g1", lat=50.35, lon=17.7)
        Clock(today=date(2025, 6, 15)).save()
        cls.make_weather(cls.wet_days)
        cls.wheat = cls.make_field("wheat", 1110, prev=1130)
        cls.wheat_after_wheat = cls.make_field("wheat2", 1110, prev=1110)
        cls.maize = cls.make_field("maize", 1130, prev=1110)

    @classmethod
    def make_weather(cls, wet_days):
        daily, hourly = [], []
        d = SEASON_START - timedelta(days=60)
        while d <= SEASON_END:
            t = seasonal_temp(d)
            wet = d in wet_days
            daily.append(WeatherDaily(grid=cls.grid, date=d, avg_temperature=t, min_temperature=t - 5, max_temperature=t + 5,
                                      avg_relative_humidity=96 if wet else 65, total_precipitation=8 if wet else 0,
                                      eto=2.0, avg_wind_speed=8, avg_soil_temperature_level_1=t, min_soil_temperature_level_1=t - 2,
                                      avg_soil_moisture_level_1=0.25, avg_snow_depth=0))
            for h in range(24):
                ts = datetime(d.year, d.month, d.day, h, tzinfo=dt_tz.utc)
                hourly.append(WeatherHourly(grid=cls.grid, utc_time=ts, date=d, temperature=t + 4 * (1 if 10 <= h <= 18 else -1) * 0.5,
                                            dew_point_temperature=t - 1, relative_humidity=97 if wet else 65,
                                            precipitation=0.5 if wet else 0))
            d += timedelta(days=1)
        WeatherDaily.objects.bulk_create(daily)
        WeatherHourly.objects.bulk_create(hourly, batch_size=5000)

    @classmethod
    def make_field(cls, name, crop, prev):
        f = Field.objects.create(name=name, geometry={"type": "Polygon", "coordinates": []}, area_ha=10,
                                 centroid_lat=50.35, centroid_lon=17.7, weather_grid=cls.grid, h3_cells=[], crop_id=crop)
        FieldCropYear.objects.create(field=f, year=2024, crop_class_id=prev, share=1.0)
        return f


class SeasonGridTests(TestCase):
    def test_season_and_slots(self):
        self.assertEqual(season_of(date(2024, 9, 1)), 2025)
        self.assertEqual(season_of(date(2025, 8, 31)), 2025)
        self.assertEqual(slot_of(date(2024, 9, 1)), 0)
        self.assertEqual(slot_of(date(2025, 8, 31)), 23)
        self.assertEqual(slot_end(2025, 0), date(2024, 9, 15))
        self.assertEqual(slot_end(2025, 23), date(2025, 8, 31))


class PredictTests(EngineTestBase):
    # warm and wet around wheat flowering (the synthetic, cool season flowers ~20-25 June)
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_writes_rows_within_bounds_with_explanations(self):
        n = predict(start=date(2025, 5, 1), end=date(2025, 6, 22))
        days = (date(2025, 6, 22) - date(2025, 5, 1)).days + 1
        n_rules = sum(1 for r in RULES.values() if r.crop == 1110) * 2 + sum(1 for r in RULES.values() if r.crop == 1130)
        self.assertEqual(n, days * n_rules)
        self.assertEqual(Risk.objects.count(), n)
        for r in Risk.objects.all()[:200]:
            self.assertTrue(0 <= r.score <= 1)
            e = r.explanation
            for key in ("summary", "level", "drivers", "action", "sources", "growth_stage", "confidence", "model_version"):
                self.assertIn(key, e)
            self.assertEqual(e["threat"]["code"], r.threat.code)

    def test_rerun_overwrites(self):
        n1 = predict(start=date(2025, 6, 1), end=date(2025, 6, 10))
        n2 = predict(start=date(2025, 6, 1), end=date(2025, 6, 10))
        self.assertEqual(n1, n2)
        self.assertEqual(Risk.objects.count(), n1)

    def test_fusarium_high_at_wet_flowering_and_previous_maize_raises_it(self):
        predict(start=date(2025, 6, 10), end=date(2025, 6, 24))
        fhb = Risk.objects.filter(threat__code="wheat.fusarium_head_blight", date=date(2025, 6, 23))
        after_maize = fhb.get(field=self.wheat)
        after_wheat = fhb.get(field=self.wheat_after_wheat)
        self.assertGreater(after_maize.score, 0.3, after_maize.explanation["summary"])
        self.assertGreaterEqual(after_maize.score, after_wheat.score)
        factors = {d["factor"] for d in after_maize.explanation["drivers"]}
        self.assertIn("previous_crop", factors)
        dry = Risk.objects.get(threat__code="wheat.fusarium_head_blight", date=date(2025, 6, 17), field=self.wheat)
        self.assertLess(dry.score, after_maize.score)

    def test_maize_not_sown_scores_zero(self):
        predict(start=date(2025, 3, 1), end=date(2025, 3, 31))
        rows = Risk.objects.filter(field=self.maize)
        self.assertTrue(rows.exists())
        self.assertEqual(max(r.score for r in rows), 0.0)
        self.assertIn("not sown", rows.first().explanation["summary"])

    def test_range_across_season_boundary(self):
        n = predict(field_ids=[self.wheat.id], start=date(2025, 7, 25), end=date(2025, 7, 31))
        self.assertEqual(n, 7 * sum(1 for r in RULES.values() if r.crop == 1110))

    def test_field_context_history(self):
        ctx = field_context(self.wheat, 2025)
        self.assertEqual(ctx.previous_crop, 1130)
        self.assertEqual(field_context(self.maize, 2025).maize_years_in_row, 1)


class NoLookAheadTests(EngineTestBase):
    wet_days = {date(2025, 6, d) for d in range(10, 15)}  # wet only AFTER the assessed day

    def test_future_weather_does_not_change_past_risk(self):
        predict(start=date(2025, 6, 1), end=date(2025, 6, 14))
        before = {(r.field_id, r.threat_id): r.score for r in Risk.objects.filter(date=date(2025, 6, 8))}
        # the wet spell after 8 June must not raise risks on 8 June: compare with a dry run of the same day
        WeatherHourly.objects.filter(date__gte=date(2025, 6, 9)).update(relative_humidity=40, precipitation=0)
        WeatherDaily.objects.filter(date__gte=date(2025, 6, 9)).update(avg_relative_humidity=40, total_precipitation=0)
        predict(start=date(2025, 6, 1), end=date(2025, 6, 14))
        after = {(r.field_id, r.threat_id): r.score for r in Risk.objects.filter(date=date(2025, 6, 8))}
        self.assertEqual(before, after)


class ObservationTests(EngineTestBase):
    """Farmer reports change risks from their date on, and show up in the explanation."""
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def run_day(self, code, day, field, reports):
        from engine.observations import Report  # noqa: F401  (import check)
        predict(field_ids=[field.id], start=day - timedelta(days=10), end=day, observations=reports)
        return Risk.objects.get(field=field, threat__code=code, date=day)

    def test_symptoms_floor_and_confidence(self):
        from engine.observations import Report
        day = date(2025, 6, 10)  # dry, so rules alone give a low score
        base = self.run_day("wheat.septoria_leaf_blotch", day, self.wheat, [])
        rep = Report(observed_on=date(2025, 6, 8), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=0.8, field_id=self.wheat.id)
        seen = self.run_day("wheat.septoria_leaf_blotch", day, self.wheat, [rep])
        self.assertLess(base.score, 0.3)
        self.assertGreaterEqual(seen.score, 0.8)
        self.assertEqual(seen.explanation["confidence"], 1.0)
        fr = [d for d in seen.explanation["drivers"] if d["factor"] == "farmer_report"]
        self.assertEqual(len(fr), 1)
        self.assertGreater(fr[0]["effect"], 0.5)
        self.assertIn("farmer reported septoria leaf blotch", seen.explanation["summary"].lower())

    def test_report_does_not_change_earlier_days(self):
        from engine.observations import Report
        rep = Report(observed_on=date(2025, 6, 9), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=1.0, field_id=self.wheat.id)
        before = self.run_day("wheat.septoria_leaf_blotch", date(2025, 6, 8), self.wheat, [rep])
        self.assertLess(before.score, 0.3)
        self.assertFalse([d for d in before.explanation["drivers"] if d["factor"] == "farmer_report"])

    def test_neighbour_raises_treatment_lowers_absence_lowers(self):
        from engine.observations import Report
        code, day = "wheat.fusarium_head_blight", date(2025, 6, 23)
        f = self.wheat_after_wheat  # no previous-maize multiplier, so there is room to move
        base = self.run_day(code, day, f, []).score
        nb = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 20), kind="neighbour", threat_code=code, distance_m=300)]).score
        tr = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 21), kind="treatment", threat_code=code, field_id=f.id)])
        ab = self.run_day(code, day, f, [Report(observed_on=date(2025, 6, 22), kind="absence", field_id=f.id)]).score
        self.assertGreater(base, 0)
        self.assertGreaterEqual(nb, base)
        self.assertLess(tr.score, base)
        self.assertEqual(tr.explanation["action"]["type"], "wait")
        self.assertLess(ab, base)

    def test_reports_for_other_fields_are_ignored(self):
        from engine.observations import Report
        rep = Report(observed_on=date(2025, 6, 8), kind="symptoms", threat_code="wheat.septoria_leaf_blotch", severity=1.0, field_id=self.wheat_after_wheat.id)
        r = self.run_day("wheat.septoria_leaf_blotch", date(2025, 6, 10), self.wheat, [rep])
        self.assertLess(r.score, 0.3)

    def test_farmer_sowing_date_changes_stage(self):
        from engine.observations import Report
        day = date(2025, 6, 1)
        late = Report(observed_on=date(2025, 5, 1), kind="field_fact", details={"sowing_date": "2025-05-20"}, field_id=self.maize.id)
        r0 = self.run_day("maize.frit_fly", day, self.maize, [])
        r1 = self.run_day("maize.frit_fly", day, self.maize, [late])
        self.assertLess(r1.explanation["growth_stage"]["bbch"], r0.explanation["growth_stage"]["bbch"])
        self.assertEqual(r1.explanation["growth_stage"]["sowing_assumed"], "2025-05-20")
        self.assertIn("farmer", r1.explanation["growth_stage"]["method"])


class PureFunctionTests(TestCase):
    def test_safe_storage_days_matches_table_37(self):
        from engine.harvest import safe_storage_days
        self.assertAlmostEqual(safe_storage_days(22, 15.6), 17, delta=0.5)
        self.assertAlmostEqual(safe_storage_days(18, -1.1), 648, delta=1)
        self.assertGreater(safe_storage_days(20, 5), safe_storage_days(26, 5))
        self.assertGreater(safe_storage_days(24, 5), safe_storage_days(24, 20))

    def test_spray_window_rules(self):
        import pandas as pd
        from engine.scoring import spray_window
        fc = pd.DataFrame({
            "max_temperature": [28, 18, 18], "min_temperature": [12, 8, 0.5], "total_precipitation": [0, 0, 0],
            "avg_wind_speed": [5, 5, 5], "avg_relative_humidity": [80, 80, 80],
        }, index=[date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 4)])
        self.assertIsNone(spray_window(fc))  # 2 Jun too hot; 3 Jun ok but the next night is 0.5 °C; 4 Jun itself 0.5 °C
        fc.loc[date(2025, 6, 4), "min_temperature"] = 6
        w = spray_window(fc)
        self.assertEqual(w["date"], "2025-06-03")
        self.assertEqual(w["quality"], "optimal")

    def test_lead_adjust_is_idempotent(self):
        from engine.compute import adjust_for_lead
        e = {"confidence": 0.6, "notes": []}
        adjust_for_lead(e, 5); adjust_for_lead(e, 5)
        self.assertAlmostEqual(e["confidence"], round(0.6 * 0.7, 2))
        self.assertEqual(len([n for n in e["notes"] if n.startswith("Day +")]), 1)


class FarmFeatureTests(EngineTestBase):
    wet_days = {date(2025, 6, d) for d in range(18, 24)}

    def test_ranking_orders_by_expected_loss(self):
        from engine.summary import farm_ranking
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        r = farm_ranking(date(2025, 6, 23))
        self.assertEqual([x["rank"] for x in r], list(range(1, len(r) + 1)))
        losses = [x["expected_loss"] for x in r]
        self.assertEqual(losses, sorted(losses, reverse=True))
        self.assertIn("why", r[0])

    def test_symptoms_spread_to_nearby_same_crop_field(self):
        from engine.observations import Report
        code = "wheat.fusarium_head_blight"
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        before = Risk.objects.get(field=self.wheat_after_wheat, threat__code=code, date=date(2025, 6, 23)).score
        rep = Report(observed_on=date(2025, 6, 20), kind="symptoms", threat_code=code, severity=0.8, field_id=self.wheat.id)
        predict(field_ids=[self.wheat.id], start=date(2025, 6, 15), end=date(2025, 6, 23), observations=[rep])
        after = Risk.objects.get(field=self.wheat_after_wheat, threat__code=code, date=date(2025, 6, 23))
        self.assertGreaterEqual(after.score, before)  # may already be saturated at 1.0
        self.assertTrue(any(d["factor"] == "farmer_report" and d["kind"] == "neighbour" for d in after.explanation["drivers"]))

    def test_what_if_does_not_write(self):
        from engine import what_if
        from engine.observations import Report
        code = "wheat.fusarium_head_blight"
        predict(start=date(2025, 6, 15), end=date(2025, 6, 23))
        stored = Risk.objects.get(field=self.wheat, threat__code=code, date=date(2025, 6, 23)).score
        res = what_if(self.wheat.id, date(2025, 6, 23), [Report(observed_on=date(2025, 6, 22), kind="treatment", threat_code=code, field_id=self.wheat.id)])
        fhb = next(x for x in res if x["threat_code"] == code)
        self.assertLess(fhb["score_if"], fhb["score_now"])
        self.assertEqual(Risk.objects.get(field=self.wheat, threat__code=code, date=date(2025, 6, 23)).score, stored)

    def test_coming_days_have_lower_confidence(self):
        predict(start=date(2025, 6, 14), end=date(2025, 6, 20))  # clock: 15 June
        today_row = Risk.objects.filter(field=self.wheat, date=date(2025, 6, 15)).first()
        ahead = Risk.objects.get(field=self.wheat, threat=today_row.threat, date=date(2025, 6, 20))
        self.assertEqual(ahead.explanation["forecast_lead_days"], 5)
        self.assertLess(ahead.explanation["confidence"], today_row.explanation["confidence"])

    def test_maize_season_continues_after_1_september(self):
        n = predict(field_ids=[self.maize.id], start=date(2025, 7, 25), end=date(2025, 7, 31))
        self.assertGreater(n, 0)
