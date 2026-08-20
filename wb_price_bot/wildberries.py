from dataclasses import dataclass
import asyncio
import json
import re
import shutil
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlencode


UFA_LATITUDE = 54.735152
UFA_LONGITUDE = 55.958727
# Этот destination совпадает с публичной витриной WB. Положительный dest из
# geo API может выбирать другой склад и возвращать завышенную цену карточки.
UFA_FALLBACK_DESTINATION = "-1257786"
WB_WALLET_DISCOUNT_PERCENT = 2


class WildberriesError(Exception):
    pass


@dataclass(frozen=True)
class Product:
    article: int
    name: str
    brand: str
    price: int


def extract_article(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    query_article = parse_qs(parsed.query).get("card")
    if query_article and query_article[0].isdigit():
        return int(query_article[0])

    match = re.search(r"/catalog/(\d+)(?:/|$)", parsed.path)
    return int(match.group(1)) if match else None


class WildberriesClient:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.curl_path = shutil.which("curl.exe") or shutil.which("curl")
        if not self.curl_path:
            raise RuntimeError("Для запросов Wildberries не найден curl")
        self.destination = UFA_FALLBACK_DESTINATION

    async def close(self) -> None:
        return None

    async def _get_json(self, url: str, params: dict[str, str]) -> dict:
        full_url = f"{url}?{urlencode(params)}"
        last_error = "WB временно не отвечает"

        for attempt in range(3):
            process = await asyncio.create_subprocess_exec(
                self.curl_path,
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                str(self.timeout),
                "--connect-timeout",
                "10",
                "--retry",
                "2",
                "--retry-all-errors",
                "--retry-delay",
                "1",
                "--user-agent",
                "Mozilla/5.0",
                "--header",
                "Accept: application/json",
                full_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                try:
                    return json.loads(stdout.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    last_error = "WB вернул некорректный ответ"
            else:
                last_error = (
                    stderr.decode("utf-8", errors="replace").strip()
                    or "WB временно не отвечает"
                )

            if attempt < 2:
                await asyncio.sleep(attempt + 1)

        raise WildberriesError(last_error)

    async def refresh_ufa_destination(self) -> None:
        url = "https://user-geo-data.wildberries.ru/get-geo-info"
        params = {
            "longitude": str(UFA_LONGITUDE),
            "latitude": str(UFA_LATITUDE),
            "address": "0",
        }
        try:
            data = await self._get_json(url, params)
            # Geo API нужен как проверка доступности региона. Для цены используем
            # стабильный destination публичной витрины.
            if not data.get("destinations"):
                raise ValueError("WB не вернул региональные назначения")
            self.destination = UFA_FALLBACK_DESTINATION
        except (WildberriesError, ValueError, TypeError):
            # Региональный идентификатор меняется редко; резерв нужен при сбое geo API.
            self.destination = UFA_FALLBACK_DESTINATION

    async def get_product(self, article: int) -> Product:
        url = "https://card.wb.ru/cards/v4/detail"
        params = {
            "appType": "1",
            "curr": "rub",
            "dest": self.destination,
            "spp": "30",
            "nm": str(article),
        }
        try:
            data = await self._get_json(url, params)
        except (WildberriesError, ValueError) as error:
            raise WildberriesError("WB временно не отвечает") from error

        products = data.get("products") or []
        if not products:
            raise WildberriesError("товар не найден")

        raw = products[0]
        prices = []
        for size in raw.get("sizes") or []:
            price_data = size.get("price") or {}
            price = price_data.get("product")
            if isinstance(price, int) and price > 0:
                prices.append(price)

        if not prices:
            raise WildberriesError("у товара сейчас нет доступной публичной цены")

        public_price_kopecks = min(prices)
        wallet_price_kopecks = (
            public_price_kopecks * (100 - WB_WALLET_DISCOUNT_PERCENT) // 100
        )

        return Product(
            article=article,
            name=str(raw.get("name") or f"Товар {article}"),
            brand=str(raw.get("brand") or ""),
            price=wallet_price_kopecks // 100,
        )
