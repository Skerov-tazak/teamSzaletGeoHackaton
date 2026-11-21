"""
Testy jednostkowe i integracyjne modułu `scenarios`.

Weryfikują poprawność parsowania definicji JSON, domyślną blokadę braku danych
w `DATA_DIR` (`DataSourceError`), jawny tryb `--allow-synthetic` z emisją ostrzeżeń,
wydłużenie horyzontu pogody do 31 grudnia dla kukurydzy, wywołanie
`engine.precompute_season()` oraz działanie komendy CLI `python manage.py scenario`.
"""

from __future__ import annotations

import io
import json
import tempfile
import warnings
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from assistant.models import Conversation, Message
from core import clock
from core.models import (
    CropClass,
    Field,
    Observation,
    Risk,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
)
from scenarios.exceptions import DataSourceError, ScenarioValidationError
from scenarios.loaders import ReferenceDataLoader, WeatherAndForecastLoader
from scenarios.manager import ScenarioManager, ScenarioRepository
from scenarios.schema import ScenarioParser, SwitchOptions


def _sample_polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [17.640, 50.365],
                [17.648, 50.365],
                [17.648, 50.370],
                [17.640, 50.370],
                [17.640, 50.365],
            ]
        ],
    }


def _sample_scenario_payload() -> dict:
    return {
        "title": "Testowy scenariusz",
        "description": "Opis testowy",
        "region": "Opolskie",
        "window": {
            "season": 2025,
            "season_start": "2025-05-01",
            "season_end": "2025-05-20",
            "clock_today": "2025-05-10",
            "include_previous_season": False,
        },
        "fields": [
            {
                "name": "Pole Testowe 1",
                "crop_code": CropClass.WHEAT,
                "geometry": _sample_polygon(),
            }
        ],
        "observations": [
            {
                "kind": "symptoms",
                "observed_on": "2025-05-09",
                "field_name": "Pole Testowe 1",
                "category": "disease",
                "threat_code": "wheat.septoria_leaf_blotch",
                "severity": 0.8,
                "text": "Plamy na liściach.",
            }
        ],
    }


class ScenarioParserTests(TestCase):
    """Testy walidacji schematu JSON, domyślnych opcji oraz wykrywania błędnych konfiguracji."""

    def test_switch_options_disables_synthetic_data_by_default(self) -> None:
        """Domyślnie `SwitchOptions` blokuje generowanie sztucznych danych."""
        opts = SwitchOptions()
        self.assertFalse(opts.allow_synthetic)

    def test_valid_scenario_parses_correctly(self) -> None:
        """Poprawny słownik/plik JSON buduje obiekt `ScenarioDefinition` z właściwymi typami."""
        definition = ScenarioParser.from_dict(_sample_scenario_payload(), slug="unit_test_case")

        self.assertEqual(definition.slug, "unit_test_case")
        self.assertEqual(definition.window.clock_today, date(2025, 5, 10))
        self.assertFalse(definition.window.include_previous_season)
        self.assertEqual(len(definition.fields), 1)
        self.assertEqual(definition.fields[0].crop_code, CropClass.WHEAT)
        self.assertEqual(len(definition.observations), 1)
        self.assertEqual(definition.observations[0].severity, 0.8)

    def test_invalid_dates_raise_validation_error(self) -> None:
        """Niespójne okno czasowe (`clock_today` poza zakresem sezonu) rzuca `ScenarioValidationError`."""
        payload = _sample_scenario_payload()
        payload["window"]["clock_today"] = "2025-08-01"

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.from_dict(payload, slug="invalid_clock")

    def test_observation_referencing_unknown_field_raises_validation_error(self) -> None:
        """Obserwacja wskazująca nieistniejące pole rzuca `ScenarioValidationError`."""
        payload = _sample_scenario_payload()
        payload["observations"][0]["field_name"] = "Nieistniejące Pole"

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.from_dict(payload, slug="unknown_field_obs")

    def test_apply_overrides_updates_clock_today_and_validates(self) -> None:
        """Metoda `apply_overrides` aktualizuje `clock_today` i odrzuca datę spoza okna."""
        definition = ScenarioParser.from_dict(_sample_scenario_payload(), slug="override_test")

        updated = ScenarioParser.apply_overrides(
            definition, SwitchOptions(today_override=date(2025, 5, 15))
        )
        self.assertEqual(updated.window.clock_today, date(2025, 5, 15))

        with self.assertRaises(ScenarioValidationError):
            ScenarioParser.apply_overrides(
                definition, SwitchOptions(today_override=date(2025, 4, 15))
            )

    def test_built_in_definitions_load_including_wheat_septoria_outbreak(self) -> None:
        """Wbudowany katalog `scenarios/definitions/` ładuje się poprawnie i zawiera `wheat_septoria_outbreak`."""
        repo = ScenarioRepository()
        scenarios = {item.slug: item for item in repo.list_scenarios()}

        self.assertIn("baseline_farm", scenarios)
        self.assertIn("wheat_septoria_outbreak", scenarios)
        self.assertIn("maize_drought_stress", scenarios)


class WeatherForecastGeneratorTests(TestCase):
    """Testy tworzenia prognozy 7-dniowej (`WeatherForecastDaily`) z danych obserwowanych."""

    def test_forecast_copies_next_seven_days_and_imerg_rain(self) -> None:
        """Dla dnia D powstają rekordy D+1..D+7, a opad IMERG trafia do `total_precipitation`."""
        grid = WeatherGrid.objects.create(grid_id="g_test_1", lat=50.36, lon=17.64)
        base_day = date(2025, 5, 1)

        for offset in range(10):
            day = base_day + timedelta(days=offset)
            WeatherDaily.objects.create(
                grid=grid,
                date=day,
                avg_temperature=15.0 + offset,
                total_precipitation=None,
                imerg_total_precipitation=2.5 * offset,
            )

        loader = WeatherAndForecastLoader(data_dir=Path("/nonexistent"))
        created_count = loader.generate_forecast_series(
            grid_ids=[grid.grid_id],
            start=base_day,
            end=base_day + timedelta(days=1),
        )

        self.assertEqual(created_count, 14)  # 2 dni emisji * 7 dni prognozy
        day_plus_3 = WeatherForecastDaily.objects.get(
            grid=grid, issued_on=base_day, date=base_day + timedelta(days=3)
        )
        self.assertEqual(day_plus_3.avg_temperature, 18.0)
        self.assertEqual(day_plus_3.total_precipitation, 7.5)


class ScenarioSwitchIntegrationTests(TestCase):
    """Testy pełnego przełączania scenariuszy, blokady braku danych oraz integracji z CLI."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.defs_dir = Path(self.tmp_dir.name) / "definitions"
        self.defs_dir.mkdir(parents=True, exist_ok=True)
        self.empty_data_dir = Path(self.tmp_dir.name) / "data"
        self.empty_data_dir.mkdir(parents=True, exist_ok=True)

        wheat_class, _ = CropClass.objects.update_or_create(
            code=CropClass.WHEAT, defaults={"name": "Wheat"}
        )
        self.threat, _ = Threat.objects.update_or_create(
            code="wheat.septoria_leaf_blotch",
            defaults={
                "crop": wheat_class,
                "name": "septorioza paskowana liści pszenicy",
                "category": Threat.Category.FUNGAL,
                "source": "test",
            },
        )

        (self.defs_dir / "case_a.json").write_text(
            json.dumps(_sample_scenario_payload()), encoding="utf-8"
        )

        payload_b = _sample_scenario_payload()
        payload_b["title"] = "Scenariusz B"
        payload_b["window"]["clock_today"] = "2025-05-12"
        payload_b["fields"][0]["name"] = "Pole Testowe B"
        payload_b["observations"][0]["field_name"] = "Pole Testowe B"
        (self.defs_dir / "case_b.json").write_text(json.dumps(payload_b), encoding="utf-8")

        ref_loader = ReferenceDataLoader(data_dir=self.empty_data_dir)
        self.manager = ScenarioManager(
            repository=ScenarioRepository(definitions_dir=self.defs_dir),
            reference_loader=ref_loader,
        )
        self.manager.field_loader.data_dir = self.empty_data_dir
        self.manager.weather_loader.data_dir = self.empty_data_dir

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_without_datasets_refuses_by_default(
        self, _mock_call_command, mock_precompute
    ) -> None:
        """Brak plików w `DATA_DIR` bez flagi `allow_synthetic=True` rzuca `DataSourceError`."""
        with self.assertRaises(DataSourceError):
            self.manager.switch_to("case_a")

        self.assertEqual(Field.objects.count(), 0)
        self.assertEqual(mock_precompute.call_count, 0)

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_with_allow_synthetic_emits_loud_warning_and_extends_to_dec_31(
        self, _mock_call_command, mock_precompute
    ) -> None:
        """Jawne `allow_synthetic=True` emituje ostrzeżenie, zasila pogodę do 31 grudnia i woła `precompute_season()`."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            report = self.manager.switch_to(
                "case_a", options=SwitchOptions(allow_synthetic=True)
            )

        self.assertTrue(len(report.warnings) > 0)
        self.assertTrue(any("SYNTHETIC DATA" in w for w in report.warnings))
        self.assertTrue(any(issubclass(w.category, UserWarning) for w in caught))

        # Nawet gdy season_end to 2025-05-20, pogoda i prognozy obejmują cały rok do 31 grudnia (dla kukurydzy)
        self.assertTrue(WeatherDaily.objects.filter(date=date(2025, 12, 31)).exists())
        self.assertTrue(WeatherForecastDaily.objects.filter(issued_on=date(2025, 12, 31)).exists())
        self.assertEqual(mock_precompute.call_count, 1)

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_replaces_fields_and_preserves_reference_tables(
        self, _mock_call_command, mock_precompute
    ) -> None:
        """Przełączenie scenariusza usuwa stare pola i obserwacje, ale zachowuje `CropClass` i `Threat`."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            report_a = self.manager.switch_to(
                "case_a", options=SwitchOptions(allow_synthetic=True)
            )

        self.assertEqual(report_a.fields_created, 1)
        self.assertEqual(report_a.risk_rows_written, 20)
        self.assertEqual(Field.objects.count(), 1)
        self.assertEqual(Field.objects.first().name, "Pole Testowe 1")

        fld = Field.objects.first()
        Risk.objects.create(
            field=fld,
            threat=self.threat,
            date=date(2025, 5, 10),
            score=0.5,
            explanation={"version": 1, "level": "medium"},
        )
        conv = Conversation.objects.create(title="Stara rozmowa")
        Message.objects.create(conversation=conv, role="user", text="Cześć")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            report_b = self.manager.switch_to(
                "case_b", options=SwitchOptions(reset_chat=True, allow_synthetic=True)
            )

        self.assertEqual(report_b.scenario_slug, "case_b")
        self.assertEqual(Field.objects.count(), 1)
        self.assertEqual(Field.objects.first().name, "Pole Testowe B")
        self.assertEqual(Observation.objects.count(), 1)
        self.assertEqual(Risk.objects.count(), 0)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(CropClass.objects.count(), 21)
        self.assertTrue(Threat.objects.filter(code="wheat.septoria_leaf_blotch").exists())
        self.assertEqual(mock_precompute.call_count, 2)

    @patch("engine.precompute_season", return_value=20)
    @patch("scenarios.loaders.call_command")
    def test_switch_sets_clock_and_respects_today_override(
        self, _mock_call_command, _mock_precompute
    ) -> None:
        """Zegar `core.Clock` ustawia się na datę ze scenariusza lub parametr `--today`."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.manager.switch_to("case_a", options=SwitchOptions(allow_synthetic=True))
            self.assertEqual(clock.today(), date(2025, 5, 10))

            self.manager.switch_to(
                "case_a",
                options=SwitchOptions(today_override=date(2025, 5, 18), allow_synthetic=True),
            )
            self.assertEqual(clock.today(), date(2025, 5, 18))

    @patch("engine.precompute_season", return_value=10)
    @patch("scenarios.loaders.call_command")
    def test_cli_list_status_and_switch_commands(self, _mock_call_command, _mock_precompute) -> None:
        """Komenda `python manage.py scenario` obsługuje `list`, `validate`, `switch` (z `--allow-synthetic`) i `status`."""
        from core.management.commands.scenario import Command as ScenarioCommand

        cmd = ScenarioCommand(manager=self.manager)
        out = io.StringIO()
        err = io.StringIO()
        cmd.stdout = out
        cmd.stderr = err

        call_command(cmd, "list")
        self.assertIn("case_a", out.getvalue())

        out.truncate(0)
        out.seek(0)
        call_command(cmd, "validate", "case_a")
        self.assertIn("jest poprawny", out.getvalue())

        # Bez flagi --allow-synthetic przy pustym DATA_DIR komenda CLI zgłasza CommandError
        with self.assertRaises(CommandError):
            call_command(cmd, "switch", "case_a")

        out.truncate(0)
        out.seek(0)
        err.truncate(0)
        err.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            call_command(cmd, "switch", "case_a", "--today", "2025-05-14", "--allow-synthetic")

        self.assertIn("Clock.today = 2025-05-14", out.getvalue())
        self.assertIn("SYNTHETIC DATA", err.getvalue())

        out.truncate(0)
        out.seek(0)
        call_command(cmd, "status")
        self.assertIn("2025-05-14", out.getvalue())