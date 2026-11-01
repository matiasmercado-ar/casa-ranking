# Casa Ranking

A small self-hosted web app to **rank houses you are thinking of buying**. Paste the
listing link, each person rates it from 0 to 10 on a few topics, tick what is nearby,
and the app keeps a live ranking, with where you are with each house (contacted the
seller? visit booked? visited?) right next to its position.

The UI is in **Spanish by default** with an English toggle. Built for a couple deciding
together, but any number of people can rate.

![Ranking](docs/ranking.png)

## Features

- **Accounts**: everyone logs in. An admin account is created on first start; the admin
  adds users (name, email, password) and decides who rates.
- **Per-person star ratings (0-10)** for *Ubicación* (location), *Vecindario*
  (neighbourhood), *Construcción* (construction), *Antigüedad* (age), *Mejorable* (how much
  better it could be made) and *¿Me gusta?* (do I like it). Each person can
  only change their own stars (enforced server side); everyone else's are shown
  read-only, and every card shows each person's own score. A "Te falta puntuar" tag
  shows which houses you still have to rate.
- **A score that means something** (0-10): each person's stars as a weighted average
  (*Ubicación* counts double by default, *Mejorable* and *¿Me gusta?* a little less than
  the rest, an unrated topic counts as 5), then everyone's
  opinions together, halfway between the average and the lowest one, so a house only
  ranks high when all of you like it. The Yes/No questions are 15% of the score. Only 10
  stars on everything from everyone plus Yes to every question gives 10.0.
- **One state per house**, in the order things happen: *No visitada* → **Ir a visitar**
  (*Sin contactar* → *Contactada* → *Visita agendada*) → *Visitada*. Each ranking row
  starts with a coloured strip showing the position and the state together, with a
  three-dot progress for the "ir a visitar" steps. The state changes from a
  *Cambiar estado* menu on the row and on the house page.
- **The calendar keeps the state honest**: booking a visit makes the house *Visita
  agendada*; moving or deleting its only visit takes it back to *Contactada*; once the day
  has passed it asks *¿Fueron?* until you mark it visited.
- **Tabs per state** with counts (the three "ir a visitar" steps grouped together).
- **Filters**: minimum score, minimum stars per topic, must-have features, price range,
  "only the ones I still have to rate". Active filters show as chips you can remove one
  by one, and the tabs and filters stay at the top while you scroll.
- **Calendar** of visits in Argentina time (UTC-3): a month view, the day's visits and the
  upcoming ones. Each visit links to the house in the app and has notes (who you meet, what
  to ask). The booked day also shows on the house page and its ranking row.
- **Comments** on every house with their author, marked *Online* (looking at the
  listing) or *En persona* (after a visit), with a tab for each.
- **Yes / No / "No sé" questions** that count towards the score: about the house (pet friendly, pool or room for one, room for an above-ground pool) and what's nearby
  (supermarket, school, public transport, gym, bike lane, park, hospital/clinic).
- **Tunable**: topic weights, question importance and how much the questions count, in Settings.
- **Activa / Favorita / Descartada** at the top of each house page (discarded ones are
  hidden from the ranking).
- **Paste a link, get the house**: photo, price, currency, address, map coordinates and
  key facts (bedrooms, bathrooms, m², age) are read from the listing for **Inmoup,
  Inmoclick, MercadoLibre and Remax** (Argentina), each from its own structured data
  (JSON-LD, embedded page state). Other sites get a best-effort Open Graph read. Pasting
  a link that's already there takes you to that house; "Actualizar desde el link"
  re-reads it and tells you if the price changed.
- **Compare view**: every house and every criterion in one table, with its state.
- **Export** to CSV (opens in Excel / Sheets) or JSON.
- **Autosave**: ratings save as you click, no submit button.
- **Phone, tablet and desktop layouts**: bottom tab bar on phones (you will use it
  standing inside the house), light / dark / automatic theme toggle. The ranking keeps
  one house per row; the features of each house (pool, school nearby...) are on its page.

![House detail](docs/house.png)

<p align="center"><img src="docs/mobile.png" width="300" alt="Phone layout"> <img src="docs/dark.png" width="520" alt="Ir a visitar tab, dark mode"></p>

![Calendar](docs/calendar.png)

The screenshots use made-up houses and people, with drawings instead of listing photos.

## Run it

### Docker (any machine, amd64 or arm64)

```bash
docker run -d --name casa-ranking -p 8000:8000 -v casa-data:/data \
  -e ADMIN_PASSWORD='choose-a-password' ghcr.io/matiasmercado-ar/casa-ranking:latest
```

Open http://localhost:8000, log in as `admin`, and add the people who will rate in
*Ajustes*. Without `ADMIN_PASSWORD` a random one is printed once in `docker logs casa-ranking`.

### Docker Compose (from source)

```bash
git clone https://github.com/matiasmercado-ar/casa-ranking.git
cd casa-ranking
cp .env.example .env     # optional: admin password, port
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

| Variable         | Default               | Meaning |
|------------------|-----------------------|---------|
| `ADMIN_EMAIL`    | `admin`               | Login of the admin account created on first start. |
| `ADMIN_PASSWORD` | *(generated, logged)* | Its password. Only read when no admin exists; change it later in Settings. |
| `SECRET_KEY`     | *(generated)*         | Session signing key; auto-generated into `data/secret.key` if unset. |
| `DATA_DIR`       | `/data` in the image  | Where the SQLite DB lives. |
| `PORT`           | `8000`                | Host port used by `docker-compose.yml`. |

Lost the admin password? Set a new one from the host:

```bash
docker compose exec casa-ranking python -c "from app import db; c=db.connect(); \
  c.execute(\"UPDATE users SET password_hash=? WHERE email='admin'\", (db.hash_password('new-password'),)); c.commit()"
```

## How the score works

1. **Each person's stars**: a weighted average of their topics. By default *Ubicación*
   counts double and *Mejorable* and *¿Me gusta?* 0.75; the rest count 1. A topic someone
   hasn't rated yet counts as a neutral 5, so a half-rated house can't look perfect.
2. **Everyone together**: halfway between the average of those personal scores and the
   lowest one, so a house only ranks high when all of you like it.
3. **Questions**: the importance-weighted share of Yes answers (*No sé* counts half, No
   zero), worth 15% of the final score by default (up to 50%, in Settings). The admin sets
   each question's importance to 2 (very important), 1 (normal) or 0 (ignored).

Only 10 stars on every topic from everyone plus Yes to every question gives 10.0. Unrated
houses go last.

## Stack

FastAPI, Jinja2 templates, SQLite, httpx for reading listings, and a few lines of vanilla JS. No frontend build
step, no external services: a single ~160 MB container. Tests: `pip install -r
requirements-dev.txt && pytest`.

## About

A weekend "vibe coding" project: designed and built in a conversation with an AI
coding assistant, then deployed to a home Proxmox server. MIT licensed.

---

### En español

App para **puntuar y rankear casas** que estás pensando comprar. Pegás el link de la
publicación, cada persona (con su propio usuario) puntúa de 0 a 10 *Ubicación*,
*Vecindario*, *Construcción*, *Antigüedad*, *Mejorable* y *¿Me gusta?*,
marcás qué hay cerca (súper, colegio, transporte, gimnasio, ciclovía, plaza, salud) y
la app arma el ranking. Cada casa tiene un estado (*No visitada*, *Ir a visitar*: *Sin
contactar*, *Contactada*, *Visita agendada*, y *Visitada*) que se ve junto a su posición
y se cambia desde el menú *Cambiar estado*; el calendario de visitas lo mantiene al día. Se levanta con `docker compose up -d --build` y se usa en
http://localhost:8000.
