# Scenarios — Test-Case & Simulation Controller

Moduł zarządzający stanem bazy danych dla prezentacji oraz testów integracyjnych platformy **Field Under Pressure (Cropilot)**. Umożliwia deterministyczne zasilanie bazy na podstawie parametrów scenariusza i zewnętrznych zbiorów danych (`DATA_DIR`) oraz szybkie przełączanie pomiędzy przypadkami testowymi.

## Zakres odpowiedzialności

- Ładowanie i weryfikacja danych referencyjnych (`WeatherGrid`, `CropClass`, `Threat`).
- Tworzenie konfiguracji gospodarstwa (`Field`, `FieldCropYear`, `SoilCell`) oraz historii pogody (`WeatherDaily`, `WeatherHourly`).
- Generowanie syntetycznej prognozy 7-dniowej (`WeatherForecastDaily`) dla każdego dnia sezonu.
- Wstrzykiwanie zdarzeń początkowych rolnika (`core.Observation`).
- Ustawianie zegara symulacji (`core.Clock`) i uruchamianie prekomputacji ryzyk (`engine.predict()`).

## Użycie (CLI)

```bash
# Lista dostępnych scenariuszy
python manage.py scenario list

# Podgląd aktualnego stanu bazy i zegara symulacji
python manage.py scenario status

# Przełączenie na wybrany scenariusz
python manage.py scenario switch wheat_septoria_outbreak

# Przełączenie z nadpisaniem parametrów
python manage.py scenario switch wheat_septoria_outbreak --today 2025-06-15 --reset-chat --keep-weather