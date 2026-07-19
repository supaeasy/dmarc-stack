# dmarc-stack

DMARC-Reports automatisch per IMAP abholen, parsen und in Grafana visualisieren —
als Docker-Stack für **Synology DSM 7.2+ mit Portainer**.

Zusammengeführt aus [LukeCallaghan/dmarc-visualizer](https://github.com/LukeCallaghan/dmarc-visualizer)
(Grafana-Dashboard + Stack-Idee) und [domainaware/parsedmarc](https://github.com/domainaware/parsedmarc)
(Parser, offizielles Docker-Image). Lizenz: Apache 2.0, wie beide Upstream-Projekte.

| Komponente | Image | Version |
|---|---|---|
| parsedmarc | `ghcr.io/domainaware/parsedmarc` | 10.2.2 |
| Elasticsearch | `docker.elastic.co/elasticsearch/elasticsearch` | 8.19.18 (Support bis Juli 2027) |
| Grafana OSS | `grafana/grafana` | 12.4.5 (Security-Support bis Mai 2027) |

## Was ist anders als im alten dmarc-visualizer?

* **Keine selbstgebauten Images mehr.** Der alte Stack baute parsedmarc und ein
  stark angepasstes Grafana per Dockerfile — genau diese Builds scheiterten auf
  Synology Container Manager ([Issue #1](https://github.com/LukeCallaghan/dmarc-visualizer/issues/1)).
  Hier laufen ausschließlich unveränderte Stock-Images; Dashboard und
  Datasources kommen per Grafana-Provisioning (Bind-Mount) rein.
* **Offizielles parsedmarc-Image** statt pip-Install in Alpine. Aktuelle
  parsedmarc-Version, Multi-Arch, gepflegt vom Upstream.
* **Kein MaxMind/GeoIP-Setup mehr nötig.** parsedmarc 10.x bringt eine
  IPinfo-Lite-Datenbank mit und aktualisiert sie selbst. GeoIP.conf, cron und
  Lizenzschlüssel aus dem alten Repo entfallen ersatzlos.
* **Docker-DNS statt fester Container-IPs** (`elasticsearch:9200` statt `10.0.2.2`).
* **Alles an einem Ort:** Konfiguration UND Daten liegen als Bind-Mounts
  unter `/volume2/docker/dmarc-stack` — nichts versteckt sich in
  Docker-Volumes. Dafür braucht es einmalig ein `chown` der Datenordner
  (Elasticsearch läuft als uid 1000, Grafana als uid 472 — siehe Schritt 2).
* **Tägliche Elasticsearch-Indizes** (parsedmarc-Default). Damit ein
  mehrjähriger Report-Bestand das Shard-Limit nicht sprengt, ist
  `cluster.max_shards_per_node=4000` gesetzt (Default wäre 1000).
* Elasticsearch 6.x/8.18 → **8.19.17**, Grafana 11.6 → **12.4.5**.

## Architektur

```
IMAP-Postfach ──► parsedmarc ──► Elasticsearch ──► Grafana (Port 3002)
 (DMARC-Mails)    (watch-Modus)   (Named Volume)    (Dashboard "DMARC Reports")
```

parsedmarc läuft dauerhaft im Watch-Modus: Er verarbeitet beim Start alle Mails
im `reports_folder`, verschiebt sie nach `Archive` und wartet dann per
IMAP IDLE auf neue Reports.

---

# Installation auf dem Synology NAS (DS1621+)

## Schritt 0 — Voraussetzungen

* DSM 7.2+, Container Manager installiert, Portainer CE läuft
* SSH-Zugang aktiviert (Systemsteuerung → Terminal & SNMP → SSH)
* **RAM:** Die Defaults (`ES_HEAP=2g`, `ES_MEM_LIMIT=4g`) passen für ein NAS
  mit 16 GB+ RAM. Bei der 4-GB-Werksbestückung auf `ES_HEAP=1g` /
  `ES_MEM_LIMIT=2g` reduzieren.
* Ein IMAP-Postfach, in dem die DMARC-Reports ankommen, mit Zugangsdaten.

## Schritt 1 — vm.max_map_count prüfen (und nur bei Bedarf setzen)

Elasticsearch verweigert den Start (Exit-Code 78), wenn der Kernel-Parameter
`vm.max_map_count` unter 262144 liegt. **Erst prüfen** — viele
DSM-Installationen stehen bereits ab Werk auf 262144:

```sh
sysctl vm.max_map_count
```

Ist der Wert ≥ 262144: diesen Schritt komplett überspringen. Ist er
niedriger (typisch 65530), als Boot-Aufgabe hinterlegen, damit er jeden
Neustart und jedes DSM-Update übersteht:

1. **Systemsteuerung → Aufgabenplaner → Erstellen → Ausgelöste Aufgabe →
   Benutzerdefiniertes Skript**
2. Allgemein: Name `es-max-map-count`, Benutzer **root**, Ereignis **Hochfahren**
3. Aufgabeneinstellungen → Benutzerdefiniertes Skript:
   ```sh
   sysctl -w vm.max_map_count=262144
   ```
4. Speichern und die Aufgabe einmal **manuell ausführen** (Rechtsklick →
   Ausführen), damit der Wert sofort gilt — ohne Neustart.

> `/etc/sysctl.conf` direkt zu editieren funktioniert auch, wird aber von
> DSM-Updates gerne überschrieben. Der Aufgabenplaner-Weg überlebt Updates.

## Schritt 2 — Konfig-Ordner auf dem NAS anlegen

Per SSH (Benutzer mit Admin-Rechten):

```sh
sudo mkdir -p /volume2/docker/dmarc-stack
cd /volume2/docker/dmarc-stack
sudo git clone https://github.com/supaeasy/dmarc-stack.git .

# Datenordner anlegen und den Container-Usern übereignen
# (Elasticsearch läuft als uid 1000, Grafana als uid 472):
sudo mkdir -p data/elasticsearch data/grafana
sudo chown -R 1000:0 data/elasticsearch
sudo chown -R 472:0 data/grafana
```

Falls `git` auf dem NAS fehlt (Git Server aus dem Paketzentrum installieren
oder): Repo als ZIP von GitHub laden und den Inhalt per File Station nach
`/volume2/docker/dmarc-stack` hochladen — die `mkdir`/`chown`-Befehle oben
sind trotzdem per SSH nötig. Am Ende muss es so aussehen:

```
/volume2/docker/dmarc-stack/
├── docker-compose.yml
├── data/
│   ├── elasticsearch/   (uid 1000)
│   └── grafana/         (uid 472)
├── grafana/
│   ├── dashboards/Grafana-DMARC_Reports.json
│   └── provisioning/...
└── parsedmarc/parsedmarc.ini.example
```

## Schritt 3 — parsedmarc.ini anlegen

```sh
cd /volume2/docker/dmarc-stack/parsedmarc
sudo cp parsedmarc.ini.example parsedmarc.ini
sudo vim parsedmarc.ini        # oder nano / File Station-Editor
sudo chmod 644 parsedmarc.ini  # Container-User (uid 1000) muss lesen dürfen
```

Eintragen: IMAP-`host`, `user`, `password`. Der Rest ist vorkonfiguriert
(Watch-Modus, Batch 500, monatliche Indizes). Die Datei bleibt nur auf dem
NAS — sie steht in `.gitignore` und gehört nie ins Repo.

**Hinweis zum Postfach:** Verarbeitete Mails werden in den IMAP-Ordner
`Archive` verschoben (nicht gelöscht). Wenn dein Mailserver den Ordner nicht
automatisch anlegt, vorher manuell erstellen.

## Schritt 4 — Stack in Portainer anlegen

1. Portainer → **Stacks → Add stack**
2. Name: `dmarc-stack`
3. Build method: **Repository**
   * Repository URL: `https://github.com/supaeasy/dmarc-stack`
   * Repository reference: `refs/heads/main`
   * Compose path: `docker-compose.yml`
   * Optional: **GitOps updates / Polling** aktivieren, dann zieht Portainer
     Compose-Änderungen aus dem Repo automatisch nach.
4. **Environment variables** hinzufügen (siehe `.env.example`):
   * `GRAFANA_ADMIN_PASSWORD` = *ein richtiges Passwort*
   * optional `ES_HEAP`, `ES_MEM_LIMIT`, `GRAFANA_PORT`, `CONFIG_DIR`
5. **Deploy the stack**

> Wichtig: Die Bind-Mounts im Compose-File sind absichtlich **absolute Pfade**
> (`/volume2/docker/dmarc-stack/...`), weil Portainer CE relative Pfade in
> Git-Stacks nicht unterstützt. Liegt dein Ordner woanders, `CONFIG_DIR`
> als Environment-Variable entsprechend setzen.

Alternativ ohne Git-Anbindung: Build method **Web editor** und den Inhalt von
`docker-compose.yml` einfügen — Rest identisch.

> Der Stack setzt eine **Standalone-Docker-Umgebung** in Portainer voraus
> (kein Swarm) — auf Synology mit Container Manager ist das der Standardfall.
> Im Swarm-Modus würden `depends_on`-Healthcheck-Bedingungen ignoriert.

## Schritt 5 — Erster Start

* Elasticsearch braucht am NAS 1–3 Minuten bis `healthy`; parsedmarc und
  Grafana starten erst danach (`depends_on` + Healthcheck).
* Grafana: `http://<NAS-IP>:3002` (Port via `GRAFANA_PORT` änderbar), Login `admin` / dein Passwort.
  Das Dashboard **DMARC Reports** ist als Startseite hinterlegt (Ordner
  „DMARC"). Datasources `dmarc-aggregate` und `dmarc-forensic` sind fertig
  provisioniert.
* Logs prüfen: Portainer → Containers → `dmarc-stack-parsedmarc-1` → Logs.

---

# Der Erstimport (~4000 Mails)

Der erste Lauf arbeitet das komplette Postfach ab. Was dich erwartet:

* **Dauer:** Rechne mit mehreren Stunden. Pro Report macht parsedmarc
  DNS-Lookups (Reverse DNS der meldenden IPs); das dominiert die Laufzeit.
  Die Verarbeitung läuft in Batches à 500 Mails (`batch_size`), nach jedem
  Batch wird in Elasticsearch gespeichert und die Mails wandern nach `Archive`.
* **Fortschritt beobachten:**
  ```sh
  sudo docker logs -f dmarc-stack-parsedmarc-1
  ```
  Alternativ: im Dashboard zusehen, wie die Zahlen wachsen (Zeitraum oben
  rechts auf „Last 1 year" o.ä. stellen!).
* **Abbruch ist unkritisch.** Schon verarbeitete Mails liegen im
  `Archive`-Ordner, der Rest in `INBOX` — nach einem Neustart macht parsedmarc
  dort weiter. Doppelt verarbeitete Reports erkennt parsedmarc am Report-Hash
  und überspringt sie („already exists in Elasticsearch").
* **RAM im Blick behalten:** DSM → Ressourcenmonitor. Wird es eng
  (Swapping), in der `parsedmarc.ini` zusätzlich
  `strip_attachment_payloads = True` setzen und/oder `batch_size = 100`,
  dann Container neu starten.
* **Nach dem Import** bleibt der Container im Watch-Modus und verarbeitet
  neue Reports, sobald sie eintreffen. Nichts weiter zu tun.

---

# Betrieb

* **Updates:** Versionen sind bewusst gepinnt. Update = Tag im Compose-File
  ändern (Commit ins Repo), dann Portainer → Stack → „Pull and redeploy"
  (bzw. automatisch via GitOps-Polling). Elasticsearch nur innerhalb der
  8.x-Linie aktualisieren, bevor Dashboards/Datasource getestet sind.
* **Backup:** Alles liegt unter `/volume2/docker/dmarc-stack` — den einen
  Ordner mit Hyper Backup o.ä. sichern, fertig. Die Rohdaten bleiben ohnehin
  im IMAP-Archive-Ordner erhalten und können jederzeit neu eingelesen werden.
* **Elasticsearch ist bewusst ohne Authentifizierung** (`xpack.security.enabled=false`),
  aber nur im internen Docker-Netz erreichbar — Port 9200 ist nicht
  veröffentlicht. Nicht ändern, ohne Security zu aktivieren.

# Troubleshooting

| Symptom | Ursache / Lösung |
|---|---|
| Elasticsearch-Container stirbt sofort, Exit-Code 78, Log: `max virtual memory areas vm.max_map_count [65530] is too low` | Schritt 1 vergessen oder Aufgabe nach Neustart nicht gelaufen. `sudo sysctl -w vm.max_map_count=262144`, Boot-Aufgabe prüfen. |
| parsedmarc: `Permission denied: '/parsedmarc.ini'` | `chmod 644` auf die Datei (Container läuft als uid 1000). |
| Elasticsearch: `AccessDeniedException` auf `/usr/share/elasticsearch/data` oder Grafana: `GF_PATHS_DATA='/var/lib/grafana' is not writable` | `chown` aus Schritt 2 vergessen: `data/elasticsearch` → uid 1000, `data/grafana` → uid 472. |
| parsedmarc: `%`-Fehler beim Start (InterpolationSyntaxError) | `%` im IMAP-Passwort muss in der ini als `%%` geschrieben werden. |
| Grafana-Panels zeigen „Datasource not found" | Datasource-UIDs (`dmarc_es_ag`/`dmarc_es_fo`) in `datasource.yml` wurden verändert — Original wiederherstellen. |
| Dashboard leer, keine Fehler | Zeitbereich oben rechts vergrößern (Reports liegen in der Vergangenheit). Prüfen: `curl http://localhost:9200/_cat/indices` (per SSH, aus einem Container im dmarc-Netz) — existieren `dmarc_aggregate-YYYY-MM-DD`- bzw. `dmarc_failure-YYYY-MM-DD`-Indizes? |
| NAS wird träge / OOM während des Imports | `ES_HEAP`/`ES_MEM_LIMIT` senken (bei 4 GB RAM: 1g/2g); `batch_size` senken; `strip_attachment_payloads = True`. |
| Import bricht ab, Log: `this action would add [2] shards, but this cluster currently has [...] maximum normal shards open` | Shard-Limit erreicht — `cluster.max_shards_per_node` in der Compose-Datei erhöhen (Default hier bereits 4000). |
| Portainer-Git-Stack: `bind source path does not exist` | `CONFIG_DIR` zeigt auf einen nicht existierenden Pfad, oder Schritt 2 fehlt. Relative Pfade funktionieren in Portainer CE nicht. |

# Credits

* [domainaware/parsedmarc](https://github.com/domainaware/parsedmarc) — Parser & Docker-Image (Apache 2.0)
* [LukeCallaghan/dmarc-visualizer](https://github.com/LukeCallaghan/dmarc-visualizer) und
  [debricked/dmarc-visualizer](https://github.com/debricked/dmarc-visualizer) — Grafana-Dashboard & ursprüngliche Stack-Idee (Apache 2.0)
