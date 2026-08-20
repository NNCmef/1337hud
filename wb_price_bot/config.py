from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    telegram_api_base: str
    check_interval_seconds: int
    request_timeout_seconds: int


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "1234567890:replace_with_botfather_token":
        raise RuntimeError("Укажите настоящий BOT_TOKEN в файле .env")

    api_base = os.getenv("TELEGRAM_API_BASE", "").strip().rstrip("/")
    if not api_base.startswith("https://"):
        raise RuntimeError(
            "Укажите HTTPS-адрес Cloudflare Worker в TELEGRAM_API_BASE файла .env"
        )

    return Config(
        bot_token=token,
        telegram_api_base=api_base,
        check_interval_seconds=max(
            60, int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
        ),
        request_timeout_seconds=max(
            5, int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
        ),
    )
