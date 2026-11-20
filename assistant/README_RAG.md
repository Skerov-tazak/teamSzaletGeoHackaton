# RAG nad metodykami IOR — `assistant/rag`

Warstwa wyszukiwania dla asystenta Field Under Pressure. Obejmuje parsowanie PDF i Excela, chunking, embeddingi `sdadas/mmlw-retrieval-roberta-base`, Qdrant (wektory), BM25 (Python) i hybrydę RRF. Serwer MCP importuje API z `rag/search.py`.

## Uruchomienie

Zależności są w `pyproject.toml` (wersje przypięte) i `uv.lock` w katalogu głównym repo. Python 3.12 jest ustawiony w `.python-version`.

```bash
uv sync                                                   # w katalogu repo: tworzy .venv z uv.lock
cd assistant
docker compose -f docker-compose.qdrant.yml up -d         # Qdrant 1.20.2; dashboard: http://localhost:6333/dashboard
uv run python -m rag.ingest                               # 5 PDF + Excel -> chunks -> embeddingi -> Qdrant + BM25
uv run python -m rag.ingest --doc pszenica_doradcy --rebuild
uv run python -m rag.ingest --all-crops                   # + 10 pozostałych PDF (jęczmień, owies, …)
uv run python -m rag.cli "w jakiej temperaturze rozwija się septorioza paskowana" --crop pszenica --k 5
uv run python -m rag.cli --risk pszenica "rdza brunatna"
uv run pytest -q
uv run python eval/run_eval.py
```

Nową zależność dodaje się przez `uv add pakiet==wersja` (zależność dev: `uv add --dev …`), a nie przez `pip install`.

- PDF-y są czytane z `metodyki/` w katalogu repo, a jeśli go nie ma, z `../field-under-pressure-materials/metodyki`. Ścieżkę można nadpisać przez `METODYKI_DIR`.
- Inne zmienne środowiskowe: `QDRANT_URL` (domyślnie `http://localhost:6333`), `QDRANT_COLLECTION` (`guides_mmlw_v1`), `RAG_DATA_DIR`, `RAG_BM25_STEMMER` (`stempel` | `trunc6`).
- Pierwszy ingest trwa ok. 4 min na M-series (MPS). Embeddingi liczą się ok. 165 s, a `find_tables` ok. 60 s; oba wyniki trafiają do cache. Kolejne przebiegi trwają ok. 1 min.
- `--rebuild` usuwa kolekcję i wgrywa od nowa wszystko z `chunks.jsonl`. Bez tej flagi ingest usuwa i wgrywa tylko punkty przetwarzanych dokumentów. Ingest jest idempotentny dzięki deterministycznym `chunk_id` i id `uuid5(chunk_id)`.
- `data/` (processed + index) jest poza gitem.

## Pipeline

| moduł | wejście → wyjście | uwagi |
|---|---|---|
| `docs.py` | rejestr → `docs.json` | tytuł z największego fontu strony 1; dla 3 PDF tytuł z rejestru (`title_source`) |
| `pdf_parse.py` | PDF → `pages.jsonl` | usuwa żywą paginę i numery stron (`printed_page` odczytany albo uzupełniony z offsetu), skleja przeniesienia, buduje akapity, tabele przez `find_tables` z tekstem przypisanym do komórek, strony `skip` z powodem |
| `toc.py` | spis treści → `sections.json` | sklejanie zawiniętych wpisów, numeracja arabska i rzymska (`IV.3.1`), dopasowanie nagłówka do bloku na stronie (rapidfuzz + styl fontu); GIORiN: nagłówki z fontu |
| `chunker.py` | sekcje → `chunks.jsonl` | ≤ 450 tokenów tokenizera modelu, cel 180–280 słów, nakładka ≤ 50 słów, małe sekcje doklejane, tabele osobno z powtarzanym nagłówkiem, podnagłówki (np. nazwa choroby) w `subheading` |
| `flags.py` | — | `has_pesticide_doses`, `has_fertilizer_doses`, `is_legal` |
| `excel_parse.py` | xlsx → `risk_conditions.json` + chunki | wykrywanie nagłówków tabel, wiersz pomocniczy (`dzień | noc`), notatki, `temp_min_c`/`temp_max_c` |
| `embed.py` | — | prefiks `zapytanie: ` tylko dla zapytań; cache sha1 w `emb_cache.npz` |
| `store.py` | — | `QdrantStore` (cosine, 768, indeksy payloadu), protokół `VectorStore` |
| `bm25.py` | — | tokenizacja PL, stop-słowa, `stempel` (pystempel polimorf) lub `trunc6`; oba warianty w `bm25.pkl` |

## Schemat chunka (`chunks.jsonl`)

```json
{
  "chunk_id": "pszenica_doradcy:5.1:0007",
  "doc_id": "pszenica_doradcy", "doc_title": "Metodyka integrowanej ochrony pszenicy ozimej i jarej dla doradców",
  "crop": "pszenica", "audience": "doradcy",
  "section_path": ["5. Ograniczanie sprawców chorób", "5.1. Najważniejsze choroby"], "section_id": "5.1",
  "subheading": "Septorioza paskowana liści pszenicy",
  "pdf_page_start": 72, "pdf_page_end": 73, "printed_page_start": 70, "printed_page_end": 71,
  "kind": "text",                    // text | table | excel_row | excel_note
  "text": "…do wyświetlania i cytowania…",
  "embed_text": "{tytuł} | {ścieżka > podnagłówek} | uprawa: {crop}\n\n{tekst}",
  "n_tokens": 312, "n_words": 190,
  "flags": {"has_pesticide_doses": false, "has_fertilizer_doses": false, "is_legal": false},
  "prev_id": "…", "next_id": "…"
}
```

Chunki z Excela mają `doc_id="ryzyka_zebrane"`, `audience="zestawienie"` oraz `sheet`, `row` i `row_end` zamiast stron. `chunk_id` wygląda tak: `ryzyka_zebrane:pszenica.r019`.

Payload w Qdrant to chunk bez `embed_text`, z flagami skopiowanymi na najwyższy poziom. Indeksy keyword: `crop`, `audience`, `doc_id`, `kind`, `chunk_id`, `section_id`. Indeksy bool: `has_pesticide_doses`, `is_legal`, `has_fertilizer_doses`.

## API (`rag/search.py`)

```python
from rag.search import search, get_passage, get_page, get_risk_conditions

search(query, crop=None, audience=None, k=6, include_pesticide_doses=False,
       mode="hybrid" | "dense" | "bm25") -> list[Passage]
get_passage(chunk_id, with_neighbors=0) -> list[Passage]   # chunk ± sąsiedzi
get_page(doc_id, printed_page) -> str                       # czysty tekst strony + tabele (Markdown)
get_risk_conditions(crop, threat=None) -> list[dict]        # rekordy risk_conditions.json, fuzzy po nazwie
```

`Passage` ma pola: `chunk_id, doc_id, doc_title, crop, audience, section, printed_pages, pdf_pages, kind, text, score, citation`.

Przykład cytatu: `Metodyka integrowanej ochrony pszenicy ozimej i jarej dla doradców (doradcy), s. 70–71`.

- **Hybryda**: top 30 z wyszukiwania wektorowego i top 30 z BM25, z tymi samymi filtrami, łączone przez RRF `w/(60+rank)`. Wagi ustawia się w `config.py`.
- **Filtry**:
  - `crop="pszenica"` przeszukuje `["pszenica", "zboza"]`.
  - `audience` zawsze dopuszcza też wiersze z Excela.
  - Domyślnie wykluczane są chunki `has_pesticide_doses`.
  - Chunki `is_legal` mają wynik mnożony przez 0,5 po fuzji.
- **Scalanie sąsiadów**: sąsiednie chunki tej samej sekcji są łączone w jeden `Passage`. Nakładka jest usuwana, a zakres stron się sumuje.
- **`get_risk_conditions`**: dopasowuje nazwę po złożeniu polskich znaków. Toleruje fleksję i literówki („septoriozy paskowanej”, „septorjoza”) dzięki `token_set_ratio` liczonemu też na 5-znakowych prefiksach słów.
- **Ładowanie zasobów**: model, klient Qdrant, BM25, strony i ryzyka ładują się leniwie, raz na proces.
- **Gdy Qdrant nie działa**: `QdrantUnavailable` z komunikatem „Qdrant nie działa na …, uruchom docker compose …”.

## Statystyki indeksu (5 PDF + Excel)

| dokument | strony (pominięte) | tabele | chunki (tekst / tabela) | sekcje: wpisy, dopasowane |
|---|---|---|---|---|
| kukurydza_doradcy | 248 (39) | 64 | 525 (418 / 107) | 73, 73/73 |
| kukurydza_producenci | 70 (14) | 28 | 154 (109 / 45) | 36, 34/36 |
| pszenica_doradcy | 224 (36) | 73 | 431 (285 / 146) | 48, 48/48 |
| pszenica_producenci | 70 (15) | 32 | 141 (79 / 62) | 36, 35/36 |
| zboza_giorin | 24 (4) | 2 | 47 (44 / 3) | 33 (z fontów), wszystkie |
| ryzyka_zebrane | 5 arkuszy | — | 106 (94 wiersze / 12 notatek) | — |

- **Razem**: 1404 chunki, a w Qdrant jest 1404 punktów.
- **Tokeny** (min / mediana / p95 / maks.): 39 / 339 / 439 / 446. Chunków powyżej 450 tokenów: 0.
- **Pokrycie sekcjami**: 100% stron z treścią.
- **Flagi**: `has_pesticide_doses` 212, `has_fertilizer_doses` 36, `is_legal` 27.

## Ewaluacja (`eval/run_eval.py`, 29 pytań + 3 pułapki)

| tryb | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| dense | 0.72 | 0.93 | 0.97 | 0.830 |
| bm25 / stempel | 0.83 | 0.97 | 1.00 | 0.899 |
| bm25 / trunc6 | 0.93 | 1.00 | 1.00 | 0.954 |
| **hybrid / stempel** (domyślny) | 0.86 | 1.00 | **1.00** | 0.925 |
| hybrid / trunc6 | 0.83 | 1.00 | 1.00 | 0.891 |

- **Pułapki o dawki**: w top 5 przy domyślnych filtrach nie ma żadnego chunka `has_pesticide_doses`.
- **Zastrzeżenie**: zestaw jest łagodny. Trafieniem jest dowolny chunk z właściwego dokumentu zawierający frazę, a pytania używają słownictwa z tekstu, co faworyzuje BM25. Do porównywania wariantów warto dodać pytania parafrazowane i potoczne (np. „żółte paski na liściach”), z węższym `contains`.

## Znane ograniczenia i heurystyki do dopracowania

- **Żywa pagina**: linie w pasie 7% góry i dołu strony, powtarzające się na ≥ 3 stronach (tytuł rozdziału nie powtarza się na 30% stron). Numer strony szukam w pasie 12%, bo w kukurydzy stoi na 8,6% od dołu.
- **Dzielenie wyrazów**: `słowo-\nmała litera` jest zawsze sklejane, więc łamany złożony wyraz („młynarsko-\npiekarniczym”) traci myślnik.
- **Akapity**: dzielone według wcięcia, krótkiej linii z kropką, odstępu w pionie i zmiany stylu. Kontynuacja z poprzedniej strony (`cont`) jest doklejana. Etykiety wykresów usuwam heurystycznie (krótkie, mniejszy font).
- **Tabele**: `find_tables` uruchamiam tylko na stronach z ≥ 8 liniami siatki, więc tabele bez linii zostają tekstem. Wielowierszowe nagłówki powtarzam tylko pierwszym wierszem. Ciąg dalszy tabeli („Tabela 27. Cd.”) dziedziczy nagłówek poprzedniej, jeśli liczba kolumn się zgadza.
- **TOC**: 3 wpisy niedopasowane w wersjach dla producentów (sekcja zaczyna się wtedy na stronie wyliczonej z offsetu). Podnagłówki spoza TOC to heurystyka stylu: pogrubienie lub inna rodzina fontu, ≤ 12 słów, jedno zdanie.
- **GIORiN**: brak numerów stron, więc cytat ma postać „s. PDF n”. Opisy śnieci cuchnącej i karłowej są w jednej sekcji.
- **Kodowanie znaków**: mapa cp1250→cp1252 naprawia krzaki („Poznañ”, „redakcj¹”). Krzaki występują tylko na stronach redakcyjnych wersji dla producentów.
- **Flagi**: `has_pesticide_doses` pochodzi w praktyce z tytułu sekcji najniższego poziomu (212/212). Regex dawek w sąsiedztwie słów herbicyd/fungicyd/środek… wyklucza ciecz użytkową, nawożenie i wysiew. Sekcja „Dobór techniki stosowania środka” nie jest flagowana. Sekcje „Metody określania liczebności i progi szkodliwości” pod „Chemiczne metody” też nie, bo progi są potrzebne.
- **Excel**:
  - `threat_type="inne"` dla niejednoznacznych nagłówków („Agrofag”, „Szkodnik / choroba”).
  - Temperatury z kilkoma zakresami w jednej komórce dają `null`.
  - „ok 20” daje `temp_approx=true`.
  - Jednostka temperatury w arkuszu pszenicy nie jest podana (zakładamy °C, ale tylko w polach `*_c`; `temperature_raw` zostaje bez zmian).
- **`--all-crops`** (sprawdzone parsowanie i chunking 10 dodatkowych PDF, bez indeksowania):
  - 13 z 15 dokumentów ma pokrycie sekcjami 100%.
  - `jeczmien_doradcy`: spis treści sparsował się źle (4 sklejone wpisy, 0 dopasowanych), więc sekcje są bezużyteczne.
  - `owies_doradcy`: 8 z 38 wpisów niedopasowanych (nagłówki wersalikami).
  - `jeczmien_producenci`: 3 chunki ponad 450 tokenów (maks. 569).
  - Do poprawy, zanim te uprawy trafią do indeksu.
