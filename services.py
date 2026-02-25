# services.py
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp


def today_sp() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y")


class Services:
    def __init__(self) -> None:
        self.bot_token = os.environ["BOT_TOKEN"]
        self.my_chat_id = str(os.environ["MY_CHAT_ID"])
        self.api_url = os.environ["API_URL"].strip()

        self.base = f"https://api.telegram.org/bot{self.bot_token}"
        self._session: Optional[aiohttp.ClientSession] = None

        self._cats: List[str] = []
        self._cats_ts: float = 0.0
        self.cats_ttl_seconds: int = int(
            os.environ.get("CATEGORIES_TTL_SECONDS", "21600")
        )

        self._timeout = aiohttp.ClientTimeout(total=10)

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise RuntimeError("Services session not started")
        return self._session

    async def send(
        self, text: str, reply_markup: Optional[Dict[str, Any]] = None
    ) -> None:
        payload: Dict[str, Any] = {"chat_id": self.my_chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        await self.session.post(f"{self.base}/sendMessage", json=payload)

    async def answer_callback(self, callback_id: str) -> None:
        await self.session.post(
            f"{self.base}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
        )

    async def post_google(self, payload: Dict[str, Any]) -> None:
        await self.session.post(self.api_url, json=payload)

    async def check_google(self, params: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session.get(self.api_url, params=params) as r:
            return await r.json()

    async def get_categories(self) -> List[str]:
        now = time.time()
        if self._cats and (now - self._cats_ts) < self.cats_ttl_seconds:
            return self._cats

        try:
            async with self.session.get(self.api_url) as r:
                j = await r.json()
                cats = j.get("categorias", [])
                if not isinstance(cats, list):
                    cats = []
                cleaned: List[str] = []
                for c in cats:
                    if isinstance(c, str):
                        s = c.strip()
                        if s:
                            cleaned.append(s)
                if cleaned:
                    self._cats = cleaned
                    self._cats_ts = now
        except Exception:
            pass

        return self._cats
