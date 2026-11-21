"""
Fasada zarządzająca cyklem życia scenariuszy symulacji (`ScenarioManager`).

Odpowiada za odkrywanie definicji JSON, atomowe czyszczenie danych poprzedniego
przypadku testowego, orkiestrację loaderów z `scenarios.loaders`, ustawienie zegara
`core.Clock` oraz prekomputację ryzyk całego sezonu przez `engine.precompute_season()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import Max, Min

import engine
from assistant.models import Conversation, Message
from core import clock
from core.models import (
    Clock,
    Field,
    FieldCropYear,
    Observation,
    Risk,
    WeatherDaily,
    WeatherGrid,
)
from scenarios.exceptions import ScenarioNotFoundError, ScenarioValidationError
from scenarios.loaders import (
    FieldAndSoilLoader,
    ObservationLoader,
    ReferenceDataLoader,
    WeatherAndForecastLoader,
)
from scenarios.schema import ScenarioDefinition, ScenarioParser, SwitchOptions

DEFAULT_DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"


@dataclass(frozen=True)
class DatabaseStatus:
    """Migawka aktualnego stanu bazy danych i zegara symulacji."""

    clock_today: date | None
    fields_count: int
    weather_grids_count: int
    weather_daily_range: tuple[date, date] | None
    observations_count: int
    risks_count: int
    conversations_count: int


@dataclass(frozen=True)
class SwitchReport:
    """Podsumowanie operacji przełączenia bazy na wybrany scenariusz."""

    scenario_slug: str
    clock_today: date
    fields_created: int
    weather_daily_rows: int
    weather_hourly_rows: int
    forecast_rows: int
    observations_created: int
    risk_rows_written: int
    warnings: list[str] = field(default_factory=list)


class ScenarioRepository:
    """Repozytorium odczytujące i walidujące definicje scenariuszy z plików `.json`."""

    def __init__(self, definitions_dir: Path | None = None) -> None:
        self.definitions_dir = (
            Path(definitions_dir) if definitions_dir is not None else DEFAULT_DEFINITIONS_DIR
        )

    def list_scenarios(self) -> list[ScenarioDefinition]:
        """Zwraca posortowaną listę wszystkich poprawnych scenariuszy z katalogu definicji."""
        if not self.definitions_dir.exists():
            return []

        definitions: list[ScenarioDefinition] = []
        for path in sorted(self.definitions_dir.glob("*.json")):
            definitions.append(self._load_file(path))
        return definitions

    def get_scenario(self, slug: str) -> ScenarioDefinition:
        """Wczytuje i waliduje pojedynczy scenariusz na podstawie jego identyfikatora (`slug`)."""
        clean_slug = slug.removesuffix(".json").strip()
        target = self.definitions_dir / f"{clean_slug}.json"
        if not target.is_file():
            available = [p.stem for p in sorted(self.definitions_dir.glob("*.json"))] if self.definitions_dir.exists() else []
            available_hint = ", ".join(available) if available else "brak"
            raise ScenarioNotFoundError(
                f"Nie znaleziono scenariusza '{clean_slug}' w '{self.definitions_dir}'. "
                f"Dostępne scenariusze: {available_hint}."
            )
        return self._load_file(target)

    @staticmethod
    def _load_file(path: Path) -> ScenarioDefinition:
        """Deserializuje plik JSON do obiektu `ScenarioDefinition`."""
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenarioValidationError(
                f"Nie udało się odczytać pliku scenariusza '{path.name}': {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ScenarioValidationError(
                f"Plik scenariusza '{path.name}' musi zawierać obiekt JSON na najwyższym poziomie."
            )

        return ScenarioParser.from_dict(payload, slug=path.stem)


class DatabaseStateCleaner:
    """Czyści dane poprzedniego przypadku testowego z zachowaniem tabel referencyjnych."""

    @staticmethod
    def reset_scenario_state(*, reset_chat: bool = False) -> None:
        """Usuwa rekordy pól, obserwacji i ryzyk (oraz opcjonalnie historię czatu)."""
        Risk.objects.all().delete()
        Observation.objects.all().delete()
        FieldCropYear.objects.all().delete()
        Field.objects.all().delete()

        if reset_chat:
            Message.objects.all().delete()
            Conversation.objects.all().delete()


class ScenarioManager:
    """Główny kontroler przełączający stan bazy danych na wybrany scenariusz symulacji."""

    def __init__(
        self,
        repository: ScenarioRepository | None = None,
        cleaner: DatabaseStateCleaner | None = None,
        reference_loader: ReferenceDataLoader | None = None,
        field_loader: FieldAndSoilLoader | None = None,
        weather_loader: WeatherAndForecastLoader | None = None,
        observation_loader: ObservationLoader | None = None,
    ) -> None:
        self.repository = repository or ScenarioRepository()
        self.cleaner = cleaner or DatabaseStateCleaner()
        self.reference_loader = reference_loader or ReferenceDataLoader()
        self.field_loader = field_loader or FieldAndSoilLoader()
        self.weather_loader = weather_loader or WeatherAndForecastLoader()
        self.observation_loader = observation_loader or ObservationLoader()

    def get_status(self) -> DatabaseStatus:
        """Zwraca podsumowanie aktualnego stanu bazy danych oraz zegara `core.Clock`."""
        clock_obj = Clock.objects.filter(pk=1).first()
        weather_agg = WeatherDaily.objects.aggregate(min_d=Min("date"), max_d=Max("date"))
        weather_range = (
            (weather_agg["min_d"], weather_agg["max_d"])
            if weather_agg["min_d"] is not None and weather_agg["max_d"] is not None
            else None
        )

        return DatabaseStatus(
            clock_today=clock_obj.today if clock_obj is not None else None,
            fields_count=Field.objects.count(),
            weather_grids_count=WeatherGrid.objects.count(),
            weather_daily_range=weather_range,
            observations_count=Observation.objects.count(),
            risks_count=Risk.objects.count(),
            conversations_count=Conversation.objects.count(),
        )

    def switch_to(self, slug: str, options: SwitchOptions | None = None) -> SwitchReport:
        """Atomowo przełącza bazę danych na wskazany scenariusz testowy."""
        opts = options or SwitchOptions()
        raw_definition = self.repository.get_scenario(slug)
        definition = ScenarioParser.apply_overrides(raw_definition, opts)

        effective_start = (
            min(definition.window.season_start, date(definition.window.season - 1, 1, 1))
            if definition.window.include_previous_season
            else definition.window.season_start
        )
        effective_today = definition.window.clock_today
        collected_warnings: list[str] = []

        with transaction.atomic():
            # 1. Reset poprzedniego stanu scenariusza (z zachowaniem CropClass, Threat, SoilCell)
            self.cleaner.reset_scenario_state(reset_chat=opts.reset_chat)

            # 2. Synchronizacja tabel referencyjnych (CropClass + Threat)
            self.reference_loader.ensure_reference_data()

            # 3. Dopasowanie siatek pogodowych oraz utworzenie pól, gleby H3 i historii upraw 2020–2024
            grids_by_field_name = self.weather_loader.resolve_grids_for_specs(
                definition.fields,
                region=definition.region,
                allow_synthetic=opts.allow_synthetic,
                warnings_sink=collected_warnings,
            )
            created_fields = self.field_loader.load_fields(
                definition.fields,
                region=definition.region,
                grids_by_field_name=grids_by_field_name,
                allow_synthetic=opts.allow_synthetic,
                warnings_sink=collected_warnings,
            )
            fields_by_name = {f.name: f for f in created_fields}

            # 4. Horyzont pogody: co najmniej do 31 grudnia roku sezonu (dla kukurydzy) + 7 dni prognozy
            forecast_days = getattr(clock, "FORECAST_DAYS", 7)
            weather_horizon_end = max(
                definition.window.season_end,
                date(definition.window.season, 12, 31),
            )
            forecast_horizon_end = weather_horizon_end + timedelta(days=forecast_days)
            years_to_load = list(range(effective_start.year, forecast_horizon_end.year + 1))

            grid_ids, daily_rows, hourly_rows = self.weather_loader.load_weather_for_fields(
                fields=created_fields,
                region=definition.region,
                years=years_to_load,
                overrides=definition.weather_overrides,
                keep_weather=opts.keep_weather,
                allow_synthetic=opts.allow_synthetic,
                warnings_sink=collected_warnings,
            )

            # 5. Wygenerowanie 7-dniowych prognoz (WeatherForecastDaily)
            forecast_rows = self.weather_loader.generate_forecast_series(
                grid_ids=grid_ids,
                start=effective_start,
                end=weather_horizon_end,
                horizon_days=forecast_days,
            )

            # 6. Zapis początkowych obserwacji rolnika
            observations_created = self.observation_loader.load_observations(
                definition.observations,
                fields_by_name=fields_by_name,
            )

            # 7. Ustawienie zegara symulacji (core.Clock) i prekomputacja ryzyk całego sezonu
            # Zegar zapisujemy bezpośrednio w modelu `core.Clock` (id=1), bo moduł `core.clock`
            # nie udostępnia funkcji `set_today`; `clock.today()` odczytuje tę samą tabelę.
            Clock.objects.update_or_create(pk=1, defaults={"today": effective_today})

            risk_rows_written = 0
            if not opts.skip_predict:
                result = engine.precompute_season()
                risk_rows_written = result if isinstance(result, int) else Risk.objects.count()

        return SwitchReport(
            scenario_slug=definition.slug,
            clock_today=effective_today,
            fields_created=len(created_fields),
            weather_daily_rows=daily_rows,
            weather_hourly_rows=hourly_rows,
            forecast_rows=forecast_rows,
            observations_created=observations_created,
            risk_rows_written=risk_rows_written,
            warnings=collected_warnings,
        )