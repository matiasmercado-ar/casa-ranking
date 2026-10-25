# Casa Ranking

A small self-hosted web app to **rank houses you are thinking of buying**. Paste the
listing link, each person rates it from 0 to 10 on a few topics, tick what is nearby,
and the app keeps a live ranking.

The UI is in **Spanish by default** with an English toggle (top right). Built for a
couple deciding together, but any number of people can rate.

![Ranking](docs/ranking.png)

## Features

- **Per-person star ratings (0-10)** for *Ubicación* (location), *Construcción*
  (construction) and *Antigüedad* (age). Each person rates on their own; the ranking
  uses the average, and unrated topics are ignored rather than counted as zero.
- **Yes / No / unknown checks**: *¿Mejorable?* (room to improve), supermarket, school,
  public transport, gym, bike lane, park, hospital/clinic nearby.
- **Weighted score**: give each topic a weight in Settings (e.g. location counts double).
- **Statuses**: active, visited, favourite, discarded (discarded ones are hidden from the ranking).
- **Link preview**: when you add a link, it tries to read the title and photo from the
  page's Open Graph tags. Many portals block bots, so you can always type them by hand.
- **Compare view**: every house and every criterion in one table.
- **Export** to CSV (opens in Excel / Sheets) or JSON.
- **Autosave**: ratings save as you click, no submit button.
- Mobile friendly (you will use it standing inside the house), dark mode, optional shared password.

![House detail](docs/house.png)

## Run it

### Docker (any machine, amd64 or arm64)

```bash
docker run -d --name casa-ranking -p 8000:8000 -v casa-data:/data \
  -e RATERS="Ana,Beto" ghcr.io/matiasmercado-ar/casa-ranking:latest
```

Open http://localhost:8000.

### Docker Compose (from source)

```bash
git clone https://github.com/matiasmercado-ar/casa-ranking.git
cd casa-ranking
cp .env.example .env     # optional: names, password, port
docker compose up -d --build
```

Data lives in `./data/casa-ranking.db` (SQLite). Back it up by copying that folder or
with *Ajustes > Exportar datos*.

### Without Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

### Proxmox LXC

`deploy/` has two scripts that create a Debian 13 LXC with Docker on a Proxmox node and
deploy the app into it over SSH:

```bash
cp deploy/deploy.env.example deploy/deploy.env   # set node, CT ID, IP, storage
deploy/proxmox-lxc.sh                            # once: creates the container
deploy/deploy.sh                                 # every update: sync, rebuild, health check
```

## Configuration

| Variable       | Default                 | Meaning |
|----------------|-------------------------|---------|
| `RATERS`       | `Persona 1,Persona 2`   | People who rate. Only used when the DB is created; rename them later in Settings. |
| `APP_PASSWORD` | *(empty)*               | Shared password. Empty = no login (fine on a home LAN, not on the internet). |
| `SECRET_KEY`   | *(generated)*           | Session signing key; auto-generated into `data/secret.key` if unset. |
| `DATA_DIR`     | `/data` in the image    | Where the SQLite DB lives. |
| `PORT`         | `8000`                  | Host port used by `docker-compose.yml`. |

## How the score works

For each topic the app averages the ratings of everyone who rated it. The house score
is the weighted average of those topic averages (weights default to 1). Houses are
sorted by score, ties broken by how many amenities are nearby; unrated houses go last.
*¿Mejorable?* is shown but not counted as an amenity, since whether it is good news
depends on you.

## Stack

FastAPI, Jinja2 templates, SQLite, and a few lines of vanilla JS. No frontend build
step, no external services: a single ~160 MB container. Tests: `pip install -r
requirements-dev.txt && pytest`.

## About

A weekend "vibe coding" project: designed and built in a conversation with an AI
coding assistant, then deployed to a home Proxmox server. MIT licensed.

---

### En español

App para **puntuar y rankear casas** que estás pensando comprar. Pegás el link de la
publicación, cada persona puntúa de 0 a 10 *Ubicación*, *Construcción* y *Antigüedad*,
marcás qué hay cerca (súper, colegio, transporte, gimnasio, ciclovía, plaza, salud) y
la app arma el ranking. Se levanta con `docker compose up -d --build` y se usa en
http://localhost:8000.
