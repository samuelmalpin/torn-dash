# Torn Nexus Bot

Bot Torn + dashboard web futuriste, prêt pour un déploiement personnel sur Docker.

## Fonctionnalités

- Polling automatique de l'API Torn (profil, bars, money, points, events)
- Auth dashboard (login + rôles admin/viewer)
- Moteur d'alertes multi-canaux (Discord, Telegram, email)
- Anti-spam d'alertes via cooldown configurable
- Dashboard web en temps réel (look cyber/futuriste + trends + insights)
- Mode War Room faction (activité live, chain timer, membres critiques)
- Moteur d'actions automatiques modulaire (V1): `refresh_user`, `refresh_faction`, `attack` (placeholder), `buy` (placeholder)
- Règles d'automatisation: horaires autorisés, priorités, cooldown par module, seuils (énergie/money)
- Garde-fous: `dry-run`, limite d'actions/heure, arrêt d'urgence
- Widgets drag & drop + sauvegarde layout locale
- Persistance SQLite locale

## Prérequis

- Docker + Docker Compose
- Clé API Torn valide

## Démarrage rapide

1. Copier le fichier d'environnement :

```bash
cp .env.example .env
```

2. Remplir les variables dans `.env` (au minimum `TORN_API_KEY`).
	Pour sécuriser l'accès internet, configure impérativement:
	- `DASHBOARD_USERS`
	- `AUTH_SECRET` (ou laisse vide/par défaut pour génération auto persistée)

3. Lancer le service :

```bash
docker compose up -d --build
```

4. Ouvrir le dashboard :

```text
http://localhost:12000
```

## Déploiement Debian 13 (personnel)

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker

git clone <ton-repo>
cd <ton-repo>
cp .env.example .env
# édite .env
docker compose up -d --build
```

## Variables principales

- `TORN_API_KEY`: clé API Torn
- `TORN_API_BASE`: base URL API Torn (défaut recommandé: `https://api.torn.com/v2`)
- `TORN_MIN_REQUEST_INTERVAL_SECONDS`: délai minimal global entre 2 requêtes Torn (toutes routes)
- `TORN_RATE_LIMIT_RETRY_COUNT`: nombre de retries automatiques sur rate-limit Torn (code 5 / HTTP 429)
- `TORN_RATE_LIMIT_BACKOFF_SECONDS`: base du délai de backoff progressif sur rate-limit
- `POLL_INTERVAL_SECONDS`: fréquence de polling user/events
- `DISCORD_WEBHOOK_URL`: webhook Discord pour alertes
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: canal Telegram
- `SMTP_*` + `EMAIL_FROM`/`EMAIL_TO`: alertes email
- `ALERT_CHANNEL_RULES`: routage par type d'alerte
- `ALERT_COOLDOWN_SECONDS`: délai minimum entre 2 alertes identiques
- `DASHBOARD_HISTORY_POINTS`: profondeur des courbes sur le dashboard
- `DASHBOARD_USERS`: utilisateurs `username:password:role`
- `AUTH_SECRET`: secret de signature de session (**32+ caractères**). Si vide/par défaut/trop court, le bot en génère un automatiquement.
- `AUTH_SECRET_FILE`: chemin du fichier de persistance du secret auto-généré (défaut: `./data/.auth_secret`)
- `AUTOMATION_ENABLED`: active le scheduler d'actions automatiques (0/1)
- `AUTOMATION_DRY_RUN`: simule les actions sans exécution réelle (recommandé: 1)
- `AUTOMATION_TICK_SECONDS`: fréquence de passage du scheduler
- `AUTOMATION_MAX_ACTIONS_PER_HOUR`: limite globale d'actions automatiques par heure
- `AUTOMATION_ALLOWED_HOURS`: heures autorisées (ex: `8-23` ou `8-12,14-22`)
- `AUTOMATION_REFRESH_USER_COOLDOWN_SECONDS`: cooldown du module refresh user
- `AUTOMATION_REFRESH_FACTION_COOLDOWN_SECONDS`: cooldown du module refresh faction
- `AUTOMATION_ATTACK_COOLDOWN_SECONDS`: cooldown du module attack (placeholder)
- `AUTOMATION_BUY_COOLDOWN_SECONDS`: cooldown du module buy (placeholder)
- `AUTOMATION_ATTACK_MIN_ENERGY`: seuil d'énergie minimal pour module attack
- `AUTOMATION_BUY_MIN_MONEY`: seuil de money minimal pour module buy
- `AUTOMATION_EMERGENCY_STOP`: arrêt d'urgence au boot (0/1)
- `FACTION_ID`: active le mode War Room si > 0

## Auth & rôles

- Login web via `/login`
- Rôle `viewer`: accès dashboard + APIs de lecture
- Rôle `admin`: accès supplémentaire à l'endpoint de backtesting

## Alertes par canal

Le routage est piloté par `ALERT_CHANNEL_RULES`.

Exemple:

```text
price_drop:discord|telegram;energy:discord;error:discord|email;war_room:discord|telegram
```

Canaux supportés: `discord`, `telegram`, `email`.

## Architecture

- `app/main.py`: API FastAPI + routes dashboard
- `app/services.py`: orchestration polling + alerting
- `app/auth.py`: authentification + rôles (session signée)
- `app/torn_client.py`: appels API Torn
- `app/storage.py`: SQLite (snapshots, prix, alertes, événements)
- `app/static/*`: dashboard web (HTML/CSS/JS)

## API automation (V1)

- `GET /api/automation/status`: état du scheduler, règles actives, compteurs, dry-run
- `GET /api/automation/logs?limit=80`: logs d'actions automatiques
- `POST /api/automation/start` (admin): démarre le scheduler
- `POST /api/automation/stop` (admin): stoppe le scheduler
- `POST /api/automation/emergency-stop` (admin): active/désactive l'arrêt d'urgence

Exemple payload arrêt d'urgence:

```json
{"enabled": true}
```
