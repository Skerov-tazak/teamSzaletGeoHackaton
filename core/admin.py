from django.contrib import admin

from .models import (
    Clock,
    CropClass,
    Field,
    FieldCropYear,
    Risk,
    SoilCell,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
    WeatherHourly,
)


@admin.register(Clock)
class ClockAdmin(admin.ModelAdmin):
    list_display = ["today"]

    def has_add_permission(self, request):
        return not Clock.objects.exists()  # only one row

    def has_delete_permission(self, request, obj=None):
        return False  # the clock must always exist


@admin.register(WeatherGrid)
class WeatherGridAdmin(admin.ModelAdmin):
    list_display = ["grid_id", "lat", "lon", "geohash4", "time_zone"]
    search_fields = ["grid_id", "geohash4"]


@admin.register(WeatherDaily)
class WeatherDailyAdmin(admin.ModelAdmin):
    list_display = ["grid", "date", "avg_temperature", "total_precipitation", "avg_relative_humidity"]
    date_hierarchy = "date"
    search_fields = ["grid__grid_id"]
    raw_id_fields = ["grid"]


@admin.register(WeatherHourly)
class WeatherHourlyAdmin(admin.ModelAdmin):
    list_display = ["grid", "utc_time", "temperature", "precipitation", "relative_humidity"]
    date_hierarchy = "date"
    search_fields = ["grid__grid_id"]
    raw_id_fields = ["grid"]


@admin.register(WeatherForecastDaily)
class WeatherForecastDailyAdmin(admin.ModelAdmin):
    list_display = ["grid", "issued_on", "date", "avg_temperature", "total_precipitation"]
    date_hierarchy = "issued_on"
    search_fields = ["grid__grid_id"]
    raw_id_fields = ["grid"]


@admin.register(SoilCell)
class SoilCellAdmin(admin.ModelAdmin):
    list_display = ["h3_index_10", "soil_texture", "ph", "clay", "sand", "silt", "om"]
    search_fields = ["h3_index_10"]


@admin.register(CropClass)
class CropClassAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]


class FieldCropYearInline(admin.TabularInline):
    model = FieldCropYear
    extra = 0


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ["name", "crop", "area_ha", "weather_grid"]
    list_filter = ["crop"]
    raw_id_fields = ["weather_grid"]
    inlines = [FieldCropYearInline]


@admin.register(Threat)
class ThreatAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "crop", "category"]
    list_filter = ["crop", "category"]
    search_fields = ["code", "name"]


@admin.register(Risk)
class RiskAdmin(admin.ModelAdmin):
    list_display = ["field", "threat", "date", "score", "computed_at"]
    list_filter = ["field", "threat__crop"]
    date_hierarchy = "date"
    search_fields = ["threat__code", "field__name"]
