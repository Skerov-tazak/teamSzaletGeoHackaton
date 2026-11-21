# Scenarios — Test-Case & Simulation Controller

Moduł zarządzający stanem bazy danych dla prezentacji oraz testów integracyjnych platformy **Field Under Pressure (Cropilot)**[cite: 4]. Umożliwia deterministyczne zasilanie bazy na podstawie parametrów scenariusza i zewnętrznych zbiorów danych (`DATA_DIR`) oraz szybkie przełączanie pomiędzy przypadkami testowymi[cite: 4].

## Zakres odpowiedzialności

- Ładowanie i weryfikacja danych referencyjnych (`WeatherGrid`, `CropClass`, `Threat`)[cite: 4].
- Tworzenie konfiguracji gospodarstwa (`Field`, `FieldCropYear`, `SoilCell`) oraz historii pogody (`WeatherDaily`, `WeatherHourly`)[cite: 4].
- Generowanie syntetycznej prognozy 7-dniowej (`WeatherForecastDaily`) dla każdego dnia sezonu[cite: 4].
- Wstrzykiwanie zdarzeń początkowych rolnika (`core.Observation`)[cite: 4].
- Ustawianie zegara symulacji (`core.Clock`) i uruchamianie prekomputacji ryzyk (`engine.precompute_season()`)[cite: 4, 15].

## Dostępne scenariusze (`scenarios/definitions/`)

- `baseline_farm` — gospodarstwo bazowe w woj. opolskim (2x pszenica ozima, 1x kukurydza) bez aktywnych ognisk chorób[cite: 7].
- `wheat_septoria_outbreak` — presja septoriozy paskowanej liści pszenicy w czerwcu[cite: 9].
- `maize_drought_stress` — fala upałów i presja szkodników w uprawie kukurydzy w lipcu[cite: 8].

## Użycie (CLI)

```bash
# Lista dostępnych scenariuszy
python manage.py scenario list

# Podgląd aktualnego stanu bazy i zegara symulacji
python manage.py scenario status

# Przełączenie na wybrany scenariusz (wymaga plików źródłowych w DATA_DIR)
python manage.py scenario switch wheat_septoria_outbreak

# Przełączenie z nadpisaniem parametrów lub trybem offline (dane syntetyczne)
python manage.py scenario switch wheat_septoria_outbreak --today 2025-06-15 --reset-chat --keep-weather
python manage.py scenario switch maize_drought_stress --allow-synthetic-fallback