# Scenarios — Test-Case & Simulation Controller

Moduł zarządzający stanem bazy danych PostgreSQL dla prezentacji oraz testów integracyjnych platformy **Field Under Pressure (Cropilot)**. Pozwala deterministycznie zasilić bazę danymi z zewnętrznych zbiorów (`settings.DATA_DIR`) lub wbudowanym generatorem zastępczym oraz szybko przełączać się pomiędzy przypadkami testowymi przed uruchomieniem lub w trakcie demonstracji aplikacji.

## Zakres odpowiedzialności

- **Synchronizacja tabel referencyjnych:** idempotentne zasilanie `CropClass` (21 klas CLMS) oraz `Threat` (katalog zagrożeń ładowany przez `engine_load_threats`).
- **Konfiguracja gospodarstwa:** tworzenie rekordów `Field` (powierzchnia liczona w układzie metrycznym `EPSG:2180`, współrzędne GeoJSON w `EPSG:4326`), przypisywanie heksagonów glebowych H3 poziomu 10 (`SoilCell`) oraz historii płodozmianu z lat 2020–2024 (`FieldCropYear`).
- **Zasilanie meteorologiczne:** import pogody dziennej (`WeatherDaily`) i godzinowej (`WeatherHourly`) wraz z opadami satelitarnymi IMERG z `DATA_DIR`, nakładanie modyfikacji scenariuszowych (`weather_overrides`) oraz generowanie 7-dniowej prognozy (`WeatherForecastDaily`) dla każdego dnia sezonu.
- **Zdarzenia rolnika i zegar symulacji:** wstrzykiwanie początkowych obserwacji (`core.Observation`), ustawianie zegara `core.Clock` (`id=1`) oraz prekomputacja ryzyk dla całego sezonu przez `engine.predict()` (z opcjonalnym przeliczeniem poprzedniego sezonu dla efektu *carry-over*).

## Struktura modułu

```text
scenarios/
├── __init__.py
├── README.md                 # Dokumentacja techniczna i instrukcja obsługi
├── exceptions.py             # Hierarchia wyjątków (ScenarioError, Validation, DataSource)
├── schema.py                 # Dataclassy definicji scenariusza oraz walidator JSON/CLI
├── loaders.py                # Loadery danych z DATA_DIR, fallback syntetyczny, generator prognoz
├── manager.py                # Fasada ScenarioManager, repozytorium JSON, czyszczenie bazy
├── tests.py                  # Testy jednostkowe i integracyjne
└── definitions/              # Gotowe definicje przypadków testowych (.json)
    ├── baseline_farm.json
    ├── wheat_septoria_outbreak.json
    └── maize_heat_and_pest.json

core/management/commands/
└── scenario.py               # Cienka komenda Django CLI delegująca do ScenarioManager
```

### Opis komponentów

| Plik | Główne klasy | Rola |
|------|--------------|------|
| `exceptions.py` | `ScenarioError`, `ScenarioNotFoundError`, `ScenarioValidationError`, `DataSourceError` | Spójna hierarchia wyjątków obsługiwana przez CLI i testy. |
| `schema.py` | `ScenarioDefinition`, `FieldSpec`, `ObservationSpec`, `SimulationWindow`, `SwitchOptions`, `ScenarioParser` | Deserializacja plików JSON, walidacja geometrii, zakresów dat, udziałów upraw i obserwacji oraz aplikowanie nadpisań CLI. |
| `loaders.py` | `ReferenceDataLoader`, `FieldAndSoilLoader`, `WeatherAndForecastLoader`, `ObservationLoader` | Odczyt archiwów ZIP/Parquet i rastrów z `DATA_DIR`, normalizacja nazw kolumn i stref czasowych UTC, generowanie `WeatherForecastDaily` oraz fallback offline. |
| `manager.py` | `ScenarioRepository`, `DatabaseStateCleaner`, `ScenarioManager`, `DatabaseStatus`, `SwitchReport` | Odkrywanie scenariuszy, atomowy reset tabel scenariuszowych, ustawienie `Clock` i wywołanie `engine.predict()`. |
| `core/management/commands/scenario.py` | `Command` | Interfejs wiersza poleceń Django (`list`, `status`, `validate`, `switch`). |

## Użycie (CLI)

Wszystkie komendy uruchamia się z katalogu głównego repozytorium w aktywnym środowisku `.venv`:

```bash
# 1. Wyświetl listę dostępnych scenariuszy
python manage.py scenario list

# 2. Sprawdź aktualny stan bazy danych i zegara symulacji
python manage.py scenario status

# 3. Zwaliduj poprawność pliku scenariusza bez modyfikacji bazy
python manage.py scenario validate wheat_septoria_outbreak

# 4. Przełącz bazę danych na wybrany scenariusz
python manage.py scenario switch wheat_septoria_outbreak

# 5. Przełącz z nadpisaniem daty "dzisiaj" i wyczyszczeniem historii czatu
python manage.py scenario switch wheat_septoria_outbreak --today 2025-06-18 --reset-chat
```

### Flagi podkomendy `switch`

| Flaga | Opis |
|-------|------|
| `--today YYYY-MM-DD` | Nadpisuje początkową datę zegara `core.Clock` (musi mieścić się w oknie `[season_start, season_end]`). |
| `--keep-weather` | Pomija ponowne ładowanie `WeatherDaily` i `WeatherHourly`, jeśli tabele zawierają już dane dla komórek siatki i lat scenariusza. Nie należy używać tej flagi po scenariuszach z `weather_overrides`, jeśli celem jest przywrócenie czystych danych źródłowych. |
| `--reset-chat` | Usuwa wszystkie rekordy z tabel `assistant.Conversation` oraz `assistant.Message`. |
| `--skip-predict` | Ładuje wyłącznie dane wejściowe i ustawia `Clock`, bez uruchamiania `engine.predict()`. |
| `--strict-data` | Wyłącza deterministyczny generator zastępczy — wymaga kompletu plików źródłowych w `settings.DATA_DIR`. |

## Format pliku definicji scenariusza (`.json`)

Nowy przypadek testowy dodaje się poprzez utworzenie pliku `<slug>.json` w katalogu `scenarios/definitions/`.

### Struktura sekcji pliku

- **`title`** *(string, wymagane)* — krótka nazwa scenariusza wyświetlana na liście CLI.
- **`description`** *(string, opcjonalne)* — opis sytuacji agronomicznej i oczekiwanych zagrożeń.
- **`region`** *(string, wymagane)* — nazwa województwa używana do dopasowania archiwów pogodowych i glebowych w `DATA_DIR` (np. `"Opolskie"`).
- **`window`** *(object, wymagane)*:
  - `season` *(int)* — rok głównego sezonu wegetacyjnego (np. `2025`).
  - `season_start` *(YYYY-MM-DD)* — początek okna przeliczania sezonu.
  - `season_end` *(YYYY-MM-DD)* — koniec okna prekomputacji sezonu.
  - `clock_today` *(YYYY-MM-DD)* — początkowa data ustawiana w `core.Clock`.
  - `include_previous_season` *(bool, domyślnie `true`)* — czy załadować i przeliczyć poprzedni sezon (`season - 1`) dla efektu *carry-over*.
- **`fields`** *(list[object], wymagane, min. 1 element)*:
  - `name` *(string)* — unikalna nazwa pola w ramach scenariusza.
  - `crop_code` *(int)* — kod uprawy wg legendy CLMS (`1110` = pszenica, `1130` = kukurydza).
  - `geometry` *(object)* — geometria GeoJSON (`Polygon` lub `MultiPolygon`) w układzie `EPSG:4326` (`[lon, lat]`).
  - `crop_history` *(object, opcjonalne)* — nadpisanie historii upraw `{ "rok": { "kod_uprawy": udział_0_1 } }`.
- **`weather_overrides`** *(list[object], opcjonalne)* — modyfikacje warunków pogodowych na potrzeby symulacji zdarzeń ekstremalnych (`start_date`, `end_date`, `values` z nazwami kolumn `WeatherDaily`).
- **`observations`** *(list[object], opcjonalne)* — lista początkowych raportów rolnika zapisywanych w `core.Observation` (`kind`, `observed_on`, `field_name`, `category`, `threat_code`, `severity`, `distance_m`, `details`, `text`).

### Przykład kompletnej definicji

```json
{
  "title": "Presja septoriozy paskowanej liści pszenicy (czerwiec)",
  "description": "Wysoka wilgotność i opady w czerwcu oraz potwierdzone objawy septoriozy na Polu Północnym.",
  "region": "Opolskie",
  "window": {
    "season": 2025,
    "season_start": "2024-09-01",
    "season_end": "2025-07-31",
    "clock_today": "2025-06-15",
    "include_previous_season": true
  },
  "fields": [
    {
      "name": "Pole Północne (Pszenica)",
      "crop_code": 1110,
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [17.640, 50.365],
            [17.648, 50.365],
            [17.648, 50.370],
            [17.640, 50.370],
            [17.640, 50.365]
          ]
        ]
      },
      "crop_history": {
        "2020": { "1110": 1.0 },
        "2021": { "1430": 1.0 },
        "2022": { "1130": 1.0 },
        "2023": { "1430": 1.0 },
        "2024": { "1110": 1.0 }
      }
    }
  ],
  "weather_overrides": [
    {
      "start_date": "2025-06-08",
      "end_date": "2025-06-14",
      "values": {
        "avg_temperature": 18.5,
        "avg_relative_humidity": 91.0,
        "imerg_total_precipitation": 14.5
      }
    }
  ],
  "observations": [
    {
      "kind": "symptoms",
      "observed_on": "2025-06-13",
      "field_name": "Pole Północne (Pszenica)",
      "category": "disease",
      "threat_code": "wheat.septoria_leaf_blotch",
      "severity": 0.85,
      "text": "Liczne podłużne brunatne plamy z piknidiami na liściu podflagowym."
    }
  ]
}
```

## Przepływ danych i zasady integracji

1. **Brak własnych migracji:** Moduł nie definiuje własnych modeli Django i nie modyfikuje `core/models.py` — korzysta wyłącznie z istniejących tabel platformy (`core` oraz opcjonalnie `assistant`).
2. **Atomowość operacji:** Cały proces czyszczenia poprzedniego scenariusza i ładowania nowego stanu odbywa się wewnątrz pojedynczej transakcji `django.db.transaction.atomic()`.
3. **Generowanie prognoz 7-dniowych:** Dla każdego dnia `D` w horyzoncie symulacji `WeatherForecastDaily` wypełniane jest wartościami z `WeatherDaily` dla dni `D+1..D+7`, z przeniesieniem opadu satelitarnego `imerg_total_precipitation` do pola `total_precipitation`.
4. **Kolejność inicjalizacji zegara:** Zapis `Clock(today=...).save()` wykonywany jest na pustej tabeli `Risk` tuż przed wywołaniem `engine.predict()`, co eliminuje zbędne przeliczanie nieaktualnych wierszy przez sygnały modelu.
5. **Tryb hybrydowy (`DATA_DIR` + fallback):** W pierwszej kolejności loadery pobierają dane z plików źródłowych w `settings.DATA_DIR`. W przypadku ich braku (i bez flagi `--strict-data`) uruchamiany jest deterministyczny generator syntetyczny, umożliwiający pracę na dowolnym stanowisku deweloperskim.

## Testy

Zestaw testów jednostkowych i integracyjnych modułu uruchamia się standardową komendą Django:

```bash
python manage.py test scenarios
```