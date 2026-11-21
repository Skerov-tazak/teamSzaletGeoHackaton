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
