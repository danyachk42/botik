import os
import threading
import time

from flask import Flask, request

# Импортируем всю игровую логику и объект бота из main.py,
# но polling не запускается, потому что main.py стартует polling только при __main__.
import main as bot_module


app = Flask(__name__)


WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "telegram-webhook")
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "").rstrip("/")


def get_webhook_url() -> str:
    if not WEBHOOK_BASE_URL:
        # Telegram требует публичный HTTPS URL.
        raise RuntimeError(
            "Не задано WEBHOOK_BASE_URL. Пример: https://your-repl-name.your-repl-domain.repl.co"
        )
    return f"{WEBHOOK_BASE_URL}/{WEBHOOK_PATH}"


@app.route(f"/{WEBHOOK_PATH}", methods=["POST"])
def webhook():
    # Telegram шлёт JSON апдейты. Передаём их в pyTelegramBotAPI.
    raw = request.get_data(as_text=True)
    update = bot_module.types.Update.de_json(raw)
    bot_module.bot.process_new_updates([update])
    return "ok", 200


def run():
    # Инициализация БД и фоновых задач.
    bot_module.init_database()
    backup_thread = threading.Thread(target=bot_module.backup_loop, daemon=True)
    backup_thread.start()

    # Регистрируем webhook.
    # Важно: URL должен быть публичным HTTPS и указывать на наш маршрут.
    bot_module.bot.remove_webhook()
    bot_module.bot.set_webhook(get_webhook_url())

    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    # Небольшая задержка, если Replit поднял сеть чуть позже.
    for _ in range(10):
        try:
            run()
            break
        except Exception:
            time.sleep(1)
            continue

