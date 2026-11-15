import asyncio
import json
import os
import re

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

# ---------- ПУТИ К ФАЙЛАМ С ДАННЫМИ ----------
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.txt")

# ---------- ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ (используются, если в config.json пусто) ----------
DEFAULT_CONFIG = {
    "api_id": 0,               # <-- ваш api_id (int) с my.telegram.org
    "api_hash": "",            # <-- ваш api_hash (str)
    "phone": "",               # <-- ваш номер в формате +7999...
    "your_id": 0,              # <-- ваш telegram user_id (int)
}

# ---------- КЛЮЧЕВЫЕ СЛОВА ----------
CHANNEL_KEYWORDS = [
    "GTA VI", "GTAVI", "ГТА 6", "ГТА6",
    "Grand Theft Auto 6", "Grand Theft Auto VI",
]

CONTEST_KEYWORDS = [
    "конкурс", "разыгрываю", "розыгрыш", "приз", "giveaway",
    "выиграй", "участвуй", "конкурсный",
]

MESSAGES_TO_CHECK = 50
DELAY_BETWEEN_CHANNELS = 3


# ---------- ЗАГРУЗКА / СОЗДАНИЕ КОНФИГА ----------
def ensure_data_dir():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        print(f"[+] Создана папка {DATA_DIR}/")


def load_config():
    """Читает data/config.json. Если файла нет — создаёт шаблон и просит заполнить."""
    ensure_data_dir()
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        raise FileNotFoundError(
            f"Файл {CONFIG_FILE} не найден — создан шаблон.\n"
            f"Заполните поля api_id, api_hash, phone, your_id и запустите снова."
        )

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    missing = [k for k in ("api_id", "api_hash", "phone", "your_id") if not cfg.get(k)]
    if missing:
        raise ValueError(
            f"В {CONFIG_FILE} не заполнены поля: {', '.join(missing)}"
        )
    return cfg


def read_bot_token(path: str) -> str:
    """Читает токен бота из data/token.txt."""
    ensure_data_dir()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Файл с токеном не найден: {path}\n"
            f"Создайте его и вставьте токен бота из @BotFather."
        )
    with open(path, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise ValueError(f"Файл {path} пустой. Вставьте в него токен бота.")
    return token


# ---------- УТИЛИТЫ ----------
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def contains_keywords(text: str, keywords) -> bool:
    if not text:
        return False
    norm_text = normalize_text(text)
    return any(normalize_text(kw) in norm_text for kw in keywords)


# ---------- ОСНОВНАЯ ЛОГИКА ----------
async def search_public_channels(user_client, keywords):
    found = {}
    for kw in keywords:
        try:
            print(f"[Поиск] Ищем каналы по запросу: {kw}")
            result = await user_client(SearchRequest(q=kw, limit=50))
            for chat in result.chats:
                if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                    if chat.id not in found:
                        found[chat.id] = chat
        except FloodWaitError as e:
            print(f"[FloodWait] Ждём {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print(f"[Ошибка поиска] {kw}: {e}")
        await asyncio.sleep(2)
    return list(found.values())


async def check_channel_for_contests(user_client, channel):
    matches = []
    try:
        messages = await user_client.get_messages(channel, limit=MESSAGES_TO_CHECK)
        for msg in messages:
            if not msg.text:
                continue
            if contains_keywords(msg.text, CONTEST_KEYWORDS):
                matches.append({
                    "channel_title": channel.title,
                    "channel_username": channel.username,
                    "message_id": msg.id,
                    "message_text": msg.text[:400],
                    "date": msg.date,
                    "link": (
                        f"https://t.me/{channel.username}/{msg.id}"
                        if channel.username else None
                    ),
                })
    except FloodWaitError as e:
        print(f"[FloodWait] Канал {channel.title}: ждём {e.seconds} сек.")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"[Ошибка чтения] {channel.title}: {e}")
    return matches


async def send_alert(bot_client, your_id, matches):
    if not matches:
        return

    by_channel = {}
    for m in matches:
        key = m["channel_username"] or m["channel_title"]
        by_channel.setdefault(key, []).append(m)

    for channel_key, msgs in by_channel.items():
        header = f"🎯 **Найдены конкурсы в канале** {channel_key}\n\n"
        body = ""
        for m in msgs[:5]:
            body += (
                f"• [{m['date'].strftime('%d.%m %H:%M')}] "
                f"{m['message_text'][:150]}...\n"
            )
            if m["link"]:
                body += f"  [Ссылка]({m['link']})\n"
        text = header + body + f"\nВсего совпадений: {len(msgs)}"

        try:
            await bot_client.send_message(
                your_id, text, parse_mode="md", link_preview=False
            )
        except Exception as e:
            print(f"[Ошибка отправки уведомления] {e}")
        await asyncio.sleep(1)


async def main():
    cfg = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    user_client = TelegramClient(
        os.path.join(DATA_DIR, "parser_session"), cfg["api_id"], cfg["api_hash"]
    )
    bot_client = TelegramClient(
        os.path.join(DATA_DIR, "bot_session"), cfg["api_id"], cfg["api_hash"]
    )

    print("🚀 Запуск парсера...")
    try:
        await user_client.start(phone=cfg["phone"])
    except SessionPasswordNeededError:
        pwd = input("Введите пароль двухфакторной аутентификации: ")
        await user_client.sign_in(password=pwd)
    print("✅ Userbot авторизован.")

    await bot_client.start(bot_token=bot_token)
    print("✅ Бот для уведомлений авторизован.")

    try:
        print("\n🔎 Этап 1: Поиск публичных каналов по ключевым словам...")
        channels = await search_public_channels(user_client, CHANNEL_KEYWORDS)
        print(f"Найдено уникальных каналов/чатов: {len(channels)}")

        if not channels:
            print("Каналы не найдены. Попробуйте изменить ключевые слова.")
            return

        print("\n📄 Этап 2: Проверка сообщений в найденных каналах...")
        all_matches = []
        for i, ch in enumerate(channels, 1):
            print(f"[{i}/{len(channels)}] Проверяем: {ch.title} (@{ch.username})")
            matches = await check_channel_for_contests(user_client, ch)
            if matches:
                print(f"   ✅ Найдено конкурсов: {len(matches)}")
                all_matches.extend(matches)
            else:
                print("   — совпадений нет")
            await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        if all_matches:
            print(f"\n📨 Отправляем уведомления о {len(all_matches)} найденных конкурсах...")
            await send_alert(bot_client, cfg["your_id"], all_matches)
            print("✅ Готово.")
        else:
            print("\n😔 Конкурсы по заданным ключевым словам не найдены.")
    finally:
        await user_client.disconnect()
        await bot_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
