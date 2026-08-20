import asyncio
from contextlib import suppress
from html import escape
import logging
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from config import load_config
from database import Database
from wildberries import WildberriesClient, WildberriesError, extract_article


BASE_DIR = Path(__file__).resolve().parent
router = Router()
database = Database(BASE_DIR / "data" / "bot.db")
wb_client: WildberriesClient | None = None


def format_price(price: int) -> str:
    return f"{price:,}".replace(",", " ") + " ₽"


def product_url(article: int) -> str:
    return f"https://www.wildberries.ru/catalog/{article}/detail.aspx"


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Привет! Я отслеживаю публичную цену товаров Wildberries для города "
        "<b>Уфа</b>.\n\n"
        "Отправь ссылку на товар или его артикул — я запомню текущую цену и "
        "сообщу при любом изменении.\n\n"
        "/list — список товаров\n"
        "/remove &lt;артикул&gt; — удалить товар\n"
        "/stop — удалить все товары\n"
        "/help — справка"
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await start(message)


@router.message(Command("list"))
async def list_products(message: Message) -> None:
    rows = await database.list_for_user(message.from_user.id)
    if not rows:
        await message.answer("Список пуст. Отправь ссылку WB или артикул товара.")
        return
    lines = ["<b>Отслеживаемые товары:</b>"]
    for row in rows:
        lines.append(
            f'\n<a href="{product_url(row["article"])}">{escape(row["name"])}</a>\n'
            f'Артикул: <code>{row["article"]}</code> · {format_price(row["last_price"])}'
        )
    await message.answer("\n".join(lines), disable_web_page_preview=True)


@router.message(Command("remove"))
async def remove_product(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Использование: <code>/remove 123456789</code>")
        return
    removed = await database.remove_product(message.from_user.id, int(parts[1]))
    await message.answer("Товар удалён." if removed else "Такого товара нет в списке.")


@router.message(Command("stop"))
async def stop_tracking(message: Message) -> None:
    count = await database.remove_all(message.from_user.id)
    await message.answer(
        f"Отслеживание остановлено. Удалено товаров: {count}."
        if count else "Список уже пуст."
    )


@router.message()
async def add_product(message: Message) -> None:
    if not message.text:
        return
    article = extract_article(message.text)
    if article is None:
        await message.answer("Пришли ссылку WB или только цифры артикула.")
        return
    await message.answer("Проверяю товар для Уфы…")
    try:
        product = await wb_client.get_product(article)
    except WildberriesError as error:
        await message.answer(f"Не удалось добавить товар: {escape(str(error))}.")
        return
    name = f"{product.brand} {product.name}".strip()
    added = await database.add_product(message.from_user.id, article, name, product.price)
    if not added:
        await message.answer("Этот товар уже отслеживается. Список: /list")
        return
    await message.answer(
        f"✅ <b>{escape(name)}</b>\nАртикул: <code>{article}</code>\n"
        f"Основная цена витрины для Уфы: <b>{format_price(product.price)}</b>\n\n"
        "Цена рассчитана с предлагаемой скидкой WB и может зависеть от способа оплаты.\n"
        "Сообщу при повышении или снижении цены."
    )


async def monitor_prices(bot: Bot, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        rows = await database.list_all()
        cache = {}
        for row in rows:
            article = row["article"]
            if article not in cache:
                try:
                    cache[article] = await wb_client.get_product(article)
                except WildberriesError:
                    logging.warning("Не удалось проверить артикул %s", article)
                    continue
            product = cache[article]
            old_price = row["last_price"]
            if product.price == old_price:
                continue
            await database.update_price(row["user_id"], article, product.price)
            direction = "снизилась 📉" if product.price < old_price else "выросла 📈"
            difference = product.price - old_price
            try:
                await bot.send_message(
                    row["user_id"],
                    f"Цена <b>{direction}</b>\n\n"
                    f'<a href="{product_url(article)}">{escape(row["name"])}</a>\n'
                    f"Было: <s>{format_price(old_price)}</s>\n"
                    f"Стало: <b>{format_price(product.price)}</b> ({difference:+} ₽)\n\n"
                    "Регион: Уфа",
                    disable_web_page_preview=True,
                )
            except (TelegramForbiddenError, TelegramBadRequest):
                logging.info("Не удалось уведомить пользователя %s", row["user_id"])


async def main() -> None:
    global wb_client
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await database.initialize()

    timeout = aiohttp.ClientTimeout(total=config.request_timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        wb_client = WildberriesClient(config.request_timeout_seconds)
        await wb_client.refresh_ufa_destination()

        api = TelegramAPIServer.from_base(config.telegram_api_base)
        telegram_session = AiohttpSession(api=api, timeout=config.request_timeout_seconds)
        bot = Bot(config.bot_token, session=telegram_session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = Dispatcher()
        dispatcher.include_router(router)
        monitor = None
        try:
            me = await bot.get_me()
            logging.info("Cloudflare-туннель работает. Запуск @%s", me.username)
            await bot.set_my_commands([
                BotCommand(command="start", description="Запустить бота"),
                BotCommand(command="list", description="Мои товары"),
                BotCommand(command="remove", description="Удалить товар"),
                BotCommand(command="stop", description="Удалить все товары"),
                BotCommand(command="help", description="Справка"),
            ])
            monitor = asyncio.create_task(monitor_prices(bot, config.check_interval_seconds))
            await dispatcher.start_polling(bot)
        finally:
            if monitor:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
            await bot.session.close()
            await wb_client.close()


if __name__ == "__main__":
    asyncio.run(main())
