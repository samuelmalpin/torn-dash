from __future__ import annotations

import aiohttp
import asyncio
import smtplib
from email.message import EmailMessage

from app.config import settings


class Notifier:
    def __init__(self, discord_webhook_url: str) -> None:
        self.discord_webhook_url = discord_webhook_url.strip()
        self.telegram_bot_token = settings.telegram_bot_token.strip()
        self.telegram_chat_id = settings.telegram_chat_id.strip()
        self.smtp_host = settings.smtp_host.strip()
        self.smtp_port = settings.smtp_port
        self.smtp_username = settings.smtp_username.strip()
        self.smtp_password = settings.smtp_password
        self.smtp_use_tls = settings.smtp_use_tls
        self.email_from = settings.email_from.strip()
        self.email_to = settings.email_to.strip()
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def send(self, channels: list[str], message: str, kind: str) -> None:
        if self._session is None or not channels:
            return

        normalized = {channel.strip().lower() for channel in channels if channel.strip()}
        tasks = []

        if "discord" in normalized:
            tasks.append(self._send_discord(message))
        if "telegram" in normalized:
            tasks.append(self._send_telegram(message))
        if "email" in normalized:
            tasks.append(self._send_email(message, kind))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_discord(self, message: str) -> None:
        if not self.discord_webhook_url or self._session is None:
            return
        payload = {"content": message[:1900]}
        async with self._session.post(self.discord_webhook_url, json=payload) as response:
            response.raise_for_status()

    async def _send_telegram(self, message: str) -> None:
        if not self.telegram_bot_token or not self.telegram_chat_id or self._session is None:
            return
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {"chat_id": self.telegram_chat_id, "text": message[:3500]}
        async with self._session.post(url, json=payload) as response:
            response.raise_for_status()

    async def _send_email(self, message: str, kind: str) -> None:
        if not self.smtp_host or not self.email_from or not self.email_to:
            return

        subject = f"[Torn Nexus] Alert {kind}"
        await asyncio.to_thread(self._send_email_sync, subject, message)

    def _send_email_sync(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to
        msg.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as smtp:
            if self.smtp_use_tls:
                smtp.starttls()
            if self.smtp_username:
                smtp.login(self.smtp_username, self.smtp_password)
            smtp.send_message(msg)
