# Torn Nexus Bot

Bot Torn + dashboard web futuriste, prêt pour un déploiement personnel sur Docker.

## Fonctionnalités

- Polling automatique de l'API Torn (profil, bars, money, points, events)
- Suivi marché pour une liste d'items configurable
- Auth dashboard (login + rôles admin/viewer)
- Moteur d'alertes multi-canaux (Discord, Telegram, email)
- Anti-spam d'alertes via cooldown configurable
- Stratégie de BUY signal à seuil dynamique (volatilité + moyenne mobile)
- Backtesting sur historique (réservé admin)
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
	- `AUTH_SECRET`
	- `DASHBOARD_USERS`

3. Lancer le service :

```bash
docker compose up -d --build
```

4. Ouvrir le dashboard :

```text
http://localhost:8000
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
- `POLL_INTERVAL_SECONDS`: fréquence de polling user/events
- `MARKET_POLL_INTERVAL_SECONDS`: fréquence de polling marché
- `TRACKED_ITEM_IDS`: IDs d'items Torn séparés par virgule
- `DISCORD_WEBHOOK_URL`: webhook Discord pour alertes
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: canal Telegram
- `SMTP_*` + `EMAIL_FROM`/`EMAIL_TO`: alertes email
- `ALERT_CHANNEL_RULES`: routage par type d'alerte
- `PRICE_DROP_ALERT_PERCENT`: seuil d'alerte baisse de prix
- `ALERT_COOLDOWN_SECONDS`: délai minimum entre 2 alertes identiques
- `DASHBOARD_HISTORY_POINTS`: profondeur des courbes sur le dashboard
- `DASHBOARD_USERS`: utilisateurs `username:password:role`
- `AUTH_SECRET`: secret de signature de session
- `STRATEGY_*`: paramètres stratégie dynamique
- `BACKTEST_*`: paramètres de validation historique
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
- `app/strategy.py`: stratégie dynamique + backtesting
- `app/torn_client.py`: appels API Torn
- `app/storage.py`: SQLite (snapshots, prix, alertes, événements)
- `app/static/*`: dashboard web (HTML/CSS/JS)
