"""
Loadery danych wejściowych dla modułu `scenarios`.

Domyślnie wymagają kompletnych plików źródłowych w `settings.DATA_DIR` i rzucają
`DataSourceError` przy jakimkolwiek braku. Tryb syntetyczny uruchamia się wyłącznie
po jawnym przekazaniu `allow_synthetic=True` i każdorazowo emituje głośne ostrzeżenie.
"""

from __future__ import annotations

import logging
import math
import random
import warnings
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import h3
import pandas as pd
from django.conf import settings
from django.core.management import call_command
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from core.models import (
    CropClass,
    Field,
    FieldCropYear,
    Observation,
    SoilCell,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
    WeatherHourly,
)
from scenarios.exceptions import DataSourceError
from scenarios.schema import FieldSpec, ObservationSpec

logger = logging.getLogger(__name__)

CLMS_CROP_NAMES: dict[int, str] = {
    1110: "Wheat",
    1120: "Barley",
    1130: "Maize",
    1140: "Rice",
    1150: "Other cereals",
    1210: "Fresh Vegetables",
    1220: "Dry pulses",
    1310: "Potatoes",
    1320: "Sugar Beet",
    1410: "Sunflower",
    1420: "Soybeans",
    1430: "Rapeseed and turnip rapeseed",
    1440: "Flax, cotton and hemp",
    2110: "Grapes",
    2210: "Olives",
    2310: "Fruits",
    2320: "Nuts",
    3100: "Temporary grassland",
    3200: "Permanent grassland",
    4000: "Fallow land",
    9999: "Other / Non-arable",
}


def _emit_synthetic_warning(reason: str, warnings_sink: list[str] | None = None) -> None:
    """Loguje głośne ostrzeżenie oraz dopisuje je do listy ostrzeżeń raportu CLI."""
    message = (
        f"UWAGA [SYNTHETIC DATA]: {reason} "
        "Używam wygenerowanych danych zastępczych (--allow-synthetic)."
    )
    logger.warning(message)
    warnings.warn(message, UserWarning, stacklevel=2)
    if warnings_sink is not None and message not in warnings_sink:
        warnings_sink.append(message)


class ReferenceDataLoader:
    """Synchronizuje tabele słownikowe (`CropClass`, `Threat`)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)

    def ensure_reference_data(self) -> None:
        """Idempotentnie uzupełnia 21 klas upraw CLMS oraz katalog zagrożeń."""
        for code, name in CLMS_CROP_NAMES.items():
            CropClass.objects.update_or_create(code=code, defaults={"name": name})

        if not Threat.objects.exists():
            try:
                call_command("engine_load_threats")
            except Exception as exc:
                raise DataSourceError(
                    "Nie udało się załadować katalogu zagrożeń (`engine_load_threats`). "
                    "Upewnij się, że submoduły i plik ryzyka_zebrane.xlsx są dostępne."
                ) from exc


class FieldAndSoilLoader:
    """Tworzy pola (`Field`), przypisuje heksagony glebowe (`SoilCell`) i historię upraw (`FieldCropYear`)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)
        self._to_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)

    def load_fields(
        self,
        field_specs: list[FieldSpec],
        region: str,
        *,
        grids_by_field_name: dict[str, WeatherGrid] | None = None,
        allow_synthetic: bool = False,
        warnings_sink: list[str] | None = None,
    ) -> list[Field]:
        """Tworzy rekordy `Field` wraz z danymi glebowymi i historią upraw 2020–2024."""
        if grids_by_field_name is None:
            weather_helper = WeatherAndForecastLoader(data_dir=self.data_dir)
            grids_by_field_name = weather_helper.resolve_grids_for_specs(
                field_specs,
                region=region,
                allow_synthetic=allow_synthetic,
                warnings_sink=warnings_sink,
            )

        all_h3: set[str] = set()
        prepared: list[tuple[FieldSpec, float, list[str]]] = []

        for spec in field_specs:
            geom_4326 = shape(spec.geometry)
            geom_2180 = shapely_transform(self._to_2180.transform, geom_4326)
            area_ha = round(geom_2180.area / 10_000.0, 4)

            cells = self._polygon_to_h3(spec.geometry)
            all_h3.update(cells)
            prepared.append((spec, area_ha, cells))

        self._ensure_soil_cells(
            sorted(all_h3),
            region=region,
            allow_synthetic=allow_synthetic,
            warnings_sink=warnings_sink,
        )

        created_fields: list[Field] = []
        for idx, (spec, area_ha, cells) in enumerate(prepared):
            crop_obj = CropClass.objects.get(code=spec.crop_code)
            centroid = shape(spec.geometry).centroid
            field = Field.objects.create(
                name=spec.name,
                crop=crop_obj,
                geometry=spec.geometry,
                area_ha=area_ha,
                centroid_lat=round(float(centroid.y), 6),
                centroid_lon=round(float(centroid.x), 6),
                weather_grid=grids_by_field_name[spec.name],
                h3_cells=cells,
            )
            self._load_crop_history(
                field=field,
                spec=spec,
                field_index=idx,
                region=region,
                allow_synthetic=allow_synthetic,
                warnings_sink=warnings_sink,
            )
            created_fields.append(field)

        return created_fields

    @staticmethod
    def _polygon_to_h3(geojson_geom: dict[str, Any], resolution: int = 10) -> list[str]:
        """Wyznacza listę komórek H3 (poziom 10) pokrywających geometrię pola."""
        geom = shape(geojson_geom)
        polygons = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        cells: set[str] = set()

        for poly in polygons:
            outer = [(lat, lon) for lon, lat in poly.exterior.coords]
            holes = [[(lat, lon) for lon, lat in ring.coords] for ring in poly.interiors]
            h3_poly = h3.LatLngPoly(outer, *holes)
            cells.update(h3.polygon_to_cells(h3_poly, res=resolution))

        if not cells:
            centroid = geom.centroid
            cells.add(h3.latlng_to_cell(centroid.y, centroid.x, resolution))

        return sorted(cells)

    def _find_soil_rasters(self, region: str) -> list[Path]:
        """Szuka rastrów glebowych dla regionu w `DATA_DIR`."""
        if not self.data_dir.exists():
            return []
        region_lower = region.lower()
        return sorted(
            p
            for p in self.data_dir.rglob("*.tif")
            if "soil" in str(p).lower() and region_lower in str(p).lower()
        )

    def _ensure_soil_cells(
        self,
        h3_indices: list[str],
        region: str,
        *,
        allow_synthetic: bool,
        warnings_sink: list[str] | None,
    ) -> None:
        """Wczytuje właściwości gleby z `DATA_DIR` lub (tylko z flagą) generuje zróżnicowane wartości."""
        missing = [
            idx
            for idx in h3_indices
            if not SoilCell.objects.filter(pk=idx).exists()
        ]
        if not missing:
            return

        soil_rasters = self._find_soil_rasters(region)
        if soil_rasters:
            self._load_soil_from_rasters(missing, soil_rasters)
            return

        if not allow_synthetic:
            raise DataSourceError(
                f"Brak rastrów glebowych dla regionu '{region}' w katalogu '{self.data_dir}'. "
                "Uzupełnij pliki w DATA_DIR lub uruchom komendę z flagą --allow-synthetic."
            )

        _emit_synthetic_warning(
            f"Brak plików glebowych dla regionu '{region}' w '{self.data_dir}'.",
            warnings_sink,
        )

        valid_cols = {f.attname for f in SoilCell._meta.concrete_fields}
        pk_name = SoilCell._meta.pk.attname
        cells_to_create: list[SoilCell] = []

        for h3_idx in missing:
            rng = random.Random(f"soil:{h3_idx}")
            sand = round(rng.uniform(22.0, 58.0), 1)
            clay = round(rng.uniform(10.0, 32.0), 1)
            silt = round(max(5.0, 100.0 - sand - clay), 1)
            raw_values: dict[str, Any] = {
                pk_name: h3_idx,
                "h3_index": h3_idx,
                "sand": sand,
                "silt": silt,
                "clay": clay,
                "ph": round(rng.uniform(5.6, 7.2), 2),
                "organic_carbon": round(rng.uniform(1.1, 2.8), 2),
                "soc": round(rng.uniform(1.1, 2.8), 2),
                "bulk_density": round(rng.uniform(1.25, 1.55), 2),
            }
            filtered = {k: v for k, v in raw_values.items() if k in valid_cols}
            cells_to_create.append(SoilCell(**filtered))

        SoilCell.objects.bulk_create(cells_to_create, ignore_conflicts=True)

    def _load_soil_from_rasters(self, h3_indices: list[str], rasters: list[Path]) -> None:
        """Próbkuje rastry glebowe w centroidach komórek H3 i zapisuje `SoilCell`."""
        try:
            import rasterio
        except ImportError as exc:
            raise DataSourceError(
                "Brak zainstalowanej biblioteki `rasterio` wymaganej do odczytu rastrów z DATA_DIR."
            ) from exc

        valid_cols = {f.attname for f in SoilCell._meta.concrete_fields}
        pk_name = SoilCell._meta.pk.attname
        records: dict[str, dict[str, Any]] = {
            idx: {pk_name: idx, "h3_index": idx} for idx in h3_indices
        }

        for raster_path in rasters:
            stem = raster_path.stem.lower()
            target_col = next(
                (col for col in ("sand", "silt", "clay", "ph", "organic_carbon", "soc", "bulk_density") if col in stem),
                None,
            )
            if target_col is None or target_col not in valid_cols:
                continue

            with rasterio.open(raster_path) as src:
                to_raster = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                coords = []
                for idx in h3_indices:
                    lat, lon = h3.cell_to_latlng(idx)
                    coords.append(to_raster.transform(lon, lat))
                for idx, val in zip(h3_indices, src.sample(coords)):
                    scalar = float(val[0])
                    if not math.isnan(scalar) and (src.nodata is None or scalar != src.nodata):
                        records[idx][target_col] = round(scalar, 3)

        SoilCell.objects.bulk_create(
            [SoilCell(**{k: v for k, v in rec.items() if k in valid_cols}) for rec in records.values()],
            ignore_conflicts=True,
        )

    @staticmethod
    def _save_crop_year(field: Field, year: int, shares: dict[str, float]) -> None:
        """Zapisuje udziały upraw dla pary (pole, rok), niezależnie od układu tabeli `FieldCropYear`.

        Nazwa kolumny z udziałami nie jest zakodowana na sztywno: wykrywamy ją z metadanych modelu.
        Obsługiwane układy:
          1. jeden wiersz na (pole, rok) z jedną kolumną `JSONField` ({kod: udział});
          2. jeden wiersz na (pole, rok, uprawa) z kluczem obcym do `CropClass` i liczbową kolumną udziału.
        """
        from django.db import models as dj_models

        meta = FieldCropYear._meta
        concrete = [f for f in meta.concrete_fields if not f.primary_key]

        json_cols = [f for f in concrete if isinstance(f, dj_models.JSONField)]
        if len(json_cols) == 1:
            FieldCropYear.objects.update_or_create(
                field=field,
                year=year,
                defaults={json_cols[0].name: shares},
            )
            return

        crop_fk = next(
            (
                f
                for f in concrete
                if isinstance(f, dj_models.ForeignKey) and f.related_model is CropClass
            ),
            None,
        )
        share_col = next(
            (
                f
                for f in concrete
                if isinstance(f, (dj_models.FloatField, dj_models.DecimalField))
                and f.name not in {"year"}
            ),
            None,
        )
        if crop_fk is not None and share_col is not None:
            FieldCropYear.objects.filter(field=field, year=year).delete()
            for code, share in shares.items():
                FieldCropYear.objects.create(
                    **{
                        "field": field,
                        "year": year,
                        crop_fk.name: CropClass.objects.get(code=int(code)),
                        share_col.name: share,
                    }
                )
            return

        raise DataSourceError(
            "Nie rozpoznano układu modelu `FieldCropYear` (oczekiwano jednej kolumny JSONField "
            f"albo pary FK->CropClass + kolumna liczbowa). Kolumny: {[f.name for f in concrete]}."
        )

    def _load_crop_history(
        self,
        field: Field,
        spec: FieldSpec,
        field_index: int,
        region: str,
        *,
        allow_synthetic: bool,
        warnings_sink: list[str] | None,
    ) -> None:
        """Zapisuje historię upraw z lat 2020–2024 do `FieldCropYear`.

        Lata zdefiniowane w `spec.crop_history` mają pierwszeństwo; brakujące lata
        uzupełniane są z rastrów z `DATA_DIR` lub (tylko z flagą) danymi syntetycznymi.
        """
        target_years = [2020, 2021, 2022, 2023, 2024]

        explicit: dict[int, dict[str, float]] = {}
        if spec.crop_history:
            for year in target_years:
                crops_map = spec.crop_history.get(year) or spec.crop_history.get(str(year))  # type: ignore[call-overload]
                if crops_map:
                    explicit[year] = {str(k): float(v) for k, v in crops_map.items()}

        for year, shares in explicit.items():
            self._save_crop_year(field, year, shares)

        missing_years = [y for y in target_years if y not in explicit]
        if not missing_years:
            return

        crop_rasters = self._find_crop_rasters(region, missing_years)
        if len(crop_rasters) == len(missing_years):
            self._load_crop_history_from_rasters(field, crop_rasters)
            return

        if not allow_synthetic:
            not_found = [y for y in missing_years if y not in crop_rasters]
            raise DataSourceError(
                f"Brak rastrów historii upraw dla regionu '{region}' (lata: {not_found}) w '{self.data_dir}'. "
                "Uzupełnij pliki w DATA_DIR, zdefiniuj `crop_history` w JSON lub użyj --allow-synthetic."
            )

        _emit_synthetic_warning(
            f"Brak pełnych rastrów historii upraw (2020–2024) dla '{field.name}' w '{self.data_dir}'.",
            warnings_sink,
        )

        rotations = [
            [1110, 1430, 1110, 1130, 1430],
            [1130, 1110, 1320, 1110, 1430],
            [1430, 1110, 1120, 1310, 1110],
        ]
        chosen = rotations[field_index % len(rotations)]
        for year, code in zip(target_years, chosen):
            if year in explicit:
                continue
            self._save_crop_year(field, year, {str(code): 1.0})

    def _find_crop_rasters(self, region: str, years: list[int]) -> dict[int, Path]:
        """Zwraca mapę `{rok: ścieżka_rastra}` wyłącznie dla lat odnalezionych w `DATA_DIR`."""
        if not self.data_dir.exists():
            return {}
        found: dict[int, Path] = {}
        region_lower = region.lower()
        for year in years:
            matches = sorted(
                p
                for p in self.data_dir.rglob("*.tif")
                if str(year) in p.name and region_lower in str(p).lower() and "soil" not in str(p).lower()
            )
            if matches:
                found[year] = matches[0]
        return found

    def _load_crop_history_from_rasters(self, field: Field, rasters_by_year: dict[int, Path]) -> None:
        """Wyznacza udziały klas upraw w komórkach H3 pola na podstawie rastrów z `DATA_DIR`."""
        try:
            import rasterio
        except ImportError as exc:
            raise DataSourceError(
                "Brak zainstalowanej biblioteki `rasterio` wymaganej do odczytu rastrów upraw."
            ) from exc

        for year, raster_path in sorted(rasters_by_year.items()):
            with rasterio.open(raster_path) as src:
                to_raster = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                coords = [to_raster.transform(*reversed(h3.cell_to_latlng(idx))) for idx in field.h3_cells]
                counts: dict[str, int] = {}
                total = 0
                for val in src.sample(coords):
                    code = int(val[0])
                    if code in CLMS_CROP_NAMES:
                        counts[str(code)] = counts.get(str(code), 0) + 1
                        total += 1
                if total > 0:
                    shares = {k: round(v / total, 4) for k, v in counts.items()}
                    self._save_crop_year(field, year, shares)


class WeatherAndForecastLoader:
    """Ładuje pogodę (`WeatherDaily`, `WeatherHourly`), aplikuje nadpisania i buduje prognozę 7-dniową."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)

    def resolve_grids_for_specs(
        self,
        field_specs: list[FieldSpec],
        region: str,
        *,
        allow_synthetic: bool = False,
        warnings_sink: list[str] | None = None,
    ) -> dict[str, WeatherGrid]:
        """Dopasowuje lub (tylko z flagą) tworzy komórki `WeatherGrid` dla każdego `FieldSpec`."""
        if not WeatherGrid.objects.exists():
            self._bootstrap_grids_from_data_dir(region)

        existing_grids = list(WeatherGrid.objects.all())
        if existing_grids:
            assigned: dict[str, WeatherGrid] = {}
            for spec in field_specs:
                centroid = shape(spec.geometry).centroid
                nearest = min(
                    existing_grids,
                    key=lambda g: (g.lat - centroid.y) ** 2 + (g.lon - centroid.x) ** 2,
                )
                assigned[spec.name] = nearest
            return assigned

        if not allow_synthetic:
            raise DataSourceError(
                f"Brak komórek siatki pogodowej (`WeatherGrid`) w bazie oraz w '{self.data_dir}'. "
                "Uzupełnij dane pogodowe w DATA_DIR lub użyj flagi --allow-synthetic."
            )

        _emit_synthetic_warning(
            f"Brak siatki pogodowej `WeatherGrid` w bazie i w '{self.data_dir}'.",
            warnings_sink,
        )

        assigned_syn: dict[str, WeatherGrid] = {}
        for idx, spec in enumerate(field_specs, start=1):
            centroid = shape(spec.geometry).centroid
            grid, _ = WeatherGrid.objects.get_or_create(
                grid_id=f"syn_grid_{idx}",
                defaults={"lat": round(centroid.y, 4), "lon": round(centroid.x, 4)},
            )
            assigned_syn[spec.name] = grid
        return assigned_syn

    def load_weather_for_fields(
        self,
        fields: list[Field],
        region: str,
        years: list[int],
        overrides: list[dict[str, Any]],
        *,
        keep_weather: bool = False,
        allow_synthetic: bool = False,
        warnings_sink: list[str] | None = None,
    ) -> tuple[list[str], int, int]:
        """Ładuje spójny szereg pogodowy dla wszystkich lat i nakłada `weather_overrides`."""
        unique_grids: dict[str, WeatherGrid] = {}
        for fld in fields:
            if fld.weather_grid is not None:
                unique_grids[fld.weather_grid.grid_id] = fld.weather_grid

        grids = list(unique_grids.values())
        grid_ids = [g.grid_id for g in grids]

        for grid in grids:
            if keep_weather and self._has_complete_weather(grid.grid_id, years):
                continue

            WeatherDaily.objects.filter(grid=grid, date__year__in=years).delete()
            WeatherHourly.objects.filter(grid=grid, utc_time__year__in=years).delete()

            # Weryfikacja fail-fast wszystkich lat przed zapisem — nigdy nie mieszamy lat prawdziwych z fałszywymi
            archives_by_year = self._collect_complete_archives(region=region, years=years)
            if archives_by_year is not None:
                self._load_grid_from_archives(grid_id=grid.grid_id, archives_by_year=archives_by_year)
            else:
                if not allow_synthetic:
                    missing = self._describe_missing_archives(region=region, years=years)
                    raise DataSourceError(
                        f"Brak kompletnych archiwów pogodowych dla regionu '{region}' (lata: {years}) "
                        f"w '{self.data_dir}'. Brakujące zestawy: {', '.join(missing)}. "
                        "Uzupełnij pliki w DATA_DIR lub użyj flagi --allow-synthetic."
                    )

                _emit_synthetic_warning(
                    f"Brak kompletnych archiwów pogodowych ZIP dla regionu '{region}' (lata: {years}) w '{self.data_dir}'.",
                    warnings_sink,
                )
                self._generate_synthetic_weather(grid=grid, years=years)

        if overrides:
            self._apply_weather_overrides(grid_ids=grid_ids, overrides=overrides)

        daily_count = WeatherDaily.objects.filter(grid_id__in=grid_ids, date__year__in=years).count()
        hourly_count = WeatherHourly.objects.filter(grid_id__in=grid_ids, utc_time__year__in=years).count()
        return grid_ids, daily_count, hourly_count

    def _bootstrap_grids_from_data_dir(self, region: str) -> None:
        """Wczytuje współrzędne `WeatherGrid` z pierwszego dostępnego archiwum ZIP w `DATA_DIR`."""
        if not self.data_dir.exists():
            return
        region_lower = region.lower()
        zips = sorted(
            p for p in self.data_dir.rglob("*.zip") if "daily" in p.name.lower() and region_lower in p.name.lower()
        )
        if not zips:
            return

        with zipfile.ZipFile(zips[0]) as zf:
            parquet_names = [n for n in zf.namelist() if n.endswith(".parquet")]
            if not parquet_names:
                return
            with zf.open(parquet_names[0]) as fh:
                df = pd.read_parquet(fh)

        if {"grid_id", "lat", "lon"}.issubset(df.columns):
            unique_grids = df[["grid_id", "lat", "lon"]].drop_duplicates(subset=["grid_id"])
            WeatherGrid.objects.bulk_create(
                [
                    WeatherGrid(grid_id=str(row.grid_id), lat=float(row.lat), lon=float(row.lon))
                    for row in unique_grids.itertuples()
                ],
                ignore_conflicts=True,
            )

    @staticmethod
    def _has_complete_weather(grid_id: str, years: list[int]) -> bool:
        """Sprawdza, czy dla każdego roku istnieją zarówno rekordy dzienne, jak i godzinowe."""
        for year in years:
            has_daily = WeatherDaily.objects.filter(grid_id=grid_id, date__year=year).exists()
            has_hourly = WeatherHourly.objects.filter(grid_id=grid_id, utc_time__year=year).exists()
            if not (has_daily and has_hourly):
                return False
        return True

    def _find_weather_zip(self, granularity: str, year: int, region: str) -> Path | None:
        """Wyszukuje archiwum ZIP (`daily` lub `hourly`) dla zadanego roku i regionu."""
        if not self.data_dir.exists():
            return None
        region_lower = region.lower()
        matches = sorted(
            p
            for p in self.data_dir.rglob("*.zip")
            if granularity in p.name.lower()
            and str(year) in p.name
            and region_lower in p.name.lower()
            and "imerg" not in p.name.lower()
        )
        return matches[0] if matches else None

    def _collect_complete_archives(
        self, region: str, years: list[int]
    ) -> dict[int, tuple[Path, Path]] | None:
        """Zwraca mapę `{rok: (daily_zip, hourly_zip)}` tylko wtedy, gdy istnieje komplet dla KAŻDEGO roku."""
        archives_by_year: dict[int, tuple[Path, Path]] = {}
        for year in years:
            daily_zip = self._find_weather_zip("daily", year, region)
            hourly_zip = self._find_weather_zip("hourly", year, region)
            if daily_zip is None or hourly_zip is None:
                return None
            archives_by_year[year] = (daily_zip, hourly_zip)
        return archives_by_year

    def _describe_missing_archives(self, region: str, years: list[int]) -> list[str]:
        """Buduje listę brakujących archiwów (np. `['daily/2025', 'hourly/2025']`) do komunikatu błędu."""
        missing: list[str] = []
        for year in years:
            if self._find_weather_zip("daily", year, region) is None:
                missing.append(f"daily/{year}")
            if self._find_weather_zip("hourly", year, region) is None:
                missing.append(f"hourly/{year}")
        return missing

    def _load_grid_from_archives(
        self, grid_id: str, archives_by_year: dict[int, tuple[Path, Path]]
    ) -> None:
        """Wczytuje pogodę dzienną i godzinową ze zweryfikowanego kompletu archiwów ZIP."""
        dcols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id"}
        hcols = {f.attname for f in WeatherHourly._meta.concrete_fields} - {"id"}

        for year, (daily_zip, hourly_zip) in sorted(archives_by_year.items()):
            daily_df = self._read_parquet_from_zip(daily_zip, [grid_id])
            imerg_daily = self._read_imerg_parquet("daily", year, [grid_id])
            if not imerg_daily.empty:
                imerg_daily = imerg_daily.rename(columns={"total_precipitation": "imerg_total_precipitation"})[
                    ["grid_id", "date", "imerg_total_precipitation"]
                ]
                daily_df = daily_df.merge(imerg_daily, on=["grid_id", "date"], how="left")

            daily_df = daily_df[[c for c in daily_df.columns if c in dcols]]
            WeatherDaily.objects.bulk_create(
                [
                    WeatherDaily(**{k: (None if pd.isna(v) else v) for k, v in rec.items()})
                    for rec in daily_df.to_dict("records")
                ],
                batch_size=5000,
                ignore_conflicts=True,
            )

            hourly_df = self._read_parquet_from_zip(hourly_zip, [grid_id])
            imerg_hourly = self._read_imerg_parquet("hourly", year, [grid_id])
            if not imerg_hourly.empty:
                imerg_hourly = imerg_hourly.rename(columns={"precipitation": "imerg_precipitation"})[
                    ["grid_id", "utc_time", "imerg_precipitation"]
                ]
                hourly_df = hourly_df.merge(imerg_hourly, on=["grid_id", "utc_time"], how="left")

            utc_series = pd.to_datetime(hourly_df["utc_time"])
            if utc_series.dt.tz is None:
                utc_series = utc_series.dt.tz_localize("UTC")
            else:
                utc_series = utc_series.dt.tz_convert("UTC")
            hourly_df["utc_time"] = utc_series
            if "date" in hcols and "date" not in hourly_df.columns:
                hourly_df["date"] = utc_series.dt.date

            hourly_df = hourly_df[[c for c in hourly_df.columns if c in hcols]]
            WeatherHourly.objects.bulk_create(
                [
                    WeatherHourly(**{k: (None if pd.isna(v) else v) for k, v in rec.items()})
                    for rec in hourly_df.to_dict("records")
                ],
                batch_size=5000,
                ignore_conflicts=True,
            )

    @staticmethod
    def _read_parquet_from_zip(zip_path: Path, grid_ids: list[str]) -> pd.DataFrame:
        """Odczytuje i filtruje wiersze po `grid_id` ze wszystkich plików `.parquet` wewnątrz ZIP."""
        frames: list[pd.DataFrame] = []
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name.endswith(".parquet"):
                    continue
                with zf.open(name) as fh:
                    df = pd.read_parquet(fh)
                if "grid_id" in df.columns:
                    df = df[df["grid_id"].astype(str).isin(grid_ids)]
                if not df.empty:
                    frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _read_imerg_parquet(self, granularity: str, year: int, grid_ids: list[str]) -> pd.DataFrame:
        """Odczytuje opady satelitarne IMERG z `DATA_DIR` dla zadanego roku i rozdzielczości."""
        if not self.data_dir.exists():
            return pd.DataFrame()
        matches = sorted(
            p
            for p in self.data_dir.rglob("*.parquet")
            if "imerg" in str(p).lower() and granularity in str(p).lower() and str(year) in p.name
        )
        if not matches:
            return pd.DataFrame()
        df = pd.read_parquet(matches[0])
        if "grid_id" in df.columns:
            df = df[df["grid_id"].astype(str).isin(grid_ids)]
        return df

    @staticmethod
    def _generate_synthetic_weather(grid: WeatherGrid, years: list[int]) -> None:
        """Deterministycznie generuje pogodę dzienną i godzinową wyłącznie w trybie `--allow-synthetic`."""
        dcols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id"}
        hcols = {f.attname for f in WeatherHourly._meta.concrete_fields} - {"id"}
        rng = random.Random(f"weather:{grid.grid_id}")

        daily_rows: list[WeatherDaily] = []
        hourly_rows: list[WeatherHourly] = []

        for year in years:
            cur = date(year, 1, 1)
            end = date(year, 12, 31)
            while cur <= end:
                doy = cur.timetuple().tm_yday
                seasonal_temp = 10.5 + 11.5 * math.sin((2.0 * math.pi * (doy - 105)) / 365.0)
                avg_temp = round(seasonal_temp + rng.uniform(-2.5, 2.5), 2)
                min_temp = round(avg_temp - rng.uniform(3.5, 6.0), 2)
                max_temp = round(avg_temp + rng.uniform(3.5, 6.5), 2)
                humidity = round(min(98.0, max(38.0, 74.0 - 0.5 * (avg_temp - 10.0) + rng.uniform(-10.0, 10.0))), 1)
                rain = round(rng.uniform(1.5, 11.0) if rng.random() < 0.28 else 0.0, 2)

                daily_payload: dict[str, Any] = {
                    "grid_id": grid.grid_id,
                    "date": cur,
                    "avg_temperature": avg_temp,
                    "min_temperature": min_temp,
                    "max_temperature": max_temp,
                    "midpoint_temperature": round((min_temp + max_temp) / 2.0, 2),
                    "avg_relative_humidity": humidity,
                    "total_precipitation": rain,
                    "imerg_total_precipitation": rain,
                    "wind_speed": round(rng.uniform(1.5, 6.5), 2),
                    "solar_radiation": round(max(2.0, 14.0 + 10.0 * math.sin((2.0 * math.pi * (doy - 80)) / 365.0)), 2),
                }
                daily_rows.append(
                    WeatherDaily(**{k: v for k, v in daily_payload.items() if k in dcols})
                )

                hourly_rain = round(rain / 24.0, 3)
                for hour in range(24):
                    diurnal = -3.5 * math.cos((2.0 * math.pi * (hour - 3)) / 24.0)
                    h_temp = round(avg_temp + diurnal, 2)
                    h_rh = round(min(99.0, max(32.0, humidity - diurnal * 2.2)), 1)
                    utc_dt = datetime.combine(cur, time(hour=hour), tzinfo=timezone.utc)
                    hourly_payload: dict[str, Any] = {
                        "grid_id": grid.grid_id,
                        "date": cur,
                        "utc_time": utc_dt,
                        "temperature": h_temp,
                        "relative_humidity": h_rh,
                        "precipitation": hourly_rain,
                        "imerg_precipitation": hourly_rain,
                    }
                    hourly_rows.append(
                        WeatherHourly(**{k: v for k, v in hourly_payload.items() if k in hcols})
                    )

                cur += timedelta(days=1)

        WeatherDaily.objects.bulk_create(daily_rows, batch_size=5000, ignore_conflicts=True)
        WeatherHourly.objects.bulk_create(hourly_rows, batch_size=10000, ignore_conflicts=True)

    @staticmethod
    def _apply_weather_overrides(grid_ids: list[str], overrides: list[dict[str, Any]]) -> None:
        """Nadpisuje wybrane kolumny pogodowe dla zadanych przedziałów dat ze scenariusza."""
        valid_daily_cols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id", "grid_id", "date"}

        for entry in overrides:
            start_str = entry.get("start_date") or entry.get("date")
            end_str = entry.get("end_date") or start_str
            values = entry.get("values")
            if not start_str or not isinstance(values, dict):
                continue

            start_d = date.fromisoformat(str(start_str))
            end_d = date.fromisoformat(str(end_str))
            filtered_values = {k: v for k, v in values.items() if k in valid_daily_cols}

            if "avg_temperature" in filtered_values and filtered_values["avg_temperature"] is not None:
                avg_t = float(filtered_values["avg_temperature"])
                filtered_values.setdefault("min_temperature", round(avg_t - 4.0, 2))
                filtered_values.setdefault("max_temperature", round(avg_t + 4.0, 2))
                filtered_values.setdefault("midpoint_temperature", avg_t)

            if filtered_values:
                WeatherDaily.objects.filter(
                    grid_id__in=grid_ids, date__range=(start_d, end_d)
                ).update(**filtered_values)

            hourly_updates: dict[str, Any] = {}
            if "avg_relative_humidity" in filtered_values and filtered_values["avg_relative_humidity"] is not None:
                hourly_updates["relative_humidity"] = float(filtered_values["avg_relative_humidity"])
            if "avg_temperature" in filtered_values and filtered_values["avg_temperature"] is not None:
                hourly_updates["temperature"] = float(filtered_values["avg_temperature"])
            if "imerg_total_precipitation" in filtered_values and filtered_values["imerg_total_precipitation"] is not None:
                hourly_updates["imerg_precipitation"] = round(
                    float(filtered_values["imerg_total_precipitation"]) / 24.0, 3
                )
            if hourly_updates:
                WeatherHourly.objects.filter(
                    grid_id__in=grid_ids, date__range=(start_d, end_d)
                ).update(**hourly_updates)

    def generate_forecast_series(
        self, grid_ids: list[str], start: date, end: date, horizon_days: int = 7
    ) -> int:
        """Buduje 7-dniową prognozę (`WeatherForecastDaily`) dla każdego dnia `D` z przedziału `[start, end]`."""
        WeatherForecastDaily.objects.filter(
            grid_id__in=grid_ids, issued_on__range=(start, end)
        ).delete()

        fcols = {f.attname for f in WeatherForecastDaily._meta.concrete_fields} - {"id"}
        daily_qs = WeatherDaily.objects.filter(
            grid_id__in=grid_ids,
            date__range=(start + timedelta(days=1), end + timedelta(days=horizon_days)),
        )
        by_grid_and_date: dict[tuple[str, date], WeatherDaily] = {
            (row.grid_id, row.date): row for row in daily_qs
        }

        to_create: list[WeatherForecastDaily] = []
        for grid_id in grid_ids:
            issued = start
            while issued <= end:
                for offset in range(1, horizon_days + 1):
                    target_date = issued + timedelta(days=offset)
                    obs = by_grid_and_date.get((grid_id, target_date))
                    if obs is None:
                        continue
                    precip = (
                        obs.imerg_total_precipitation
                        if getattr(obs, "imerg_total_precipitation", None) is not None
                        else getattr(obs, "total_precipitation", None)
                    )
                    payload: dict[str, Any] = {
                        "grid_id": grid_id,
                        "issued_on": issued,
                        "date": target_date,
                        "avg_temperature": getattr(obs, "avg_temperature", None),
                        "min_temperature": getattr(obs, "min_temperature", None),
                        "max_temperature": getattr(obs, "max_temperature", None),
                        "avg_relative_humidity": getattr(obs, "avg_relative_humidity", None),
                        "total_precipitation": precip,
                    }
                    to_create.append(
                        WeatherForecastDaily(**{k: v for k, v in payload.items() if k in fcols})
                    )
                issued += timedelta(days=1)

        WeatherForecastDaily.objects.bulk_create(to_create, batch_size=5000, ignore_conflicts=True)
        return len(to_create)


class ObservationLoader:
    """Zapisuje początkowe obserwacje rolnika (`core.Observation`) z definicji scenariusza."""

    @staticmethod
    def load_observations(
        observations: list[ObservationSpec], fields_by_name: dict[str, Field]
    ) -> int:
        """Tworzy rekordy `Observation` powiązane z odpowiednimi polami i zagrożeniami."""
        created = 0
        for spec in observations:
            field = fields_by_name.get(spec.field_name) if spec.field_name else None
            threat = (
                Threat.objects.filter(code=spec.threat_code).first()
                if spec.threat_code
                else None
            )
            Observation.objects.create(
                field=field,
                kind=spec.kind,
                observed_on=spec.observed_on,
                category=spec.category or "",
                threat=threat,
                severity=spec.severity,
                distance_m=spec.distance_m,
                details=spec.details or {},
                text=spec.text or "",
            )
            created += 1
        return created