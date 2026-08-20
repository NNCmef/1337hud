# Telegram-бот мониторинга цен Wildberries — Уфа

Бот принимает ссылку на карточку Wildberries или артикул, сохраняет текущую
публичную цену для Уфы и уведомляет при любом её изменении.

## Возможности

- отслеживание нескольких товаров для каждого пользователя;
- уведомления как о снижении, так и о повышении цены;
- хранение данных в SQLite;
- фиксированный регион проверки — Уфа;
- команды `/list`, `/remove <артикул>` и `/stop`.

## Установка на Windows

Откройте PowerShell в этой папке и выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Рекомендуется Python 3.11 или новее.

Создайте бота через [@BotFather](https://t.me/BotFather) и скопируйте токен.

Если `api.telegram.org` недоступен напрямую, создайте бесплатный Cloudflare
Worker:

1. Зарегистрируйтесь на [dash.cloudflare.com](https://dash.cloudflare.com).
2. Откройте `Workers & Pages` → `Create` → `Worker`.
3. Нажмите `Edit code`, замените код содержимым `cloudflare-worker.js`.
4. Нажмите `Deploy` и скопируйте адрес вида
   `https://имя.поддомен.workers.dev`.

Укажите токен и адрес Worker в `.env`:

```dotenv
BOT_TOKEN=ваш_токен
TELEGRAM_API_BASE=https://имя.поддомен.workers.dev
CHECK_INTERVAL_SECONDS=300
REQUEST_TIMEOUT_SECONDS=20
```

Запуск:

```powershell
python bot.py
```

Интервал проверки не может быть меньше 60 секунд. Для постоянной работы бот
должен оставаться запущенным на компьютере или сервере.

## Как определяется цена

Бот отслеживает основную цену, которую публичная витрина WB показывает крупно,
с учётом предлагаемой скидки WB. Рядом на карточке может отображаться более
высокая цена для другого способа оплаты. Персональные скидки авторизованного
аккаунта не учитываются. Неофициальные API Wildberries могут со временем
измениться.

## Как работает подключение

Бот использует обычный Telegram Bot API через ваш Cloudflare Worker. Поэтому
`API_ID`, `API_HASH`, MTProto-прокси и сайт `my.telegram.org` не нужны. Worker
пересылает HTTPS-запросы в Telegram; токен остаётся в локальном `.env` и в код
Worker не записывается.
