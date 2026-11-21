"""
The development stand-in for the platform API (engine_mock_api) must answer exactly as docs/interfaces.md
agrees: the keys of each example, the cut-off at today + 7, and {"detail": ...} errors. The map is built
against it, so a difference here would be a difference against the real API later.
"""

from datetime import date, timedelta

from django.test import TestCase

from core.models import Risk, SoilCell
from engine import predict
from engine.management.commands import engine_mock_api as M
from engine.tests import EngineTestBase, copy_forecast

TODAY = date(2025, 6, 15)


def call(fn, *args, q=None, body=None):
    try:
        return 200, fn(q or {}, body, *args)
    except M.ApiError as e:
        return e.status, {"detail": e.detail}


class MockApiShapeTests(EngineTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        copy_forecast(cls.grid, TODAY, TODAY + timedelta(days=1))  # issued on today and on the day after
        predict(start=date(2025, 6, 1))   # to today + 7

    def test_clock(self):
        self.assertEqual(call(M.clock_get), (200, {"today": "2025-06-15", "forecast_days": 7}))

    def test_threats(self):
        _, rows = call(M.threats)
        self.assertEqual(set(rows[0]), {"code", "name", "crop", "category"})
        self.assertEqual(set(rows[0]["crop"]), {"code", "name"})

    def test_fields_geojson(self):
        _, fc = call(M.fields)
        self.assertEqual(fc["type"], "FeatureCollection")
        f = fc["features"][0]
        self.assertEqual(set(f), {"type", "id", "geometry", "properties"})
        self.assertEqual(set(f["properties"]), {"id", "name", "crop", "area_ha"})

    def test_field_detail(self):
        SoilCell.objects.create(h3_index_10="8a1e3a5a1d27fff", ph=6.0, clay=0.2, sand=0.3, silt=None, soil_texture="Loam")
        self.wheat.h3_cells = ["8a1e3a5a1d27fff"]
        self.wheat.save()
        _, d = call(M.field_detail, str(self.wheat.id))
        self.assertEqual(set(d), {"id", "name", "crop", "area_ha", "centroid", "weather_grid_id", "crop_history", "soil"})
        self.assertEqual(set(d["centroid"]), {"lat", "lon"})
        self.assertEqual(set(d["crop_history"][0]), {"year", "classes"})
        self.assertEqual(set(d["crop_history"][0]["classes"][0]), {"code", "name", "share"})
        self.assertEqual(set(d["soil"]), {"ph", "soil_texture", "clay", "sand", "silt", "om", "cec", "bulk_density"})
        self.assertIsNone(d["soil"]["silt"])        # null in every cell stays null
        self.assertEqual(call(M.field_detail, "99999")[0], 404)

    def test_risks_day_and_cut_off(self):
        status, d = call(M.risks_day, q={"date": "2025-06-15"})
        self.assertEqual(set(d), {"date", "risks"})
        self.assertEqual(set(d["risks"][0]), {"field_id", "threat_code", "score"})
        self.assertEqual(call(M.risks_day)[1]["date"], "2025-06-15")                 # default today
        self.assertEqual(call(M.risks_day, q={"date": "2025-06-22"})[0], 200)       # today + 7
        self.assertEqual(call(M.risks_day, q={"date": "2025-06-23"}), (400, {"detail": "date is after today + 7"}))
        self.assertEqual(call(M.risks_day, q={"date": "15.06.2025"})[0], 400)

    def test_field_series_cut_at_horizon(self):
        status, d = call(M.field_risks, str(self.wheat.id), q={"from": "2025-06-01", "to": "2025-12-31"})
        self.assertEqual(set(d), {"field_id", "from", "to", "threats"})
        self.assertEqual(d["to"], "2025-06-22")                                     # cut, and reported
        self.assertEqual(set(d["threats"][0]), {"threat_code", "points"})
        self.assertEqual(set(d["threats"][0]["points"][0]), {"date", "score"})
        self.assertTrue(all(p["date"] <= "2025-06-22" for t in d["threats"] for p in t["points"]))
        self.assertEqual(call(M.field_risks, str(self.wheat.id))[1]["from"], "2024-09-01")  # default: 1 Sep, year before
        self.assertEqual(call(M.field_risks, str(self.wheat.id), q={"from": "2025-07-01"})[0], 400)  # from > to

    def test_field_day_with_explanations(self):
        status, d = call(M.field_day, str(self.wheat.id), "2025-06-15")
        self.assertEqual(set(d), {"field_id", "date", "risks"})
        r = d["risks"][0]
        self.assertEqual(set(r), {"threat", "score", "explanation"})
        self.assertEqual(set(r["threat"]), {"code", "name", "category"})
        self.assertEqual(r["explanation"]["version"], 1)
        scores = [x["score"] for x in d["risks"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(call(M.field_day, str(self.wheat.id), "2025-06-23")[0], 400)

    def test_put_clock_recomputes_the_window(self):
        before = Risk.objects.filter(date=TODAY + timedelta(days=3)).first()
        self.assertEqual(before.explanation["forecast_lead_days"], 3)
        self.assertEqual(call(M.clock_put, body={"today": "2025-06-16"}), (200, {"today": "2025-06-16", "forecast_days": 7}))
        after = Risk.objects.get(field=before.field, threat=before.threat, date=before.date)
        self.assertEqual(after.explanation["forecast_lead_days"], 2)            # clock_moved ran
        self.assertEqual(call(M.clock_put, body={})[0], 400)
        self.assertEqual(call(M.clock_put, body={"today": "jutro"})[0], 400)


class MockApiNoClockTests(TestCase):
    def test_missing_clock_is_503(self):
        self.assertEqual(call(M.clock_get)[0], 503)
