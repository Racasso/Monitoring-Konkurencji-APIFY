# Monitoring konkurencji na Instagramie

Dokumentowe API do tworzenia raportów o publicznych profilach Instagram. Pomaga klientowi i account managerowi odpowiedzieć na pytanie: **co publikują konkurenci, jak często to robią, które posty osiągają najlepsze zaangażowanie i z kim widać sygnały współpracy?**

Aplikacja przyjmuje kampanię dla 3–5 konkurentów, zleca pobranie danych w tle i udostępnia kompletny raport pod jednym endpointem.

## Najważniejsze funkcje

- Tworzenie kampanii z oknem analizy od 1 do 365 dni i limitem do 50 postów na profil.
- Pobieranie postów i bieżącej liczby obserwujących przez aktora Apify Store.
- Liczenie częstotliwości publikacji, interakcji i engagement rate.
- Wskazywanie do trzech najlepszych postów na konkurenta.
- Zbieranie sygnałów współpracy: oznaczeń płatnej współpracy, sponsorów, oznaczonych kont, współautorów i wzmianek.
- Kolejkowanie pracy przez dokumenty job i przetwarzanie w jednym lub wielu workerach.
- Idempotentne zapisy kampanii, zleceń i postów.
- Jedno zapytanie GET zwraca kompletny raport kampanii.

## Pytanie biznesowe i metryki

Raport jest przeznaczony dla klienta oraz account managera. Pokazuje aktywność konkurentów w zadanym okresie i obserwowalne sygnały dotyczące ich treści oraz współprac.

- **Interakcje posta** = likes + comments. Wynik jest nieznany, jeśli brakuje którejś z tych wartości.
- **Engagement rate (%)** = (likes + comments) / snapshot liczby followers × 100. Liczba obserwujących pochodzi z chwili pobrania profilu, a nie z dnia publikacji. Wynik jest nieznany, jeśli brakuje danych lub liczba obserwujących wynosi zero.
- **Posty tygodniowo** = liczba postów w oknie / (liczba dni okna / 7).
- **Średni engagement rate** to średnia dostępnych wartości engagement rate dla postów w oknie.
- **Najlepsze posty**: maksymalnie trzy na konkurenta, sortowane po engagement rate, liczbie interakcji i dacie publikacji.
- **Sygnały współpracy** obejmują oznaczenie płatnej współpracy, sponsorów, oznaczone konta, współautorów i wzmianki. Sama wzmianka lub oznaczenie nie potwierdza płatnej umowy. Licznik płatnych współprac obejmuje wyłącznie posty z jawną wartością paid_partnership równą true.

Raport nie mierzy zasięgu ani wyświetleń zwykłych zdjęć. Licznik odtworzeń wideo może być dostępny, ale nie jest tym samym co zasięg. Prywatne profile i metryki ukryte przez Instagram mogą pozostać niedostępne. Jeśli liczba zebranych postów osiągnie ustawiony limit, raport oznacza wynik jako potencjalnie ucięty.

## Wymagania

- Python 3.12 — do lokalnego uruchomienia i testów.
- Docker z Docker Compose — do uruchomienia całego stosu lub samej bazy MongoDB 7.0.
- Token Apify z dostępem do używanego aktora.
- Połączenie z internetem dla workera pobierającego dane z Apify.

Wersje zależności Pythona są przypięte w requirements.txt. Stos obejmuje FastAPI, Pydantic v2, PyMongo, oficjalny klient apify-client, Uvicorn i pytest.

## Szybkie uruchomienie w Dockerze

1. W katalogu projektu skopiuj przykładową konfigurację:

   ```bash
   cp .env.example .env
   ```

2. W pliku .env ustaw APIFY_TOKEN. Nie umieszczaj prawdziwego tokena w kodzie ani nie commituj pliku .env — jest ignorowany przez Git.

3. Uruchom API, MongoDB i trzy workery:

   ```bash
   docker compose up --build --scale worker=3 -d
   ```

4. Sprawdź status kontenerów i połączenie API z MongoDB:

   ```bash
   docker compose ps
   curl --fail --silent --show-error http://localhost:8000/health
   ```

   Oczekiwana odpowiedź:

   ```json
   {"status":"ok"}
   ```

5. Otwórz interaktywną dokumentację: [http://localhost:8000/docs](http://localhost:8000/docs).

Jeśli port 8000 jest zajęty, ustaw API_PORT=18000 w .env i uruchom ponownie Compose. Możesz też przekazać port przy uruchomieniu:

```bash
API_PORT=18000 docker compose up --build --scale worker=3 -d
```

Wtedy API i Swagger UI będą dostępne pod http://localhost:18000 i http://localhost:18000/docs.

## Uruchomienie lokalne

W tym wariancie API i worker działają w lokalnym środowisku Pythona, a MongoDB w kontenerze.

1. Utwórz i aktywuj wirtualne środowisko Pythona 3.12, zainstaluj zależności i przygotuj .env:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   cp .env.example .env
   ```

   Uzupełnij APIFY_TOKEN w .env. Jeśli .env już istnieje, zachowaj go — ponowne kopiowanie mogłoby nadpisać konfigurację.

2. Uruchom MongoDB:

   ```bash
   docker compose up -d mongo
   ```

3. W pierwszym terminalu załaduj zmienne z .env i uruchom API:

   ```bash
   set -a
   source .env
   set +a
   uvicorn app.api:app --host "$API_HOST" --port "$API_PORT"
   ```

4. W drugim terminalu, z aktywnym .venv, załaduj te same zmienne i uruchom workera:

   ```bash
   set -a
   source .env
   set +a
   python -m app.worker
   ```

API będzie pod http://localhost:8000, a Swagger UI pod http://localhost:8000/docs. W trybie lokalnym API i worker używają MONGO_URI z .env, domyślnie mongodb://localhost:27017.

## Konfiguracja

Wartości domyślne pochodzą z .env.example, app/ i docker-compose.yml.

| Zmienna | Domyślna wartość | Znaczenie |
|---|---|---|
| APIFY_TOKEN | brak — wymagana do pobierania | Token klienta Apify. |
| APIFY_ACTOR_ID | apify/instagram-scraper | Identyfikator aktora. Kod korzysta z domyślnej wersji aktora. |
| APIFY_MAX_ITEMS_PER_RUN | 250 | Maksymalna liczba wyników przekazywana klientowi Apify dla jednego runu. |
| APIFY_MAX_TOTAL_CHARGE_USD_PER_RUN | 0.70 | Limit opłaty przekazywany dla każdego runu. Kampania wykonuje osobny run postów i osobny run profili. |
| MAX_POSTS_PER_COMPETITOR | 50 | Domyślny i konfigurowalny limit postów na konkurenta; model nie pozwala przekroczyć 50. |
| ANALYSIS_WINDOW_DAYS | 30 | Domyślna liczba dni analizowanego okna. |
| MONGO_URI | mongodb://localhost:27017 | URI MongoDB przy uruchomieniu lokalnym. W Compose API i worker łączą się z usługą mongo pod mongodb://mongo:27017. |
| MONGO_DATABASE | competitor_monitoring | Nazwa bazy MongoDB. |
| API_HOST | 127.0.0.1 | Host Uvicorna przy uruchomieniu lokalnym. |
| API_PORT | 8000 | Port API i publikowany port hosta w Compose. |
| WORKER_POLL_SECONDS | 2 | Odstęp między sprawdzeniami kolejki przez workera. |

Plik .env.example zawiera komplet ustawień. Prawdziwy APIFY_TOKEN przechowuj wyłącznie w lokalnym .env lub bezpiecznej konfiguracji środowiska uruchomieniowego.

## Użycie API

### Utworzenie kampanii

POST /campaigns wymaga nagłówka Idempotency-Key i 3–5 różnych nazw użytkowników. Można podać nazwę profilu, nazwę z @ albo adres profilu Instagram.

```bash
curl -i -X POST http://localhost:8000/campaigns \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: acme-competitors-run-1' \
  -d '{
    "campaign_key": "acme-competitors",
    "client_ref": "acme",
    "competitors": [
      {"username": "natgeo"},
      {"username": "disney"},
      {"username": "bbcnews"}
    ],
    "window_days": 30,
    "max_posts_per_competitor": 50
  }'
```

API waliduje żądanie, zapisuje dokument kampanii i dokument joba, a potem zwraca 202 Accepted. Przykładowa odpowiedź:

```json
{
  "campaign_id": "wygenerowany-identyfikator-kampanii",
  "job_id": "wygenerowany-identyfikator-zadania",
  "status": "queued"
}
```

W Swagger UI wpisz Idempotency-Key w osobnym polu parametru. W polu request body wklej sam obiekt JSON — bez komendy curl, opcji -H ani -d.

### Sprawdzenie joba i pobranie raportu

Worker atomowo pobiera job, kolejno uruchamia pobieranie postów i profili, a następnie zapisuje wyniki. Status sprawdzisz przez job_id:

```bash
curl http://localhost:8000/jobs/wygenerowany-identyfikator-zadania
```

Status może być queued, running, done albo failed. Po zakończeniu pobierz pełny dokument raportu, podstawiając campaign_id z odpowiedzi POST:

```bash
curl http://localhost:8000/campaigns/wygenerowany-identyfikator-kampanii
```

campaign_id generuje API. Nie zastępuj go nazwą użytkownika z Instagrama, campaign_key ani job_id.

### Przykładowy kształt raportu

Poniższy JSON pokazuje strukturę odpowiedzi. Wartości w nawiasach ostrych są placeholderami, a nie identyfikatorami ani danymi z konkretnego uruchomienia:

```json
{
  "_id": "<campaign_id>",
  "type": "campaign",
  "schema_version": 1,
  "created_at": "<data ISO 8601>",
  "updated_at": "<data ISO 8601>",
  "business_key": "acme-competitors",
  "client_ref": "acme",
  "status": "done",
  "analysis": {
    "platform": "instagram",
    "start": "<początek okna ISO 8601>",
    "end": "<koniec okna ISO 8601>",
    "window_days": 30,
    "max_posts_per_competitor": 50,
    "collaboration_interpretation": "Mentions and tags are evidence signals; they do not prove a paid contract."
  },
  "competitors": [
    {
      "username": "<nazwa_profilu>",
      "profile_url": "https://www.instagram.com/<nazwa_profilu>/",
      "profile_snapshot": {
        "followers": null,
        "captured_at": "<data ISO 8601>"
      },
      "metrics": {
        "posts_in_window": 0,
        "posts_per_week": 0.0,
        "mean_engagement_rate_pct": null,
        "paid_collaboration_posts": 0,
        "posts_may_be_truncated": false
      },
      "best_posts": [],
      "collaborations": [],
      "posts": []
    },
    {
      "username": "<nazwa_profilu_2>",
      "profile_url": "https://www.instagram.com/<nazwa_profilu_2>/",
      "profile_snapshot": {"followers": null, "captured_at": "<data ISO 8601>"},
      "metrics": {
        "posts_in_window": 0,
        "posts_per_week": 0.0,
        "mean_engagement_rate_pct": null,
        "paid_collaboration_posts": 0,
        "posts_may_be_truncated": false
      },
      "best_posts": [],
      "collaborations": [],
      "posts": []
    },
    {
      "username": "<nazwa_profilu_3>",
      "profile_url": "https://www.instagram.com/<nazwa_profilu_3>/",
      "profile_snapshot": {"followers": null, "captured_at": "<data ISO 8601>"},
      "metrics": {
        "posts_in_window": 0,
        "posts_per_week": 0.0,
        "mean_engagement_rate_pct": null,
        "paid_collaboration_posts": 0,
        "posts_may_be_truncated": false
      },
      "best_posts": [],
      "collaborations": [],
      "posts": []
    }
  ],
  "summary": {
    "competitor_count": 3,
    "total_posts": 0,
    "paid_collaboration_posts": 0
  }
}
```

Pola posts, best_posts i collaborations zawierają odpowiednio zebrane posty, wybrane najlepsze posty i informacje o wykrytych sygnałach współpracy. Raport jest składany przez agregację MongoDB używaną przez GET /campaigns/{campaign_id}.

## Jak przechowywane są dane

- **campaigns** przechowuje definicję kampanii, okno analizy, profile konkurentów, snapshot obserwujących i status.
- **jobs** przechowuje żądanie, status, liczbę prób, identyfikatory runów Apify, koszt i liczniki wyników.
- **posts** przechowuje snapshoty postów osobno, aby dokument kampanii nie rósł bez ograniczeń. Odpowiedź kampanii osadza posty z wybranego okna przy pomocy agregacji MongoDB.

Dokumenty campaign, job i post_snapshot zawierają pola _id, type, schema_version, created_at i updated_at. Indeksy są tworzone przy starcie API i workera. Obejmują unikalny klucz kampanii, unikalny klucz idempotencji joba, indeks kolejki oraz unikalną parę (campaign_id, post_url) dla postów. Zapis postów używa upsertu, więc ponowny wynik tego samego URL w tej samej kampanii aktualizuje istniejący dokument.

Worker pozwala przyjąć żądanie bez czekania na scrapowanie w połączeniu API. Dodatkowe repliki uruchomisz przez --scale worker=3; atomowe pobieranie joba zapobiega przejęciu tego samego zadania przez dwa workery.

## Koszt Apify

Przy limicie 50 postów dla każdego z 3–5 konkurentów kampania może zwrócić do 150–250 postów oraz 3–5 wyników profili, czyli łącznie 153–255 wyników. Według [cennika aktora](https://apify.com/apify/instagram-scraper/pricing) w dniu 2026-11-03 daje to orientacyjnie:

- **Starter:** 0,35–0,59 USD za wyniki przy stawce 2,30 USD / 1 000.
- **Free:** 0,41–0,69 USD za wyniki przy stawce 2,70 USD / 1 000, przed wykorzystaniem dostępnego kredytu.

Wyliczenie dotyczy wyników. Plan Starter ma osobną opłatę abonamentową. Ceny mogą się zmieniać, dlatego przed użyciem sprawdź aktualny cennik.

Kod przekazuje do każdego runu limit max_items, limit opłaty max_total_charge_usd (domyślnie 0,70 USD) i timeout 10 minut. Ponieważ posty i profile pobierane są w dwóch runach, łączny skonfigurowany limit opłaty wynosi domyślnie 1,40 USD na kampanię. Rzeczywisty koszt runu zapisuje się w jobie jako usage_total_usd, jeśli Apify go zwróci. Szczegóły parametrów opisuje [dokumentacja klienta Apify dla Pythona](https://docs.apify.com/api/client/python/reference/next/class/ActorClient).

## Testowanie

Po aktywowaniu .venv i zainstalowaniu zależności uruchom:

```bash
python -m pytest -q
```

Testy sprawdzają metryki i normalizację na próbkach z tests/fixtures/, obsługę brakujących metryk oraz idempotentny upsert postów. Test upsertu używa kolekcji testowej; unikalny indeks dla produkcyjnej kolekcji MongoDB jest definiowany w app/db.py.

## Komendy operacyjne i diagnostyka

| Polecenie | Działanie |
|---|---|
| docker compose up --build | Buduje obrazy i uruchamia API, MongoDB oraz jeden worker. |
| docker compose up --build --scale worker=3 -d | Uruchamia stos w tle z trzema workerami. |
| docker compose ps | Pokazuje stan usług. |
| docker compose logs -f api worker | Śledzi logi API i workerów. |
| docker compose up -d mongo | Uruchamia samą bazę MongoDB, np. do pracy lokalnej. |
| python -m app.worker | Uruchamia lokalny worker po załadowaniu .env. |
| uvicorn app.api:app ... | Uruchamia lokalny serwer API; pełne polecenie jest w sekcji uruchomienia lokalnego. |
| python -m pytest -q | Uruchamia testy w aktywnym .venv. |
| docker compose stop | Zatrzymuje kontenery, pozostawiając je i dane. |
| docker compose down | Usuwa kontenery i sieć Compose; nazwany wolumen MongoDB pozostaje. |

Typowe problemy:

- **422 Unprocessable Entity przy POST /campaigns:** sprawdź poprawność JSON, wymagany nagłówek Idempotency-Key i listę 3–5 różnych konkurentów.
- **404 Campaign not found:** użyj campaign_id zwróconego przez POST /campaigns. Nazwa profilu, campaign_key i job_id nie są identyfikatorem kampanii.
- **Job ma status running:** worker nadal pobiera posty i profile. Odśwież GET /jobs/{job_id}. Każdy run Apify ma limit czasu 10 minut.
- **Job ma status failed:** odczytaj error_type przez GET /jobs/{job_id} i sprawdź docker compose logs -f api worker. Po usunięciu przyczyny wyślij nowe żądanie z nowym Idempotency-Key, aby utworzyć kolejny job.
- **API nie startuje, bo port jest zajęty:** ustaw API_PORT na wolny port w .env, np. 18000, i uruchom Compose ponownie.
- **Worker zgłasza brak konfiguracji Apify:** sprawdź, czy .env zawiera APIFY_TOKEN. Nie wklejaj go do Swaggera, logów ani repozytorium.

## Struktura projektu

```text
.
├── app/
│   ├── api.py       # endpointy FastAPI
│   ├── apify.py     # wywołania aktora i normalizacja wyników
│   ├── db.py        # indeksy, upserty i agregacja raportu
│   ├── models.py    # modele dokumentów i walidacja Pydantic
│   └── worker.py    # pobieranie i przetwarzanie jobów
├── tests/
│   ├── fixtures/    # ograniczone próbki wyników aktora
│   ├── test_metrics.py
│   └── test_idempotency.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Źródła i informacje do uzupełnienia

Opis opracowano na podstawie kodu w app/, konfiguracji .env.example, .gitignore, .dockerignore, Dockerfile, docker-compose.yml, przypiętych zależności w requirements.txt, testów i próbek w tests/fixtures/ oraz wymagań przekazanych dla projektu.

Przydatna dokumentacja:

- [FastAPI](https://fastapi.tiangolo.com/tutorial/)
- [Pydantic](https://docs.pydantic.dev/latest/)
- [PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/)
- [Docker Compose](https://docs.docker.com/compose/)
- [pytest](https://docs.pytest.org/en/stable/)
- [Apify Instagram Scraper — strona aktora](https://apify.com/apify/instagram-scraper)
- [Apify Instagram Scraper — cennik](https://apify.com/apify/instagram-scraper/pricing)
- [Apify Python Client — ActorClient](https://docs.apify.com/api/client/python/reference/next/class/ActorClient)

**Do uzupełnienia przed publikacją:** autor lub organizacja, decyzja o licencji i plik LICENSE oraz adres publicznego repozytorium GitHub (brak skonfigurowanego remote). Repozytorium nie zawiera zrzutów ekranu; interaktywną demonstracją API jest /docs po uruchomieniu aplikacji.
