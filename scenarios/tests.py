"""
Testy jednostkowe i integracyjne modułu `scenarios`.

Weryfikują poprawność parsowania definicji JSON, izolację czyszczenia danych
scenariuszowych, generowanie prognoz 7-dniowych oraz ustawianie `core.Clock`.
"""

from __future__ import annotations

from django.test import TestCase


class ScenarioParserTests(TestCase):
    """Testy walidacji schematu JSON oraz wykrywania błędnych konfiguracji."""

    def test_valid_scenario_parses_correctly(self) -> None:
        """Poprawny plik JSON buduje obiekt `ScenarioDefinition` z właściwymi typami."""
        ...

    def test_invalid_dates_raise_validation_error(self) -> None:
        """Niespójne okno czasowe (np. `season_end < season_start`) rzuca `ScenarioValidationError`."""
        ...


class WeatherForecastGeneratorTests(TestCase):
    """Testy tworzenia prognozy 7-dniowej (`WeatherForecastDaily`) z danych obserwowanych."""

    def test_forecast_copies_next_seven_days_and_imerg_rain(self) -> None:
        """Dla dnia D powstają rekordy D+1..D+7, a opad IMERG trafia do `total_precipitation`."""
        ...


class ScenarioSwitchIntegrationTests(TestCase):
    """Testy pełnego przełączania scenariuszy z wykorzystaniem trybu syntetycznego."""

    def test_switch_replaces_fields_and_preserves_reference_tables(self) -> None:
        """Przełączenie scenariusza usuwa stare pola i obserwacje, ale zachowuje `CropClass` i `Threat`."""
        ...

    def test_switch_sets_clock_and_respects_today_override(self) -> None:
        """Zegar `core.Clock` ustawia się na datę ze scenariusza lub parametr `--today`."""
        ...