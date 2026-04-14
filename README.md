# Rezept0r

Self-hosted Rezept-Extraktor fuer Webseiten und Videos mit Import nach [Tandoor Recipes](https://github.com/TandoorRecipes/recipes).

Optimiert fuer den Betrieb auf einem Raspberry Pi 3 (512 MB Container-Limit, 1 Worker).

## Features

- **Website-Extraktion** -- Rezepte von beliebigen Kochseiten (Chefkoch, Lecker, BBC Good Food, etc.)
- **Video-Extraktion** -- YouTube, TikTok, Instagram Reels, Vimeo, Reddit, Twitter/X
- **3-stufige Website-Analyse**: `recipe-scrapers` -> LD+JSON / Schema.org -> GPT-4o-mini Fallback
- **4-stufige Video-Analyse**: yt-dlp Metadaten -> Caption-Check -> Audio-Download -> Whisper-Transkription -> GPT-4o-mini
- **Naehrwert-Berechnung**: Bereits extrahiert -> USDA FoodData Central -> GPT-4o-mini Schaetzung
- **Tandoor-Import** per Klick (REST API + Bild-Upload)
- **Rezept-Verlauf** in lokaler SQLite-Datenbank
- **Echtzeit-Fortschritt** via Server-Sent Events (SSE)

## Unterstuetzte Plattformen

| Typ | Quellen |
|---|---|
| Video | YouTube, TikTok, Instagram Reels, Vimeo, Twitch, Twitter/X, Facebook, Reddit |
| Website | Alle Seiten mit Rezept-Schema (Schema.org), sowie beliebige Artikel per KI-Extraktion |

## Voraussetzungen

- Docker und Docker Compose
- OpenAI API-Key (fuer Whisper-Transkription und GPT-4o-mini)
- Optional: Tandoor-Instanz mit API-Token
- Optional: USDA FoodData Central API-Key

## Installation

### 1. Repository klonen

```bash
git clone <repo-url>
cd Rezept0r
```

### 2. Umgebungsvariablen konfigurieren

`.env`-Datei im Projektroot erstellen:

```env
OPENAI_API_KEY=sk-...
USDA_API_KEY=DEMO_KEY
TANDOOR_BASE_URL=http://tandoor:8080
TANDOOR_API_TOKEN=tda_...
```

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `OPENAI_API_KEY` | Ja | OpenAI API-Key fuer Whisper + GPT-4o-mini |
| `USDA_API_KEY` | Nein | USDA FoodData Central Key (Standard: `DEMO_KEY`) |
| `TANDOOR_BASE_URL` | Nein | URL der Tandoor-Instanz |
| `TANDOOR_API_TOKEN` | Nein | Tandoor Bearer-Token |
| `TMP_DIR` | Nein | Verzeichnis fuer temporaere Audio-Dateien (Standard: `/app/tmp`) |
| `FFMPEG_LOCATION` | Nein | Pfad zu ffmpeg (nur fuer lokale Windows-Entwicklung) |

### 3. Starten

```bash
docker compose up -d --build
```

Die App ist unter **http://localhost:88** erreichbar.

### Logs anzeigen

```bash
docker compose logs -f
```

## Lokale Entwicklung (ohne Docker)

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Zusaetzlich muss `yt-dlp` und `ffmpeg` lokal installiert sein fuer Video-Extraktion.

## Architektur

```
Browser
  |
  |  GET /api/extract/stream?url=...  (SSE)
  v
FastAPI (uvicorn, 1 Worker)
  |
  +-- Plattform-Erkennung (URL-Regex)
  |     |
  |     +-- Website?  -->  recipe-scrapers -> LD+JSON -> GPT-4o-mini
  |     +-- Video?    -->  yt-dlp Metadaten -> Caption-Check -> Audio/Whisper -> GPT-4o-mini
  |
  +-- Naehrwert-Anreicherung (USDA / GPT-4o-mini)
  +-- SQLite-Verlauf speichern
  +-- ExtractResponse an Browser (SSE event: result)
  |
  |  POST /api/import  (nach Klick auf "Importieren")
  v
Tandoor REST API
```

### Dateistruktur

```
main.py                           FastAPI-App, Routen, Health-Check
app/
  config.py                       Pydantic-Settings aus .env
  models.py                       Alle Pydantic-Schemas (Recipe, Tandoor*, SSE-Events)
  api/
    extract.py                    GET /api/extract/stream (SSE-Endpoint)
    tandoor.py                    POST /api/import
    history.py                    GET /api/history, DELETE /api/history/{id}
  extractors/
    base.py                       URL-Plattformerkennung (Video vs. Website)
    website.py                    3-stufige Website-Extraktion
    video.py                      4-stufige Video-Extraktion (yt-dlp + Whisper)
  services/
    openai_service.py             Whisper-Transkription + GPT-4o-mini Extraktion
    nutrition.py                  3-stufige Naehrwert-Berechnung
    tandoor_service.py            Tandoor REST-Client + Bild-Upload
    history_service.py            SQLite-Verlauf (CRUD)
  static/
    index.html                    SPA-Frontend
    style.css                     Styling
    app.js                        Frontend-Logik (SSE, UI)
```

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/` | Frontend (SPA) |
| `GET` | `/api/extract/stream?url=...` | Rezept extrahieren (SSE-Stream) |
| `POST` | `/api/import` | Rezept nach Tandoor importieren |
| `GET` | `/api/history` | Extraktions-Verlauf abrufen |
| `DELETE` | `/api/history/{id}` | Verlaufseintrag loeschen |
| `GET` | `/api/health` | Health-Check |

### SSE-Events

Der Extraktions-Endpoint streamt drei Event-Typen:

- **`status`** -- Fortschrittsupdates (`stage`, `message`, `progress` 0-100)
- **`result`** -- Fertiges Rezept als JSON (`ExtractResponse`)
- **`error`** -- Fehlermeldung

## Technische Hinweise

- **yt-dlp** wird immer als Subprocess aufgerufen (`asyncio.create_subprocess_exec`), nie ueber die Python-API, um den Event-Loop nicht zu blockieren
- **Whisper** hat ein Dateigroessen-Limit von 25 MB -- zu lange Videos fuehren zu einem Fehler
- **recipe-scrapers** laedt HTML selbststaendig -- es wird die URL uebergeben, nicht vorgeladenes HTML
- **Bild-Upload** nach Tandoor erfolgt per `PATCH` mit Multipart -- der `Content-Type`-Header wird nicht manuell gesetzt
- **SSE-Header** `X-Accel-Buffering: no` ist gesetzt fuer Nginx-Proxy-Kompatibilitaet
- Container laeuft mit 512 MB Memory-Limit und ohne Swap (SD-Karten-Schutz)

## Lizenz

Privates Projekt.
