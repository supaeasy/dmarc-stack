# dmarc-stack

🇬🇧 English | 🇩🇪 [Deutsch](README.de.md)

Fetch DMARC reports from an IMAP mailbox, parse them, and visualize them in
Grafana — as a Docker stack built for **Synology DSM 7.2+ with Portainer**.

Merged from [LukeCallaghan/dmarc-visualizer](https://github.com/LukeCallaghan/dmarc-visualizer)
(Grafana dashboard + stack idea) and [domainaware/parsedmarc](https://github.com/domainaware/parsedmarc)
(parser, official Docker image). License: Apache 2.0, same as both upstream projects.

| Component | Image | Version |
|---|---|---|
| parsedmarc | `ghcr.io/domainaware/parsedmarc` | 10.2.2 |
| Elasticsearch | `docker.elastic.co/elasticsearch/elasticsearch` | 8.14.3 (last version that starts on Synology kernels without seccomp — see troubleshooting) |
| Grafana OSS | `grafana/grafana` | 12.4.5 |

## Design decisions

* **No custom image builds.** Older DMARC stacks built parsedmarc and a
  customized Grafana via Dockerfiles — exactly those builds are known to fail
  on Synology Container Manager
  ([dmarc-visualizer#1](https://github.com/LukeCallaghan/dmarc-visualizer/issues/1)).
  This stack runs unmodified stock images only; the dashboard and datasources
  are injected via Grafana provisioning (bind mounts).
* **Official parsedmarc image** instead of a pip install in Alpine. Current
  parsedmarc version, multi-arch, maintained upstream. Side effect: no
  MaxMind/GeoIP setup needed — parsedmarc 10.x ships its own IP database and
  keeps it updated.
* **Elasticsearch pinned to 8.14.3.** Synology's DSM kernel (4.4) lacks
  `CONFIG_SECCOMP`; starting with ES 8.15 the missing seccomp sandbox is a
  fatal boot error. Do not raise this pin while running on Synology.
* **Docker DNS instead of fixed container IPs** (`elasticsearch:9200`).
* **Everything in one folder:** configuration AND data live as bind mounts
  under a single directory (default `/volume2/docker/dmarc-stack`) — nothing
  hides in Docker volumes. This requires a one-time `chown` of the data
  directories (Elasticsearch runs as uid 1000, Grafana as uid 472 — see
  step 2).
* **Daily Elasticsearch indices** (parsedmarc default). So that years of
  report history don't hit the shard limit, `cluster.max_shards_per_node=4000`
  is set (default would be 1000).

## Architecture

```
IMAP mailbox  ──► parsedmarc ──► Elasticsearch ──► Grafana (port 3002)
(DMARC reports)   (watch mode)   (bind mount)      ("DMARC Reports" dashboard)
```

parsedmarc runs permanently in watch mode: on startup it processes all mail in
the `reports_folder`, moves it to `Archive`, and then waits for new reports
via IMAP IDLE.

---

# Installation on a Synology NAS

## Step 0 — Prerequisites

* DSM 7.2+, Container Manager installed, Portainer CE running (standalone
  Docker environment, not Swarm — the default on Synology)
* SSH access enabled (Control Panel → Terminal & SNMP → SSH)
* **RAM:** the defaults (`ES_HEAP=2g`, `ES_MEM_LIMIT=4g`) fit a NAS with
  16 GB+ RAM. On a 4 GB model reduce to `ES_HEAP=1g` / `ES_MEM_LIMIT=2g`.
* An IMAP mailbox receiving the DMARC reports, with credentials.

## Step 1 — Check vm.max_map_count (set only if needed)

Elasticsearch refuses to start (exit code 78) if the kernel parameter
`vm.max_map_count` is below 262144. **Check first** — many DSM installations
already ship with 262144:

```sh
sysctl vm.max_map_count
```

If the value is ≥ 262144: skip this step entirely. If it is lower (typically
65530), register it as a boot task so it survives every reboot and DSM update:

1. **Control Panel → Task Scheduler → Create → Triggered Task →
   User-defined script**
2. General: name `es-max-map-count`, user **root**, event **Boot-up**
3. Task settings → user-defined script:
   ```sh
   sysctl -w vm.max_map_count=262144
   ```
4. Save, then run the task once manually (right-click → Run) so the value
   applies immediately — no reboot needed.

> Editing `/etc/sysctl.conf` directly also works, but DSM updates tend to
> overwrite it. The Task Scheduler route survives updates.

## Step 2 — Create the config folder on the NAS

Via SSH (user with admin rights):

```sh
sudo mkdir -p /volume2/docker/dmarc-stack
cd /volume2/docker/dmarc-stack
sudo git clone https://github.com/supaeasy/dmarc-stack.git .

# Create the data directories and hand them to the container users
# (Elasticsearch runs as uid 1000, Grafana as uid 472):
sudo mkdir -p data/elasticsearch data/grafana
sudo chown -R 1000:0 data/elasticsearch
sudo chown -R 472:0 data/grafana
```

If `git` is missing on the NAS (install Git Server from the Package Center,
or): download the repo as a ZIP from GitHub and upload the contents to
`/volume2/docker/dmarc-stack` via File Station — the `mkdir`/`chown` commands
above are still required via SSH. The result must look like this:

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

## Step 3 — Create parsedmarc.ini

```sh
cd /volume2/docker/dmarc-stack/parsedmarc
sudo cp parsedmarc.ini.example parsedmarc.ini
sudo vim parsedmarc.ini        # or nano / the File Station editor
sudo chmod 644 parsedmarc.ini  # the container user (uid 1000) must be able to read it
```

Fill in: IMAP `host`, `user`, `password`. The rest is preconfigured (watch
mode, batching, daily indices). The file stays on the NAS only — it is listed
in `.gitignore` and must never end up in the repo.

**Mailbox note:** processed mail is moved to the IMAP folder `Archive`
(never deleted). If your mail server doesn't create folders automatically,
create it beforehand.

## Step 4 — Create the stack in Portainer

1. Portainer → **Stacks → Add stack**
2. Name: `dmarc-stack`
3. Build method: **Repository**
   * Repository URL: `https://github.com/supaeasy/dmarc-stack`
   * Repository reference: `refs/heads/main`
   * Compose path: `docker-compose.yml`
   * Optional: enable **GitOps updates / polling** so Portainer picks up
     compose changes from the repo automatically.
4. Add **environment variables** (see `.env.example`):
   * `GRAFANA_ADMIN_PASSWORD` = *a real password*
   * optional: `ES_HEAP`, `ES_MEM_LIMIT`, `GRAFANA_PORT`, `CONFIG_DIR`
5. **Deploy the stack**

> Important: the bind mounts in the compose file deliberately use **absolute
> paths** (`/volume2/docker/dmarc-stack/...`) because Portainer CE does not
> support relative paths in Git stacks. If your folder lives elsewhere, set
> `CONFIG_DIR` accordingly.

Alternative without the Git connection: build method **Web editor**, paste the
contents of `docker-compose.yml` — everything else is identical.

## Step 5 — First start

* Elasticsearch takes 1–3 minutes to report `healthy` on a NAS; parsedmarc
  and Grafana start only afterwards (`depends_on` + healthcheck).
* Grafana: `http://<NAS-IP>:3002` (port configurable via `GRAFANA_PORT`),
  login `admin` / your password. The **DMARC Reports** dashboard is the
  default home dashboard (folder "DMARC"). The datasources
  `dmarc-aggregate` and `dmarc-forensic` are provisioned automatically.
* Check the logs: Portainer → Containers → `dmarc-stack-parsedmarc-1` → Logs.

---

# Importing an existing mailbox

The first run processes the entire `reports_folder`. What to expect:

* **Duration:** for mailboxes with thousands of reports, plan for hours. Per
  report parsedmarc performs DNS lookups (reverse DNS of the reporting IPs);
  that dominates the runtime. Processing happens in batches (`batch_size`);
  after each batch, results are saved and the mail is moved to `Archive`.
* **Watch progress:**
  ```sh
  sudo docker logs -f dmarc-stack-parsedmarc-1
  ```
  Or watch the dashboard numbers grow (set the time range in the top right
  to something like "Last 1 year"!).
* **Interruptions are harmless.** Already-processed mail sits in `Archive`,
  the rest in the `reports_folder` — after a restart parsedmarc continues
  there. Duplicates are detected and skipped.
* **Watch memory usage:** DSM → Resource Monitor. If things get tight,
  set `strip_attachment_payloads = True` and/or lower `batch_size` in
  `parsedmarc.ini`, then restart the container.
* **After the import** the container stays in watch mode and processes new
  reports as they arrive. Nothing else to do.

---

# Operation

* **Updates:** versions are pinned on purpose. Update = change the tag in the
  compose file (commit to the repo), then Portainer → stack → "Pull and
  redeploy" (or automatically via GitOps polling). **Elasticsearch stays
  pinned to 8.14.3** — newer versions do not start on Synology kernels
  (seccomp, see troubleshooting).
* **Backup:** everything lives under `/volume2/docker/dmarc-stack` — back up
  that one folder with Hyper Backup or similar. The raw reports remain in the
  IMAP archive folder anyway and can be re-imported at any time.
* **Elasticsearch deliberately runs without authentication**
  (`xpack.security.enabled=false`) but is only reachable inside the internal
  Docker network — port 9200 is not published. Don't change this without
  enabling security.

# Special case: failure reports without an ARF part

Some gateways (e.g. Exim/cPanel-based ones) send DMARC failure/forensic
reports without the machine-readable `message/feedback-report` part.
parsedmarc parses them via a plain-text fallback, but its Elasticsearch
export then drops them with
`Failure report missing required field: 'feedback_type'`
([parsedmarc#332](https://github.com/domainaware/parsedmarc/issues/332)).

This stack therefore prepends
[parsedmarc/patch_feedback_type.py](parsedmarc/patch_feedback_type.py) as an
entrypoint wrapper: it fills in the missing fields
(`feedback_type = auth-failure`, empty `authentication_results`) so these
reports still reach the dashboard. For standards-compliant reports the patch
changes nothing. A proper fix has been submitted upstream
([parsedmarc#831](https://github.com/domainaware/parsedmarc/pull/831)); once
it is released, the wrapper can be removed.

To re-import reports that were previously archived but never indexed: move
the mail from `Archive/Failure` (or `Archive/Invalid`) back into the inbox —
watch mode processes it again, and parsedmarc detects duplicates itself.

# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Elasticsearch container dies immediately, exit code 78, log: `max virtual memory areas vm.max_map_count [65530] is too low` | Step 1 skipped or the boot task didn't run. `sudo sysctl -w vm.max_map_count=262144`, check the boot task. |
| Elasticsearch dies with exit code 1, log: `seccomp unavailable: CONFIG_SECCOMP not compiled into kernel` | Elasticsearch ≥ 8.15 on Synology — the DSM kernel (4.4) has no seccomp; from 8.15 on this is fatal. Keep the image pinned to 8.14.3; no DSM-side fix exists. |
| parsedmarc: `Permission denied: '/parsedmarc.ini'` | `chmod 644` the file (the container runs as uid 1000). |
| Elasticsearch: `AccessDeniedException` on `/usr/share/elasticsearch/data`, or Grafana: `GF_PATHS_DATA='/var/lib/grafana' is not writable` | The `chown` from step 2 is missing: `data/elasticsearch` → uid 1000, `data/grafana` → uid 472. |
| parsedmarc: `%` error on startup (InterpolationSyntaxError) | A `%` in the IMAP password must be written as `%%` in the ini file. |
| Grafana panels show "Datasource not found" | The datasource UIDs (`dmarc_es_ag`/`dmarc_es_fo`) in `datasource.yml` were changed — restore the originals. |
| Dashboard empty, no errors | Widen the time range in the top right (reports lie in the past). Check: `curl http://localhost:9200/_cat/indices` (via SSH, from a container in the dmarc network) — do `dmarc_aggregate-YYYY-MM-DD` / `dmarc_failure-YYYY-MM-DD` indices exist? |
| NAS becomes sluggish / OOM during import | Lower `ES_HEAP`/`ES_MEM_LIMIT` (on 4 GB RAM: 1g/2g); lower `batch_size`; set `strip_attachment_payloads = True`. |
| Import aborts, log: `this action would add [2] shards, but this cluster currently has [...] maximum normal shards open` | Shard limit reached — raise `cluster.max_shards_per_node` in the compose file (already 4000 here). |
| Portainer Git stack: `bind source path does not exist` | `CONFIG_DIR` points to a non-existent path, or step 2 is missing. Relative paths do not work in Portainer CE. |

# Credits

* [domainaware/parsedmarc](https://github.com/domainaware/parsedmarc) — parser & Docker image (Apache 2.0)
* [LukeCallaghan/dmarc-visualizer](https://github.com/LukeCallaghan/dmarc-visualizer) and
  [debricked/dmarc-visualizer](https://github.com/debricked/dmarc-visualizer) — Grafana dashboard & original stack idea (Apache 2.0)
