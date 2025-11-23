# Lecture Cleanup KI Pipeline (Deutsch)

Dieses Tool wandelt lange Vorlesungstranskripte in gut lesbares Markdown für **Obsidian** und Wissensdatenbanken um.
Es bewahrt den Inhalt vollständig, korrigiert Interpunktionsfehler, Groß-/Kleinschreibung und typische ASR-Erkennungsfehler.
Außerdem fügt es eine einfache Struktur hinzu und sorgt für konsistente Terminologie zwischen Textblöcken.

* **Eingabe:** `.txt` (Zeilen, optional mit `[HH:MM:SS,mmm]`) oder `.srt` (noch in Entwicklung aufgrund unterschiedlicher Formate).
* **Ausgabe:** eine `.md`-Datei und ein `.csv`-Bericht mit QC-Metriken.
* Arbeitet in überlappenden Textblöcken („Chunks“) und unterstützt Terminologie-Hinweise zwischen Abschnitten.
* Unterstützt drei Bearbeitungsmodi: `strict`, `normal`, `creative`.

## Funktionsweise (Kurzüberblick)

1. Liest die Eingabedatei (`.txt` oder `.srt`). Bei `.txt` können Zeitstempel in eckigen Klammern am Zeilenanfang stehen.
2. Teilt den Text in Blöcke mit Überlappung, ohne nach Möglichkeit Zeilen zu trennen.
3. Fügt „Kontext“ aus dem vorherigen Fragment hinzu (nur lesend) — `raw`, `cleaned` oder `none`.
4. Sendet den Block mit strikten Prompts an OpenAI.
5. Bei `.txt`-Dateien mit Zeitstempeln werden diese in Überschriften eingefügt. Standard: Zeitstempel des Blockanfangs für alle Überschriften; optional `--process-timecodes-by-ai`, dann setzt das Modell pro Überschrift einen Zeitcode anhand der gelieferten Stempel.
6. Entfernt doppelte Textstellen an den Blockgrenzen.
7. Erfasst Informationen über „merged_terms“ und übergibt sie an folgende Blöcke (`<!-- merged_terms: ... -->`, nur neue Änderungen).
8. Fügt alle Blöcke zu einer endgültigen Markdown-Datei zusammen; optional wird am Ende eine automatisch erzeugte Zusammenfassung hinzugefügt.
9. Erstellt einen QC-Bericht, der die Änderungen jedes Blocks anzeigt.

## Bildschirmfotos

<img width="500" alt="cleanup-pipeline01" src="https://github.com/user-attachments/assets/9a096d90-fe5f-4c7a-8170-3dd25917ee8d" />
<img width="500" alt="cleanup-pipeline02" src="https://github.com/user-attachments/assets/20d11eda-0628-49cf-a987-62340eb19d77" />

---

<img width="500" alt="cleanup-pipeline03" src="https://github.com/user-attachments/assets/bb4cc7b1-eba5-401e-9b50-be5a65bd235e" />
<img width="500" alt="cleanup-pipeline04" src="https://github.com/user-attachments/assets/0d992cd8-ce0f-4f3a-8396-e96e09beeb2d" />

---

## Algorithmus (Detailliert)

* **Eingabezeilen:**

  * TXT: Jede Zeile bleibt erhalten. Zeilen im Format `[HH:MM:SS,mmm] Text` liefern Zeitcodes; standardmäßig wird der Blockstart an alle Überschriften gehängt, oder die Rohstempel werden mit `--process-timecodes-by-ai` an das Modell gegeben, damit es pro Überschrift einen Zeitcode setzt.
  * SRT: Nur der Text wird übernommen, Zeitcodes nicht. Empfehlung: SRT → zeilenbasiertes TXT mit Zeitstempeln konvertieren, um alle Funktionen zu nutzen.
* **Chunking (zeilenbasiert):**

  * `chunk_text_line_preserving(...)` gruppiert Text bis zur Grenze `txt_chunk_chars` mit Überlappung `txt_overlap_chars`.
  * Kontext = die letzten `txt_overlap_chars` des vorherigen Blocks (nur lesend).
* **OpenAI-Aufruf:**

  * System-Prompt abhängig vom Modus: `strict` / `normal` / `creative`.
  * Benutzer-Prompt enthält: Sprache, Füllwort-Listen, Stil für Randbemerkungen/Witze, `TERM_HINTS` (versteckt), „Kontext“ und den eigentlichen Textblock.
* **Terminologie-Normalisierung:**

  * Extrahiert `<!-- merged_terms: ... -->` aus der Modellantwort.
  * Erstellt eine globale Zuordnung *kanonisch → Varianten*.
  * Übergibt sie als `TERM_HINTS` an den nächsten Aufruf (versteckt, nicht ausgegeben).
  * Im Kommentar des aktuellen Blocks werden nur neue Begriffe aufgeführt.
* **Zeitcodes:**

  * Für TXT-Dateien mit Zeitangabe: Standard ist der Blockstart als `[HH:MM:SS](#t=HH:MM:SS)` an jeder Überschrift. Optional `--process-timecodes-by-ai`: Rohzeitstempel bleiben im Prompt, das Modell setzt pro Überschrift einen Zeitcode und entfernt die Rohmarker aus dem Text.
* **Deduplizierung:**

  * Vergleicht das Ende des vorherigen und den Anfang des nächsten Blocks im Fenster `stitch_dedup_window_chars`; entfernt Duplikate.
* **Zusammenfassung:**

  * Optional wird am Ende des Dokuments eine nicht-autorisierte Zusammenfassung hinzugefügt.
* **QC-Bericht:**

  * Erstellt CSV mit Länge, Ähnlichkeit zum Original und Änderungsrate.

## Installation

1. Python 3.10 oder höher installieren.
2. Eine `.env`-Datei im Projektverzeichnis erstellen (oder kopieren):

   ```bash
   cp .env_default .env
   ```

   Danach den Schlüssel eintragen:

   ```env
   OPENAI_API_KEY=dein_schlüssel
   ```
3. Einmalige Initialisierung ausführen:

   ```bash
   ./init_once.sh
   ```

   Dieses Skript erstellt `.venv` und installiert Abhängigkeiten (`pyyaml`, `openai`, `google-generativeai`).

## Verwendung

Es wird empfohlen, die `.sh`-Wrapper zu verwenden, da sie `.venv` aktivieren und das Python-Skript mit den richtigen Parametern aufrufen.
⚠️ **Achtung:** Verwende unbedingt die neueste Version des `openai`-Pakets – alte Versionen können Abstürze oder fehlerhafte Ergebnisse verursachen! Für Gemini-Unterstützung wird `google-generativeai` durch `init_once.sh` installiert.

### LLM-Provider wählen (Adapter)

- Den Provider in `config.yaml` unter `llm.provider` setzen (Standard: `openai`).
- Per CLI überschreiben mit `--llm-provider openai|gemini|dummy|...`.
- API-Schlüssel in `.env` im Projektverzeichnis ablegen:
  - OpenAI: `OPENAI_API_KEY=...`
  - Gemini: `GOOGLE_API_KEY=...`

Die Pipeline ist anbieterunabhängig und verwendet eine einheitliche Adapter-Schnittstelle. Um einen neuen Provider hinzuzufügen, `aiadapters/dummy_adapter.py` kopieren, `LLMAdapter.generate` implementieren und in `aiadapters/factory.py` registrieren.

### Protokollierungsstufe

- Konfiguration: `logging.level` in `config.yaml` auf `info`, `debug` oder `trace` setzen.
- CLI-Überschreibungen:
  - `--debug` → Debug-Logs (ohne vollständige Prompts/Antworten)
  - `--trace` → sehr ausführlich; druckt vollständige LLM-Prompts und -Antworten (groß, sensibel)

* **Einzeldatei:**

  ```bash
  ./lecture_cleanup.sh --input input/lecture.txt --lang uk
  ```
* **Stapelverarbeitung aller `.txt`-Dateien (Standard: `./input`):**

  ```bash
  ./bulk_cleanup.sh --lang uk
  # oder in einem anderen Verzeichnis
  ./bulk_cleanup.sh --lang uk --indir ./notes
  ```

**Ausgabedateien** werden im Verzeichnis `./output` gespeichert:

* `lecture.md` — Endgültige Markdown-Datei
* `lecture_qc_report.csv` — QC-Bericht

## CLI-Parameter (Wichtigste)

Diese Parameter werden über die `.sh`-Skripte an `scripts/run_pipeline.py` übergeben.

* `--input` *(erforderlich)* — Pfad zu `.txt` oder `.srt`
* `--format` — `txt` oder `srt` (wird sonst automatisch erkannt)
* `--outdir` — Ausgabeverzeichnis (Standard: `output`)
* `--lang` — `ru`, `uk`, `en`
* `--glossary` — Pfad zu einer Glossardatei (ein Begriff pro Zeile)
* `--txt-chunk-chars` — Blockgröße in Zeichen (überschreibt Konfigurationswert)
* `--txt-overlap-chars` — Überlappung in Zeichen
* `--include-timecodes` — Zeitcodes in Überschriften einfügen (für TXT)
* `--process-timecodes-by-ai` / `--no-process-timecodes-by-ai` — Rohzeitstempel an das Modell geben, damit es pro Überschrift Zeitcodes setzt (TXT mit Zeilen `[HH:MM:SS,mmm] ...`)
* `--use-context-overlap {raw,cleaned,none}` — Quelle des Kontexts für den nächsten Block
* `--debug` — Debug-Logs (ohne vollständige Prompts/Antworten)
* `--trace` — sehr ausführlich; druckt vollständige LLM-Prompts und -Antworten
* `--request-delay <Sekunden>` — Verzögerung zwischen LLM-Anfragen (0 = aus)
* `--chunks <Spezifikation>` — nur bestimmte Blöcke verarbeiten; z. B. `1,3,7-9,23` (1-basiert)
* `--retry-attempts <N>` — fehlgeschlagene LLM-Anfragen bis zu N‑mal erneut versuchen (1 = kein Retry)
* `--context-file <Pfad>` — Datei mit dateispezifischem Kontext; wird im USER‑Prompt direkt nach dem allgemeinen Satz „Context“ eingefügt (gilt für alle Blöcke). Mehrfach nutzbar; Inhalte werden in Reihenfolge zusammengefügt.

**Beispiele**

```bash
# Standardlauf (Ukrainisch, TXT automatisch erkannt)
./lecture_cleanup.sh --input input/lec1.txt --lang uk

# SRT (noch experimentell)
./lecture_cleanup.sh --input input/lec1.srt --lang uk --format srt

# Anpassung der Blockgröße und Überlappung
./lecture_cleanup.sh --input input/lec1.txt --lang uk \
  --txt-chunk-chars 6000 --txt-overlap-chars 600

# Überlappung mit bereinigtem Kontext
./lecture_cleanup.sh --input input/lec1.txt --lang uk --use-context-overlap cleaned

# Mit Glossar und Zeitcodes
./lecture_cleanup.sh --input input/lec1.txt --lang uk --glossary data/my_glossary.txt --include-timecodes

# Zeitcodes werden vom Modell pro Überschrift anhand der Rohstempel gesetzt
./lecture_cleanup.sh --input input/lec1.txt --lang uk --include-timecodes --process-timecodes-by-ai

# Debug-Modus aktivieren (ohne vollständige Texte)
./lecture_cleanup.sh --input input/lec1.txt --lang uk --debug

# Trace aktivieren (mit vollständigen Prompts/Antworten)
./lecture_cleanup.sh --input input/lec1.txt --lang uk --trace
```

## Konfiguration (`config.yaml`)

Die meisten Optionen können über CLI-Parameter überschrieben werden.

Allgemein
- `language`: Sprache (`ru`, `uk`, `en`, `de`)
- `format`: `txt` oder `srt` (überschreibt automatische Erkennung)
- `txt_chunk_chars`: Blockgröße (Standard: 6500)
- `txt_overlap_chars`: Überlappung (Standard: 500)
- `use_context_overlap`: `raw`, `cleaned` oder `none` (Standard `raw`)
- `stitch_dedup_window_chars`: Fenster zur Deduplizierung (null = wie Überlappung, 0 = aus)
- `include_timecodes_in_headings`: Zeitcodes in Überschriften (für TXT)
- `process_timecodes_by_ai`: Rohzeitcodes im Prompt lassen und das Modell pro Überschrift Zeitcodes setzen lassen (TXT mit Zeitstempeln)
- `content_mode`: `strict` / `normal` / `creative`

  * `strict`: nur minimale Oberflächenkorrekturen
  * `normal`: bessere Lesbarkeit, leichte Umstellungen erlaubt
  * `creative`: freiere Strukturierung; kontextbasierte Terminologie hat Vorrang vor Häufigkeit (zur Vermeidung von ASR-Fehlern)
* `suppress_edit_comments`: entfernt HTML-Kommentare im finalen Markdown
* `highlight_asides_style`: `italic` oder `blockquote` für Randbemerkungen/Witze
* `append_summary`: Zusammenfassung am Ende hinzufügen
* `summary_heading`: Überschrift des Zusammenfassungsabschnitts
* `parasites`: Pfade zu Füllwortlisten je Sprache
* `llm.request_delay_seconds`: Verzögerung zwischen LLM-Anfragen (Sekunden); hilft gegen Rate Limits; 0 = aus
* `retry.attempts`: globale Standardanzahl an Versuchen (1 = kein Retry)
* `retry.pause_seconds`: zusätzliche Wartezeit, die zu einer ggf. vom Provider vorgeschlagenen Wartezeit addiert wird; ohne Vorschlag allein genutzt
* `llm.openai.retry.attempts`: Versuche für OpenAI (überschreibt global)
* `llm.openai.retry.pause_seconds`: zusätzliche Wartezeit für OpenAI (addiert zur Provider-Empfehlung; sonst allein)
* `llm.gemini.retry.attempts`: Versuche für Gemini (überschreibt global)
* `llm.gemini.retry.pause_seconds`: zusätzliche Wartezeit für Gemini (addiert zur Provider-Empfehlung; sonst allein)

LLM
- `llm.provider`: `openai`, `gemini` oder eigener Adapter
- `llm.openai.model`: Modellname (z. B. `gpt-5-mini`)
- `llm.openai.temperature`: Zahl
- `llm.openai.top_p`: Zahl oder null
- `llm.gemini.model`: Modellname (z. B. `gemini-2.5-pro`)
- `llm.gemini.temperature`: Zahl
- `llm.gemini.top_p`: Zahl oder null

### Überlappungs-Kontext (Overlap)

* `txt_overlap_chars` definiert die maximale Kontextlänge.
* Quelle: `raw` oder `cleaned` (ohne HTML-Kommentare). Wenn `cleaned` leer → automatischer Fallback auf `raw` mit Warnung.
* Kürzungsreihenfolge:

  1. Ganze Zeilen
  2. Falls zu lang — nach Sätzen trennen (`.!?…`)
  3. Falls erster Satz zu lang — nach Wörtern kürzen; falls Wort zu lang — Ende innerhalb des Budgets behalten
* Keine Steuerzeichen; natürliche Reihenfolge; Gesamtlänge ≤ Budget.

## Terminologiekontrolle zwischen Blöcken

* Das Modell dokumentiert normalisierte Begriffe in `<!-- merged_terms: ... -->`.
* Die Pipeline sammelt diese Daten und übergibt sie als `TERM_HINTS` an folgende Blöcke.
* Kommentare zeigen nur neue Einträge des jeweiligen Blocks.
* Wenn ein kanonischer Begriff später mit einer neuen Schreibweise auftritt, wird er in einem Cluster zusammengeführt und einheitlich verwendet.

## Verzeichnisstruktur

* `input/` — Eingabedateien (`.txt` oder `.srt`)
* `output/` — Ausgabedateien (`.md`, `_qc_report.csv`)
* `data/parasites_*.txt` — Füllwortlisten je Sprache
* `prompts/` — System- und Benutzer-Prompt-Vorlagen
* `scripts/run_pipeline.py` — Hauptlogik
* `scripts/slides_stub.py` — Vorlage für zukünftige Slide-Unterstützung
* `init_once.sh`, `lecture_cleanup.sh`, `bulk_cleanup.sh` — Start-Skripte

## Hinweise

* Lege eine `.env`-Datei an und speichere den API-Schlüssel nicht im Git-Repository.
* Für Debug-Zwecke `suppress_edit_comments: false` in `config.yaml` lassen.
* `--trace` hilft beim Analysieren vollständiger Prompts und Antworten; `--debug` zeigt Metadaten ohne vollständige Texte.

## Einschränkungen

* **SRT** befindet sich noch in Entwicklung, da mehrere Varianten existieren.

  * Derzeit ohne Zeitcode-Einfügen in Überschriften.
  * Zukünftig wird ein Standardisierer implementiert, der alle SRT-Dateien in ein einheitliches TXT-Format mit Zeitstempeln konvertiert.
* Terminologiekontrolle basiert auf Kommentaren des Modells; wenn keine Normalisierung erkannt wurde, fehlt der Hinweis.
* Unterstützte Sprachen: RU / UK / EN / DE (mit Füllwortlisten). Andere Sprachen funktionieren ohne Wörterlisten.
* Zeitcodes sind nur annähernd (Beginn jedes Blocks), sofern `--process-timecodes-by-ai` nicht aktiv ist. Für genauere Ergebnisse kleinere Blockgrößen oder AI-Zeitcode-Modus verwenden.
* Bei der Zusammenfassung wird der gesamte bereinigte Text auf einmal gesendet:

  * verdoppelt die Token-Nutzung
  * kann zum Absturz führen, wenn die Modellkontextgröße überschritten wird.

## Lizenz

Dieses Projekt steht unter der **MIT-[Lizenz](LICENSE)** und wird **OHNE JEGLICHE GEWÄHRLEISTUNG** bereitgestellt.
