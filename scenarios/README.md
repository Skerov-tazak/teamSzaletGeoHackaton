# Scenarios — Test-Case & Simulation Controller

Moduł zarządzający stanem bazy danych PostgreSQL dla prezentacji oraz testów integracyjnych platformy **Field Under Pressure (Cropilot)**. Pozwala deterministycznie zasilić bazę danymi z zewnętrznych zbiorów (`settings.DATA_DIR`) i szybko przełączać się pomiędzy przypadkami testowymi przed uruchomieniem lub w trakcie demonstracji aplikacji.

## Zakres odpowiedzialności

- **Synchronizacja tabel referencyjnych:** idempotentne zasilanie `CropClass` (21 klas CLMS) oraz `Threat` (katalog zagrożeń ładowany przez `engine_load_threats`).
- **Konfiguracja gospodarstwa:** tworzenie rekordów `Field` (powierzchnia liczona w układzie metrycznym `EPSG:2180`, współrzędne GeoJSON w `EPSG:4326`), przypisywanie heksagonów glebowych H3 poziomu 10 (`SoilCell`) oraz historii płodozmianu z lat 2020–2024 (`FieldCropYear`).
- **Zasilanie meteorologiczne:** import kompletnych archiwów pogody dziennej (`WeatherDaily`) i godzinowej (`WeatherHourly`) wraz z opadami satelitarnymi IMERG z `DATA_DIR`, nakładanie modyfikacji scenariuszowych (`weather_overrides`) oraz generowanie 7-dniowej prognozy (`WeatherForecastDaily`).
- **Pełny horyzont upraw i prekomputacja ryzyk:** automatyczne rozszerzenie ładowania pogody i prognoz co najmniej do **31 grudnia** roku sezonu (aby ryzyka dla późnych upraw, takich jak kukurydza, obejmowały cały rok), zapis obserwacji rolnika (`core.Observation`), ustawienie zegara `core.Clock` (`id=1`) oraz przeliczenie ryzyk przez `engine.precompute_season()`.

## Struktura modułu

```text
scenarios/
├── __init__.py
├── README.md                 # Dokumentacja techniczna i instrukcja obsługi
├── exceptions.py             # Hierarchia wyjątków (ScenarioError, Validation, DataSource)
├── schema.py                 # Dataclassy definicji scenariusza oraz walidator JSON/CLI
├── loaders.py                # Loadery danych z DATA_DIR, fallback opt-in, generator prognoz
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
| `loaders.py` | `ReferenceDataLoader`, `FieldAndSoilLoader`, `WeatherAndForecastLoader`, `ObservationLoader` | Weryfikacja *fail-fast* i odczyt archiwów ZIP/Parquet oraz rastrów z `DATA_DIR`, normalizacja UTC, generowanie `WeatherForecastDaily` oraz jawny tryb syntetyczny (`--allow-synthetic`). |
| `manager.py` | `ScenarioRepository`, `DatabaseStateCleaner`, `ScenarioManager`, `DatabaseStatus`, `SwitchReport` | Odkrywanie scenariuszy, atomowy reset tabel scenariuszowych, ustawienie `Clock` i wywołanie `engine.precompute_season()`. |
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

# 4. Przełącz bazę danych na wybrany scenariusz (wymaga kompletnych plików w DATA_DIR)
python manage.py scenario switch wheat_septoria_outbreak

# 5. Przełącz z nadpisaniem daty "dzisiaj" i wyczyszczeniem historii czatu
python manage.py scenario switch wheat_septoria_outbreak --today 2025-06-18 --reset-chat

# 6. Tryb offline (bez plików w DATA_DIR) — wyłącznie do lokalnego developmentu
python manage.py scenario switch wheat_septoria_outbreak --allow-synthetic
```

### Flagi podkomendy `switch`

| Flaga | Opis |
|-------|------|
| `--today YYYY-MM-DD` | Nadpisuje początkową datę zegara `core.Clock` (musi mieścić się w oknie `[season_start, season_end]`). |
| `--keep-weather` | Pomija ponowne ładowanie `WeatherDaily` i `WeatherHourly`, jeśli tabele zawierają już kompletne dane dla komórek siatki i lat scenariusza. Nie należy używać tej flagi po scenariuszach z `weather_overrides`, jeśli celem jest przywrócenie czystych danych źródłowych. |
| `--reset-chat` | Usuwa wszystkie rekordy z tabel `assistant.Conversation` oraz `assistant.Message`. |
| `--skip-predict` | Ładuje wyłącznie dane wejściowe i ustawia `Clock`, bez uruchamiania `engine.precompute_season()`. |
| `--allow-synthetic` | Zezwala na wygenerowanie danych zastępczych przy braku kompletnych plików w `settings.DATA_DIR`. Domyślnie wyłączone (brak danych kończy się błędem `DataSourceError`); użycie emituje głośne ostrzeżenie w logach oraz na `stderr`. |

## Format pliku definicji scenariusza (`.json`)

Nowy przypadek testowy dodaje się poprzez utworzenie pliku `<slug>.json` w katalogu `scenarios/definitions/`.

### Struktura sekcji pliku

- **`title`** *(string, wymagane)* — krótka nazwa scenariusza wyświetlana na liście CLI.
- **`description`** *(string, opcjonalne)* — opis sytuacji agronomicznej i oczekiwanych zagrożeń.
- **`region`** *(string, wymagane)* — nazwa województwa używana do dopasowania archiwów pogodowych i glebowych w `DATA_DIR` (np. `"Opolskie"`).
- **`window`** *(object, wymagane)*:
  - `season` *(int)* — rok głównego sezonu wegetacyjnego (np. `2025`).
  - `season_start` *(YYYY-MM-DD)* — początek okna ładowania danych sezonu.
  - `season_end` *(YYYY-MM-DD)* — koniec okna scenariusza (horyzont pogody i prognoz jest automatycznie rozszerzany co najmniej do `31 grudnia` roku `season`).
  - `clock_today` *(YYYY-MM-DD)* — początkowa data ustawiana w `core.Clock`.
  - `include_previous_season` *(bool, domyślnie `true`)* — czy załadować także poprzedni sezon (`season - 1`) na potrzeby efektu *carry-over* w silniku.
- **`fields`** *(list[object], wymagane, min. 1 element)*:
  - `name` *(string)* — unikalna nazwa pola w ramach scenariusza.
  - `crop_code` *(int)* — kod uprawy wg legendy CLMS (`1110` = pszenica, `1130` = kukurydza).
  - `geometry` *(object)* — geometria GeoJSON (`Polygon` lub `MultiPolygon`) w układzie `EPSG:4326` (`[lon, lat]`).
  - `crop_history` *(object, opcjonalne)* — nadpisanie historii upraw `{ "rok": { "kod_uprawy": udział_0_1 } }` dla lat `2020–2024`. Można podać tylko wybrane lata — zdefiniowane lata mają pierwszeństwo, a brakujące są uzupełniane z rastrów w `DATA_DIR` (lub danymi syntetycznymi przy `--allow-synthetic`).
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
2. **Atomowość i weryfikacja *fail-fast*:** Cały proces czyszczenia poprzedniego scenariusza i ładowania nowego stanu odbywa się w pojedynczej transakcji `django.db.transaction.atomic()`. Przed zapisem sprawdzana jest kompletność wszystkich wymaganych plików źródłowych, dzięki czemu dane prawdziwe nigdy nie są mieszane z danymi zastępczymi.
3. **Generowanie prognoz 7-dniowych:** Dla każdego dnia `D` w horyzoncie do co najmniej `31 grudnia` roku sezonu tabela `WeatherForecastDaily` wypełniana jest wartościami z `WeatherDaily` dla dni `D+1..D+7`, z przeniesieniem opadu satelitarnego `imerg_total_precipitation` do pola `total_precipitation`.
4. **Prekomputacja ryzyk przez silnik:** Zapis zegara `Clock(today=...)` wykonywany jest na pustej tabeli `Risk` tuż przed wywołaniem `engine.precompute_season()`, które przelicza pełne okno sezonu wraz z efektem *carry-over* oraz horyzontem kukurydzy do końca roku.
5. **Ścisła walidacja źródeł danych:** Domyślnie brak jakiegokolwiek pliku w `settings.DATA_DIR` przerywa działanie błędem `DataSourceError`. Generator syntetyczny uruchamia się wyłącznie po jawnym podaniu flagi `--allow-synthetic` i zawsze emituje ostrzeżenie.

## Testy

Zestaw testów jednostkowych i integracyjnych modułu uruchamia się standardową komendą Django:

```bash
python manage.py test scenarios
```