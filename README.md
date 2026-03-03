# Torn Nexus Bot

Bot Torn + dashboard web futuriste, prêt pour un déploiement personnel sur Docker.

## Fonctionnalités

- Polling automatique de l'API Torn (profil, bars, money, points, events)
- Suivi marché pour une liste d'items configurable
- Auth dashboard (login + rôles admin/viewer)
- Moteur d'alertes multi-canaux (Discord, Telegram, email)
- Anti-spam d'alertes via cooldown configurable
- Stratégie de BUY signal à seuil dynamique (volatilité + moyenne mobile)
- Plan de trading assisté par budget (simulation d'allocation, non exécutable)
- Backtesting sur historique (réservé admin)
- Auto-discovery optionnel des items (scan pool d'IDs, scoring liquidité/volatilité/spread)
- Dashboard web en temps réel (look cyber/futuriste + trends + insights)
- Graphiques avancés (candles, moyenne mobile, volatilité, heatmap)
- Mode War Room faction (activité live, chain timer, membres critiques)
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
- `MARKET_POLL_INTERVAL_SECONDS`: fréquence de polling marché
- `MARKET_MAX_ITEMS_PER_CYCLE`: nombre max d'items market scannés par cycle (scan tournant)
- `MARKET_REQUEST_SPACING_SECONDS`: délai entre 2 appels market pour lisser la charge API
- `TRACKED_ITEM_IDS`: IDs d'items Torn séparés par virgule
- `AUTO_DISCOVERY_ENABLED`: active la sélection automatique des meilleurs items (0/1)
- `AUTO_DISCOVERY_POOL_IDS`: pool d'IDs à scanner (si vide, fallback sur `TRACKED_ITEM_IDS`)
- `AUTO_DISCOVERY_TOP_N`: nombre d'items retenus automatiquement
- `AUTO_DISCOVERY_STATS_WINDOW`: taille d'historique pour le scoring auto-discovery
- `DISCORD_WEBHOOK_URL`: webhook Discord pour alertes
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: canal Telegram
- `SMTP_*` + `EMAIL_FROM`/`EMAIL_TO`: alertes email
- `ALERT_CHANNEL_RULES`: routage par type d'alerte
- `PRICE_DROP_ALERT_PERCENT`: seuil d'alerte baisse de prix
- `ALERT_COOLDOWN_SECONDS`: délai minimum entre 2 alertes identiques
- `DASHBOARD_HISTORY_POINTS`: profondeur des courbes sur le dashboard
- `DASHBOARD_USERS`: utilisateurs `username:password:role`
- `AUTH_SECRET`: secret de signature de session (**32+ caractères**). Si vide/par défaut/trop court, le bot en génère un automatiquement.
- `AUTH_SECRET_FILE`: chemin du fichier de persistance du secret auto-généré (défaut: `./data/.auth_secret`)
- `STRATEGY_*`: paramètres stratégie dynamique
- `BACKTEST_*`: paramètres de validation historique
- `TRADING_BUDGET_DEFAULT`: budget par défaut pour le plan de trading simulé
- `TRADING_MAX_POSITIONS`: nombre max de positions dans le plan simulé
- `FACTION_ID`: active le mode War Room si > 0

## Auto-discovery (fallback manuel)

- Si `AUTO_DISCOVERY_ENABLED=1`, le bot scanne le pool d'IDs (`AUTO_DISCOVERY_POOL_IDS`) et retient dynamiquement les meilleurs.
- Le dashboard et les endpoints de signaux utilisent alors cette liste dynamique.
- Si aucun candidat valide n'est trouvé, fallback automatique sur `TRACKED_ITEM_IDS`.

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
- `app/strategy.py`: stratégie dynamique + backtesting
- `app/torn_client.py`: appels API Torn
- `app/storage.py`: SQLite (snapshots, prix, alertes, événements)
- `app/static/*`: dashboard web (HTML/CSS/JS)
