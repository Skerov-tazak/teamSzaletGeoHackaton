"""
Every table of the platform. Described in docs/database.md; keep the two in sync.

Owned by Szymek + Janek. Other components (engine, assistant) import these models and own no
migrations of their own; if you need a new table or column, ask us.

Units: columns copied from a dataset keep the dataset's name and unit. Each column's unit is in
its help_text, shown in /admin/.
"""

from datetime import timedelta

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q

from core import clock


def measure(unit: str, description: str = "") -> models.FloatField:
    """A nullable float column with its unit recorded in help_text."""
    return models.FloatField(null=True, blank=True, help_text=f"[{unit}] {description}".strip())


# --- Time ------------------------------------------------------------------------------------


class Clock(models.Model):
    """The demo's current date. Exactly one row (id = 1). Read it with core.clock.today()."""

    # No default on purpose: with a default, Django always INSERTs new objects instead of updating
    # the existing row. save() sets the id to 1.
    id = models.PositiveSmallIntegerField(primary_key=True, editable=False)
    today = models.DateField(help_text="The demo's current date (local, Europe/Warsaw).")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="clock_single_row")]

    def save(self, *args, **kwargs):
        self.pk = 1  # there is only ever one clock
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Today is {self.today.isoformat()}"


# --- Weather ---------------------------------------------------------------------------------


class WeatherGrid(models.Model):
    """A 4 km weather grid cell, given by its centre point. Source: weather grid_table."""

    grid_id = models.CharField(primary_key=True, max_length=64, help_text="Grid id from the dataset.")
    lat = models.FloatField(help_text="[° WGS84] Grid point latitude.")
    lon = models.FloatField(help_text="[° WGS84] Grid point longitude.")
    geohash4 = models.CharField(max_length=12, blank=True, help_text="Geohash, precision 4.")
    time_zone = models.CharField(max_length=64, blank=True, help_text="Local time zone of the cell.")

    def __str__(self) -> str:
        return self.grid_id


class DailyWeatherColumns(models.Model):
    """
    The daily weather columns, shared by observed weather and the forecast.
    Names and units as in the dataset's daily_table. Values outside valid ranges are null.
    """

    max_temperature = measure("°C", "Max of 24 hourly values, 2 m.")
    min_temperature = measure("°C", "Min of 24 hourly values, 2 m.")
    midpoint_temperature = measure("°C", "(min + max) / 2.")
    avg_temperature = measure("°C", "Mean of 24 hourly values, 2 m.")
    max_dew_point_temperature = measure("°C")
    min_dew_point_temperature = measure("°C")
    avg_dew_point_temperature = measure("°C")
    total_precipitation = measure("mm/day", "Sum of 24 hourly values (weather model).")
    max_wind_speed = measure("km/h", "10 m.")
    min_wind_speed = measure("km/h", "10 m.")
    avg_wind_speed = measure("km/h", "10 m.")
    avg_wind_direction = measure("° azimuth", "10 m, vector average.")
    max_wind_gust = measure("km/h", "10 m.")
    max_wind_speed_2m = measure("km/h", "2 m.")
    min_wind_speed_2m = measure("km/h", "2 m.")
    avg_wind_speed_2m = measure("km/h", "2 m.")
    max_relative_humidity = measure("% 0-100")
    min_relative_humidity = measure("% 0-100")
    avg_relative_humidity = measure("% 0-100")
    total_downward_solar_radiation = measure("MJ/m²/day", "Daily total.")
    max_downward_solar_radiation = measure("MJ/m²/hour", "Highest hourly value of the day.")
    total_net_solar_radiation = measure("MJ/m²/day", "Daily total.")
    max_net_solar_radiation = measure("MJ/m²/hour", "Highest hourly value of the day.")
    min_atmospheric_pressure = measure("mbar", "Surface.")
    max_atmospheric_pressure = measure("mbar", "Surface.")
    avg_atmospheric_pressure = measure("mbar", "Surface.")
    avg_total_cloud_cover = measure("fraction 0-1")
    avg_snow_depth = measure("mm water equivalent", "Not snow height.")
    avg_snow_density = measure("kg/m³")
    max_soil_temperature_level_1 = measure("°C", "Weather soil level 1: 0-7 cm.")
    max_soil_temperature_level_2 = measure("°C", "Weather soil level 2: 7-28 cm.")
    max_soil_temperature_level_3 = measure("°C", "Weather soil level 3: 28-100 cm.")
    max_soil_temperature_level_4 = measure("°C", "Weather soil level 4: 100-289 cm.")
    min_soil_temperature_level_1 = measure("°C", "Weather soil level 1: 0-7 cm.")
    min_soil_temperature_level_2 = measure("°C", "Weather soil level 2: 7-28 cm.")
    min_soil_temperature_level_3 = measure("°C", "Weather soil level 3: 28-100 cm.")
    min_soil_temperature_level_4 = measure("°C", "Weather soil level 4: 100-289 cm.")
    avg_soil_temperature_level_1 = measure("°C", "Weather soil level 1: 0-7 cm.")
    avg_soil_temperature_level_2 = measure("°C", "Weather soil level 2: 7-28 cm.")
    avg_soil_temperature_level_3 = measure("°C", "Weather soil level 3: 28-100 cm.")
    avg_soil_temperature_level_4 = measure("°C", "Weather soil level 4: 100-289 cm.")
    avg_soil_moisture_level_1 = measure("m³/m³ fraction 0-1", "Weather soil level 1: 0-7 cm.")
    avg_soil_moisture_level_2 = measure("m³/m³ fraction 0-1", "Weather soil level 2: 7-28 cm.")
    avg_soil_moisture_level_3 = measure("m³/m³ fraction 0-1", "Weather soil level 3: 28-100 cm.")
    avg_soil_moisture_level_4 = measure("m³/m³ fraction 0-1", "Weather soil level 4: 100-289 cm.")
    eto = measure("mm/day", "Grass reference evapotranspiration.")
    etr = measure("mm/day", "Alfalfa reference evapotranspiration.")
    day_length = measure("h")

    class Meta:
        abstract = True


class ObservedWeatherQuerySet(models.QuerySet):
    def observed(self):
        """Only weather up to and including the demo's today. Never read observed weather without this."""
        return self.filter(date__lte=clock.today())


class WeatherDaily(DailyWeatherColumns):
    """Observed daily weather per grid cell. Source: weather daily_table + IMERG daily."""

    grid = models.ForeignKey(WeatherGrid, on_delete=models.PROTECT, related_name="daily")
    date = models.DateField(help_text="Local calendar date (Europe/Warsaw).")
    imerg_total_precipitation = measure("mm/day", "Satellite precipitation from NASA IMERG.")

    objects = ObservedWeatherQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "weather daily"
        constraints = [
            models.UniqueConstraint(fields=["grid", "date"], name="weatherdaily_unique_grid_date"),
        ]

    def __str__(self) -> str:
        return f"{self.grid_id} {self.date}"


class ForecastQuerySet(models.QuerySet):
    def current(self):
        """The forecast issued on the demo's today: the next FORECAST_DAYS days."""
        return self.filter(issued_on=clock.today())


class WeatherForecastDaily(DailyWeatherColumns):
    """
    The 7-day daily forecast as known on `issued_on`. In the demo it is seeded from WeatherDaily.
    Same columns as WeatherDaily, without IMERG (there is no forecast of satellite precipitation).
    """

    grid = models.ForeignKey(WeatherGrid, on_delete=models.PROTECT, related_name="forecasts")
    issued_on = models.DateField(help_text="The day the forecast was made (local).")
    date = models.DateField(help_text="The day the forecast is for (local): issued_on + 1 to + 7.")

    objects = ForecastQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "weather forecasts daily"
        constraints = [
            models.UniqueConstraint(
                fields=["grid", "issued_on", "date"], name="weatherforecastdaily_unique_grid_issued_date"
            ),
            models.CheckConstraint(
                condition=Q(date__gt=F("issued_on"))
                & Q(date__lte=F("issued_on") + timedelta(days=clock.FORECAST_DAYS)),
                name="weatherforecastdaily_date_within_window",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.grid_id} {self.date} (issued {self.issued_on})"


class WeatherHourly(models.Model):
    """Observed hourly weather per grid cell. Source: weather hourly_table + IMERG hourly."""

    grid = models.ForeignKey(WeatherGrid, on_delete=models.PROTECT, related_name="hourly")
    utc_time = models.DateTimeField(help_text="[UTC] Start of the hour.")
    date = models.DateField(help_text="Local calendar date (Europe/Warsaw), for fast filtering.")
    temperature = measure("°C", "2 m.")
    dew_point_temperature = measure("°C", "2 m.")
    precipitation = measure("mm/hour", "Weather model.")
    imerg_precipitation = measure("mm/hour", "Satellite precipitation from NASA IMERG.")
    wind_speed = measure("km/h", "10 m.")
    wind_direction = measure("° azimuth", "10 m.")
    wind_gust = measure("km/h", "10 m.")
    wind_speed_2m = measure("km/h", "2 m.")
    relative_humidity = measure("% 0-100")
    downward_solar_radiation = measure("MJ/m²/hour")
    net_solar_radiation = measure("MJ/m²/hour")
    atmospheric_pressure = measure("mbar", "Surface.")
    total_cloud_cover = measure("fraction 0-1")
    snow_depth = measure("mm water equivalent", "Not snow height.")
    snow_density = measure("kg/m³")
    soil_temperature_level_1 = measure("°C", "Weather soil level 1: 0-7 cm.")
    soil_temperature_level_2 = measure("°C", "Weather soil level 2: 7-28 cm.")
    soil_temperature_level_3 = measure("°C", "Weather soil level 3: 28-100 cm.")
    soil_temperature_level_4 = measure("°C", "Weather soil level 4: 100-289 cm.")
    soil_moisture_level_1 = measure("m³/m³ fraction 0-1", "Weather soil level 1: 0-7 cm.")
    soil_moisture_level_2 = measure("m³/m³ fraction 0-1", "Weather soil level 2: 7-28 cm.")
    soil_moisture_level_3 = measure("m³/m³ fraction 0-1", "Weather soil level 3: 28-100 cm.")
    soil_moisture_level_4 = measure("m³/m³ fraction 0-1", "Weather soil level 4: 100-289 cm.")
    eto = measure("mm/hour", "Grass reference evapotranspiration.")
    etr = measure("mm/hour", "Alfalfa reference evapotranspiration.")

    objects = ObservedWeatherQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "weather hourly"
        constraints = [
            models.UniqueConstraint(fields=["grid", "utc_time"], name="weatherhourly_unique_grid_time"),
        ]
        indexes = [models.Index(fields=["grid", "date"], name="weatherhourly_grid_date")]

    def __str__(self) -> str:
        return f"{self.grid_id} {self.utc_time:%Y-%m-%d %H:%M}Z"


# --- Soil ------------------------------------------------------------------------------------


class SoilCell(models.Model):
    """
    Soil properties of one H3 level-10 cell. Source: ISRIC SoilGrids Soil 250 v2 (2022).
    Layered columns are <property>_<depth>_mean. Check the units after download (docs/database.md).
    """

    h3_index_10 = models.CharField(primary_key=True, max_length=15, help_text="H3 index, level 10.")

    # Bulk density of the fine earth (no 15-30 cm column in the source)
    bdod_0_5cm_mean = measure("kg/dm³", "Bulk density, 0-5 cm.")
    bdod_5_15cm_mean = measure("kg/dm³", "Bulk density, 5-15 cm.")
    bdod_30_60cm_mean = measure("kg/dm³", "Bulk density, 30-60 cm.")
    bdod_60_100cm_mean = measure("kg/dm³", "Bulk density, 60-100 cm.")
    bdod_100_200cm_mean = measure("kg/dm³", "Bulk density, 100-200 cm.")
    # Cation exchange capacity
    cec_0_5cm_mean = measure("cmol(c)/kg", "CEC, 0-5 cm.")
    cec_5_15cm_mean = measure("cmol(c)/kg", "CEC, 5-15 cm.")
    cec_15_30cm_mean = measure("cmol(c)/kg", "CEC, 15-30 cm.")
    cec_30_60cm_mean = measure("cmol(c)/kg", "CEC, 30-60 cm.")
    cec_60_100cm_mean = measure("cmol(c)/kg", "CEC, 60-100 cm.")
    cec_100_200cm_mean = measure("cmol(c)/kg", "CEC, 100-200 cm.")
    # Coarse fragments (> 2 mm), by volume
    cfvo_0_5cm_mean = measure("vol %", "Coarse fragments, 0-5 cm.")
    cfvo_5_15cm_mean = measure("vol %", "Coarse fragments, 5-15 cm.")
    cfvo_15_30cm_mean = measure("vol %", "Coarse fragments, 15-30 cm.")
    cfvo_30_60cm_mean = measure("vol %", "Coarse fragments, 30-60 cm.")
    cfvo_60_100cm_mean = measure("vol %", "Coarse fragments, 60-100 cm.")
    cfvo_100_200cm_mean = measure("vol %", "Coarse fragments, 100-200 cm.")
    # Clay (< 0.002 mm)
    clay_0_5cm_mean = measure("%", "Clay, 0-5 cm.")
    clay_5_15cm_mean = measure("%", "Clay, 5-15 cm.")
    clay_15_30cm_mean = measure("%", "Clay, 15-30 cm.")
    clay_30_60cm_mean = measure("%", "Clay, 30-60 cm.")
    clay_60_100cm_mean = measure("%", "Clay, 60-100 cm.")
    clay_100_200cm_mean = measure("%", "Clay, 100-200 cm.")
    # Sand (> 0.05 mm)
    sand_0_5cm_mean = measure("%", "Sand, 0-5 cm.")
    sand_5_15cm_mean = measure("%", "Sand, 5-15 cm.")
    sand_15_30cm_mean = measure("%", "Sand, 15-30 cm.")
    sand_30_60cm_mean = measure("%", "Sand, 30-60 cm.")
    sand_60_100cm_mean = measure("%", "Sand, 60-100 cm.")
    sand_100_200cm_mean = measure("%", "Sand, 100-200 cm.")
    # Silt (0.002-0.05 mm)
    silt_0_5cm_mean = measure("%", "Silt, 0-5 cm.")
    silt_5_15cm_mean = measure("%", "Silt, 5-15 cm.")
    silt_15_30cm_mean = measure("%", "Silt, 15-30 cm.")
    silt_30_60cm_mean = measure("%", "Silt, 30-60 cm.")
    silt_60_100cm_mean = measure("%", "Silt, 60-100 cm.")
    silt_100_200cm_mean = measure("%", "Silt, 100-200 cm.")
    # Total nitrogen
    nitrogen_0_5cm_mean = measure("g/kg", "Nitrogen, 0-5 cm.")
    nitrogen_5_15cm_mean = measure("g/kg", "Nitrogen, 5-15 cm.")
    nitrogen_15_30cm_mean = measure("g/kg", "Nitrogen, 15-30 cm.")
    nitrogen_30_60cm_mean = measure("g/kg", "Nitrogen, 30-60 cm.")
    nitrogen_60_100cm_mean = measure("g/kg", "Nitrogen, 60-100 cm.")
    nitrogen_100_200cm_mean = measure("g/kg", "Nitrogen, 100-200 cm.")
    # pH in water
    phh2o_0_5cm_mean = measure("pH", "pH (H2O), 0-5 cm.")
    phh2o_5_15cm_mean = measure("pH", "pH (H2O), 5-15 cm.")
    phh2o_15_30cm_mean = measure("pH", "pH (H2O), 15-30 cm.")
    phh2o_30_60cm_mean = measure("pH", "pH (H2O), 30-60 cm.")
    phh2o_60_100cm_mean = measure("pH", "pH (H2O), 60-100 cm.")
    phh2o_100_200cm_mean = measure("pH", "pH (H2O), 100-200 cm.")
    # Organic carbon density
    ocd_0_5cm_mean = measure("kg/m³", "Organic carbon density, 0-5 cm.")
    ocd_5_15cm_mean = measure("kg/m³", "Organic carbon density, 5-15 cm.")
    ocd_15_30cm_mean = measure("kg/m³", "Organic carbon density, 15-30 cm.")
    ocd_30_60cm_mean = measure("kg/m³", "Organic carbon density, 30-60 cm.")
    ocd_60_100cm_mean = measure("kg/m³", "Organic carbon density, 60-100 cm.")
    ocd_100_200cm_mean = measure("kg/m³", "Organic carbon density, 100-200 cm.")
    # Soil organic carbon
    soc_0_5cm_mean = measure("g/kg", "Soil organic carbon, 0-5 cm.")
    soc_5_15cm_mean = measure("g/kg", "Soil organic carbon, 5-15 cm.")
    soc_15_30cm_mean = measure("g/kg", "Soil organic carbon, 15-30 cm.")
    soc_30_60cm_mean = measure("g/kg", "Soil organic carbon, 30-60 cm.")
    soc_60_100cm_mean = measure("g/kg", "Soil organic carbon, 60-100 cm.")
    soc_100_200cm_mean = measure("g/kg", "Soil organic carbon, 100-200 cm.")

    # Single columns
    ocs_0_30cm_mean = models.IntegerField(null=True, blank=True, help_text="[t/ha] Organic carbon stock, 0-30 cm.")
    om = measure("g/kg (check)", "Organic matter, root-zone average to 30 cm. Unit to verify, see docs.")
    cec = measure("cmol(c)/kg", "CEC, root-zone average to 30 cm.")
    ph = measure("pH", "pH, root-zone average to 15 cm. Source name: pH.")
    sand = measure("%", "Sand, root-zone average to 30 cm.")
    silt = measure("%", "Silt, root-zone average to 30 cm.")
    clay = measure("%", "Clay, root-zone average to 30 cm.")
    bulk_density = measure("kg/dm³", "Bulk density, root-zone average to 30 cm.")
    band_om = measure("category", "Organic matter band: low (< 2), moderate, high (> 3.5).")
    band_cec = measure("category", "CEC band: low (< 10), moderate, high (> 20).")
    band_ph = measure("category", "pH band: low (< 5.8), moderate, high (> 7.5). Source name: band_pH.")
    soil_texture = models.CharField(
        max_length=64, null=True, blank=True, help_text="USDA soil texture class, root zone to 30 cm."
    )

    def __str__(self) -> str:
        return self.h3_index_10


# --- Crops and fields ------------------------------------------------------------------------


class CropClass(models.Model):
    """A CLMS Crop Types class. Source: the cropland legend (all 21 codes)."""

    WHEAT = 1110
    MAIZE = 1130
    NO_CROPLAND = 0

    code = models.PositiveIntegerField(primary_key=True, help_text="CLMS class code, e.g. 1110 Wheat, 1130 Maize.")
    name = models.CharField(max_length=100, help_text="English name from the legend.")

    class Meta:
        verbose_name_plural = "crop classes"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Field(models.Model):
    """
    A field of the demo farm. The polygon is drawn by us; the other columns are computed once at
    import, so nothing needs geometry at runtime.
    """

    name = models.CharField(max_length=200)
    geometry = models.JSONField(help_text="GeoJSON Polygon or MultiPolygon, EPSG:4326, coordinates [lon, lat].")
    area_ha = models.FloatField(help_text="[ha] Computed in EPSG:2180, never from degrees.")
    centroid_lat = models.FloatField(help_text="[° WGS84]")
    centroid_lon = models.FloatField(help_text="[° WGS84]")
    weather_grid = models.ForeignKey(
        WeatherGrid,
        on_delete=models.PROTECT,
        related_name="fields",
        help_text="The weather grid point nearest the field's centroid.",
    )
    h3_cells = ArrayField(
        models.CharField(max_length=15),
        help_text="H3 level-10 cells whose centre lies inside the polygon (or the centroid's cell if none).",
    )
    crop = models.ForeignKey(
        CropClass,
        on_delete=models.PROTECT,
        related_name="fields",
        help_text="This season's crop: the largest share in this season's FieldCropYear rows.",
    )

    def soil_cells(self) -> models.QuerySet["SoilCell"]:
        """The soil cells under this field. Average them for field values (all cells have the same area)."""
        return SoilCell.objects.filter(h3_index_10__in=self.h3_cells)

    def __str__(self) -> str:
        return self.name


class FieldCropYear(models.Model):
    """Share of a field's pixels in one crop class for one year. Source: cropland rasters 2020-2024."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="crop_years")
    year = models.PositiveSmallIntegerField()
    crop_class = models.ForeignKey(CropClass, on_delete=models.PROTECT, related_name="+")
    share = models.FloatField(help_text="[fraction 0-1] Pixels of this class / all pixels inside the field.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["field", "year", "crop_class"], name="fieldcropyear_unique"),
            models.CheckConstraint(condition=Q(share__gte=0) & Q(share__lte=1), name="fieldcropyear_share_0_1"),
        ]

    def __str__(self) -> str:
        return f"{self.field} {self.year}: {self.crop_class} {self.share:.0%}"


# --- Threats and risks -----------------------------------------------------------------------


class Threat(models.Model):
    """A disease or pest of a crop. Source: ryzyka_zebrane.xlsx (sheets kukurydza, pszenica)."""

    class Category(models.TextChoices):
        FUNGAL = "fungal"
        BACTERIAL = "bacterial"
        VIRAL = "viral"
        PEST = "pest"

    code = models.CharField(
        max_length=100, unique=True, help_text="Stable name, e.g. wheat.septoria_leaf_blotch."
    )
    crop = models.ForeignKey(CropClass, on_delete=models.PROTECT, related_name="threats")
    name = models.CharField(max_length=200, help_text="Polish name, as in the source.")
    category = models.CharField(max_length=16, choices=Category.choices)
    temperature_text = models.TextField(blank=True, help_text="Favourable temperature, as written in the source.")
    temp_min_c = measure("°C", "Lower end of the favourable temperature, where the source gives a number.")
    temp_max_c = measure("°C", "Upper end of the favourable temperature, where the source gives a number.")
    humidity_text = models.TextField(blank=True, help_text="Favourable humidity / rain, as written in the source.")
    other_factors = models.TextField(blank=True, help_text="Other risk factors, as written in the source.")
    growth_stage_text = models.TextField(blank=True, help_text="When to watch for it, as written in the source.")
    source = models.CharField(max_length=200, help_text="e.g. ryzyka_zebrane.xlsx / pszenica")

    class Meta:
        ordering = ["crop", "code"]

    def __str__(self) -> str:
        return self.code


class RiskQuerySet(models.QuerySet):
    def season_so_far(self):
        """Risks up to and including the demo's today."""
        return self.filter(date__lte=clock.today())

    def coming_days(self):
        """Risks for the next FORECAST_DAYS days after the demo's today."""
        today = clock.today()
        return self.filter(date__gt=today, date__lte=today + timedelta(days=clock.FORECAST_DAYS))


class Risk(models.Model):
    """
    Risk of one threat on one field for one day, written by the decision engine.
    One row per field, threat and day, overwritten on every recompute.
    """

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="risks")
    threat = models.ForeignKey(Threat, on_delete=models.PROTECT, related_name="risks")
    date = models.DateField(help_text="The day this risk applies to (local).")
    score = models.FloatField(help_text="[0-1] Risk score.")
    explanation = models.JSONField(help_text="Why the risk is what it is. Format still open, see docs/database.md.")
    computed_at = models.DateTimeField(auto_now=True, help_text="[UTC] When the engine last wrote this row.")

    objects = RiskQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["field", "threat", "date"], name="risk_unique_field_threat_date"),
            models.CheckConstraint(condition=Q(score__gte=0) & Q(score__lte=1), name="risk_score_0_1"),
        ]
        indexes = [models.Index(fields=["field", "date"], name="risk_field_date")]

    def __str__(self) -> str:
        return f"{self.field} · {self.threat} · {self.date}: {self.score:.2f}"
