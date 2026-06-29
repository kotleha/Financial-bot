from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from financial_bot.app.config import Settings


def create_telegram_bot(settings: Settings) -> Bot:
    proxy_url = settings.telegram_route_url.strip() if settings.telegram_route_url else None
    session = AiohttpSession(proxy=proxy_url) if proxy_url else None
    return Bot(token=settings.get_bot_token(), session=session)
