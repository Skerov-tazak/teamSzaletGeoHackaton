"""Tests of the assistant's tools (assistant/tools) on a small synthetic farm (assistant/devdata.py)."""
from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from assistant import devdata, domain
from assistant.models import Observation
from assistant.tools import sql
from assistant.tools.registry import ToolError, available, call, to_openai_tools

TODAY = dt.date(2024, 5, 15)


class ToolTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = devdata.build(start=dt.date(2024, 4, 10), end=dt.date(2024, 5, 31), today=TODAY,
                                  )
        cls.wheat = next(f for f in cls.world.fields if f.crop_id == devdata.CROP_WHEAT)
        cls.wheat2 = [f for f in cls.world.fields if f.crop_id == devdata.CROP_WHEAT][1]
        cls.maize = next(f for f in cls.world.fields if f.crop_id == devdata.CROP_MAIZE)


class RegistryTests(ToolTestCase):
    def test_unknown_tool_and_bad_input_raise_tool_error(self):
        with self.assertRaises(ToolError):
            call("no_such_tool")
        with self.assertRaises(ToolError):
            call("get_field", field_id="abc")

    def test_openai_schemas_exclude_write_tools(self):
        names = [t["function"]["name"] for t in to_openai_tools()]
        self.assertIn("get_field_risks", names)
        self.assertNotIn("record_observation", names)
        self.assertTrue(all(t["function"]["parameters"]["type"] == "object" for t in to_openai_tools()))

    def test_sql_tool_disabled_by_default(self):
        self.assertNotIn("run_readonly_sql", [t.name for t in available()])


class PlatformToolTests(ToolTestCase):
    def test_season_date(self):
        r = call("get_season_date")
        self.assertEqual(r["today"], "2024-05-15")
        self.assertEqual(r["forecast_until"], "2024-05-22")

    def test_list_and_get_field_without_geometry(self):
        self.assertEqual(len(call("list_fields")["fields"]), len(devdata.DEV_FIELDS))
        f = call("get_field", field_id=self.wheat.id)
        self.assertEqual(f["crop"], "pszenica")
        self.assertNotIn("geometry", f)
        with self.assertRaises(ToolError):
            call("get_field", field_id=999999)

    def test_field_risks_overview_and_cut_at_forecast(self):
        r = call("get_field_risks", field_id=self.wheat.id, date_to="2024-06-30")
        self.assertTrue(r["cut_at_forecast"])
        self.assertEqual(r["date_to"], "2024-05-22")
        self.assertTrue(r["threats"])
        scores = [t["today"]["score"] for t in r["threats"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertNotIn("points", r["threats"][0])  # overview has no daily points
        self.assertEqual(r["threats"][0]["citation"]["type"], "risk")

    def test_field_risks_one_threat_inflected(self):
        r = call("get_field_risks", field_id=self.wheat.id, threat="septoriozy paskowanej")
        self.assertEqual(len(r["threats"]), 1)
        self.assertEqual(r["threats"][0]["threat_code"], "wheat.septoria_leaf_blotch")
        self.assertTrue(r["threats"][0]["points"])
        self.assertIn(r["threats"][0]["trend"], ("rośnie", "maleje", "stały"))
        with self.assertRaises(ToolError):
            call("get_field_risks", field_id=self.wheat.id, threat="zupełnie nieznana choroba xyz")

    def test_farm_summary_sorted_and_no_future(self):
        s = call("get_farm_risk_summary")
        maxes = [f["max_score"] for f in s["fields"]]
        self.assertEqual(maxes, sorted(maxes, reverse=True))
        self.assertTrue(s["most_urgent"])
        with self.assertRaises(ToolError):
            call("get_farm_risk_summary", date="2024-06-30")

    def test_weather_observed_then_forecast_and_weekly(self):
        w = call("get_weather", field_id=self.wheat.id)
        sources = [d["source"] for d in w["days"]]
        self.assertEqual(sources[0], "observed")
        self.assertEqual(sources[-1], "forecast")
        self.assertTrue(all(d["date"] <= "2024-05-15" for d in w["days"] if d["source"] == "observed"))
        self.assertEqual(w["units"]["avg_temperature"], "°C")
        weekly = call("get_weather", field_id=self.wheat.id, date_from="2024-04-10")
        self.assertEqual(weekly["aggregation"], "weekly")
        with self.assertRaises(ToolError):
            call("get_weather", field_id=self.wheat.id, variables=["not_a_column"])


class ChartToolTests(ToolTestCase):
    def test_risk_timeline(self):
        r = call("chart_risk_timeline", field_ids=[self.wheat.id, self.wheat2.id], threat="septorioza paskowana")
        self.assertEqual(r["chart"]["$schema"], "https://vega.github.io/schema/vega-lite/v5.json")
        self.assertEqual(set(r["summary"]["fields"]), {self.wheat.name, self.wheat2.name})
        s = r["summary"]["fields"][self.wheat.name]
        self.assertTrue({"max", "max_date", "today_level", "trend"} <= set(s))
        layer_texts = [l["encoding"].get("text", {}).get("value", "") for l in r["chart"]["layer"]]
        self.assertTrue(any(t.startswith("dziś") for t in layer_texts))

    def test_weather_vs_risk_and_farm_overview(self):
        r = call("chart_weather_vs_risk", field_id=self.wheat.id, variable="total_precipitation",
                 threat="septorioza paskowana")
        self.assertIn("weather_sum", r["summary"])
        o = call("chart_farm_overview")
        self.assertEqual(sum(o["summary"]["fields_per_level"].values()), len(devdata.DEV_FIELDS))


class ObservationToolTests(ToolTestCase):
    def _call(self, key="key-00000001", **kw):
        args = dict(field_id=self.wheat.id, category="choroba", threat="septorioza", severity="srednie",
                    note="brunatne plamy z czarnymi kropkami", idempotency_key=key)
        return call("record_observation", **(args | kw))

    def test_idempotent_and_engine_unavailable(self):
        r1 = self._call()
        self.assertTrue(r1["created"])
        self.assertEqual(r1["draft"]["date"], "2024-05-15")
        self.assertEqual(r1["draft"]["threat_code"], "wheat.septoria_leaf_blotch")
        self.assertEqual(r1["reassessment"]["status"], "unavailable")
        r2 = self._call()
        self.assertFalse(r2["created"])
        self.assertEqual(r1["observation_id"], r2["observation_id"])
        self.assertEqual(Observation.objects.count(), 1)

    def test_engine_called_and_failure_keeps_observation(self):
        calls = []
        with mock.patch("assistant.tools.observations.engine_predict",
                        return_value=lambda **kw: calls.append(kw) or 7):
            r = self._call(key="key-00000002", date="2024-05-14")
        self.assertEqual(r["reassessment"]["status"], "ok")
        self.assertEqual(calls, [{"field_ids": [self.wheat.id], "start": dt.date(2024, 5, 14)}])

        def boom(**kw):
            raise RuntimeError("engine down")
        with mock.patch("assistant.tools.observations.engine_predict", return_value=boom):
            r = self._call(key="key-00000003")
        self.assertEqual(r["reassessment"]["status"], "failed")
        self.assertTrue(Observation.objects.filter(idempotency_key="key-00000003").exists())

    def test_future_date_rejected_and_listed(self):
        with self.assertRaises(ToolError):
            self._call(key="key-00000004", date="2024-05-20")
        self._call(key="key-00000005")
        obs = call("get_observations", field_id=self.wheat.id)["observations"]
        self.assertEqual(len(obs), 1)


class SqlToolTests(ToolTestCase):
    MALICIOUS = [
        "DELETE FROM core_risk",
        "SELECT 1; DROP TABLE core_risk",
        "SELECT * FROM core_field /* ; */ ; UPDATE core_field SET name='x'",
        "WITH x AS (DELETE FROM core_risk RETURNING *) SELECT * FROM x",
        "SELECT pg_sleep(10) FROM core_field",
        "SELECT * FROM auth_user",
        "SELECT * FROM assistant_message",
        "SELECT * FROM information_schema.tables",
        "SELECT * INTO new_table FROM core_field",
        "SELECT set_config('statement_timeout','0',false) FROM core_field",
        "COPY core_field TO '/tmp/x'",
        "SELECT * FROM core_field FOR UPDATE",
    ]

    def test_rejects_malicious(self):
        for q in self.MALICIOUS:
            with self.subTest(q=q), self.assertRaises(ToolError):
                sql.validate(q)

    def test_executes_simple_select_with_row_cap(self):
        r = sql.execute("SELECT name, area_ha FROM core_field ORDER BY name", max_rows=2, alias="default")
        self.assertEqual(r["columns"], ["name", "area_ha"])
        self.assertEqual(len(r["rows"]), 2)
        self.assertTrue(r["truncated"])
        r = sql.execute("WITH t AS (SELECT date, score FROM core_risk) SELECT max(date) FROM t", alias="default")
        self.assertTrue(r["rows"][0][0].startswith("2024-"))

    def test_schema_description_generated_from_models(self):
        d = sql.schema_description()
        self.assertIn("core_risk", d)
        self.assertIn("score", d)
        self.assertNotIn("assistant_", d)

    @override_settings(DATABASES={})
    def test_disabled_without_readonly_connection(self):
        with mock.patch.dict("os.environ", {"ASSISTANT_ENABLE_SQL": "1"}):
            self.assertFalse(sql.sql_enabled())


class DomainTests(ToolTestCase):
    def test_levels_and_trend(self):
        self.assertEqual(domain.level(0.1)[1], "niskie")
        self.assertEqual(domain.level(0.5)[1], "średnie")
        self.assertEqual(domain.level(0.9)[1], "wysokie")
        self.assertEqual(domain.trend([0.1, 0.2, 0.4]), "rośnie")
        self.assertEqual(domain.trend([0.5, 0.5, 0.52]), "stały")
        self.assertEqual(domain.rising_days([0.5, 0.4, 0.5, 0.6]), 2)

    def test_resolve_threat_aliases(self):
        m = domain.resolve_threats("widzę brunatne plamy z czarnymi kropkami", devdata.CROP_WHEAT)
        self.assertEqual(m[0].code, "wheat.septoria_leaf_blotch")
        m = domain.resolve_threats("czy grozi mi rdza brunatna?", devdata.CROP_WHEAT)
        self.assertEqual(m[0].code, "wheat.brown_rust")
        self.assertEqual(domain.resolve_threats("jaka będzie pogoda jutro", devdata.CROP_WHEAT), [])


class GuideToolTests(unittest.TestCase):
    """fit_passages without Qdrant; search_guides is covered by test_rag when Qdrant runs."""

    def test_fit_passages_respects_budget(self):
        from assistant.tools.guides import _ntok, fit_passages
        cit = {"type": "guide", "document": "x.pdf", "page": 1}
        mk = lambda i: SimpleNamespace(chunk_id=f"d:{i}", citation=f"Doc s. {i}", section="S", printed_pages=str(i),
                                       pdf_pages=(i, i), kind="text", text="słowo " * 300, to_citation=lambda: cit)
        out = fit_passages([mk(i) for i in range(6)], budget=900)
        self.assertGreaterEqual(len(out), 1)
        self.assertLessEqual(sum(_ntok(p["text"]) for p in out), 900 + 20)
