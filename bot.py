import asyncio
import json
import os
import re

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

# ---------- ПУТИ ----------
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.txt")
SESSION_FILE = os.path.join(DATA_DIR, "session_string.txt")

# ---------- КОНФИГ ПО УМОЛЧАНИЮ ----------
DEFAULT_CONFIG = {
    "api_id": 0,           # int с my.telegram.org
    "api_hash": "",        # str с my.telegram.org
    "phone": "",           # ваш номер, например "+79990000000"
    "your_id": 0,          # ваш Telegram user_id (int), для уведомлений и авторизации
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
AUTH_TIMEOUT = 600  # секунд на ввод кода/пароля через бота


# ---------- ФАЙЛЫ ----------
def ensure_data_dir():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        print(f"[+] Создана папка {DATA_DIR}/")


def load_config() -> dict:
    ensure_data_dir()
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        raise FileNotFoundError(
            f"Создан шаблон {CONFIG_FILE}. Заполните api_id, api_hash, phone, your_id "
            f"и запустите снова."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    missing = [k for k in ("api_id", "api_hash", "phone", "your_id") if not cfg.get(k)]
    if missing:
        raise ValueError(f"В {CONFIG_FILE} не заполнены поля: {', '.join(missing)}")
    return cfg


def read_bot_token(path: str) -> str:
    ensure_data_dir()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Файл с токеном не найден: {path}. Вставьте в него токен из @BotFather."
        )
    with open(path, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise ValueError(f"Файл {path} пустой. Вставьте в него токен бота.")
    return token


def save_session_string(path: str, session: str):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        f.write(session)
    print(f"[+] Сессия сохранена в {path}")


def load_session_string(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        s = f.read().strip()
    return s or None


# ---------- УТИЛИТЫ ----------
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def contains_keywords(text: str, keywords) -> bool:
    if not text:
        return False
    norm = normalize_text(text)
    return any(normalize_text(kw) in norm for kw in keywords)


# ---------- ИНТЕРАКТИВНАЯ АВТОРИЗАЦИЯ ЧЕРЕЗ БОТА ----------
async def _wait_for_user_input(queue: asyncio.Queue, prompt: str,
                               bot_client, your_id: int, timeout: int = AUTH_TIMEOUT) -> str:
    await bot_client.send_message(your_id, prompt)
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"❌ Таймаут ожидания ответа ({timeout} сек).")


async def interactive_auth(cfg: dict, bot_client):
    """
    Авторизует userbot: запрашивает код у Telegram, отправляет пользователю через бота,
    ждёт код в ответ, при необходимости — 2FA пароль.
    Возвращает (user_client, session_string).
    """
    user_client = TelegramClient(
        StringSession(), cfg["api_id"], cfg["api_hash"]
    )
    await user_client.connect()

    if await user_client.is_user_authorized():
        return user_client, user_client.session.save()

    # Запрос кода у Telegram
    try:
        await user_client.send_code_request(cfg["phone"])
    except FloodWaitError as e:
        await user_client.disconnect()
        raise RuntimeError(
            f"❌ Telegram требует подождать {e.seconds} сек. перед повторным запросом кода. "
            f"Подождите и перезапустите бота."
        )

    # Очередь сообщений от вас боту
    queue: asyncio.Queue = asyncio.Queue()

    @bot_client.on(events.NewMessage(from_users=cfg["your_id"]))
    async def _handler(event):
        await queue.put(event.raw_text.strip())

    code = await _wait_for_user_input(
        queue,
        "🔐 Требуется авторизация.\n"
        "Telegram отправил код подтверждения на ваш номер.\n"
        "Отправьте этот код сюда сообщением.",
        bot_client, cfg["your_id"],
    )

    for attempt in range(1, 4):
        try:
            await user_client.sign_in(cfg["phone"], code)
            break
        except SessionPasswordNeededError:
            password = await _wait_for_user_input(
                queue,
                "🔐 Включена двухфакторная аутентификация.\n"
                "Отправьте пароль 2FA сообщением.",
                bot_client, cfg["your_id"],
            )
            await user_client.sign_in(password=password)
            break
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            if attempt == 3:
                await user_client.disconnect()
                raise RuntimeError(f"❌ Не удалось войти: {e}")
            code = await _wait_for_user_input(
                queue,
                f"❌ {e}. Попробуйте ещё раз ({attempt + 1}/3):",
                bot_client, cfg["your_id"],
            )
        except Exception as e:
            if attempt == 3:
                await user_client.disconnect()
                raise RuntimeError(f"❌ Ошибка авторизации: {e}")
            code = await _wait_for_user_input(
                queue,
                f"❌ Ошибка: {e}. Попробуйте ещё раз ({attempt + 1}/3):",
                bot_client, cfg["your_id"],
            )

    if not await user_client.is_user_authorized():
        await user_client.disconnect()
        raise RuntimeError("❌ Авторизация не удалась.")

    session_string = user_client.session.save()
    await bot_client.send_message(cfg["your_id"], "✅ Авторизация успешна, сессия сохранена!")
    return user_client, session_string


# ---------- ЛОГИКА ПАРСЕРА ----------
async def search_public_channels(user_client, keywords):
    found = {}
    for kw in keywords:
        try:
            print(f"[Поиск] {kw}")
            result = await user_client(SearchRequest(q=kw, limit=50))
            for chat in result.chats:
                if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                    if chat.id not in found:
                        found[chat.id] = chat
        except FloodWaitError as e:
            print(f"[FloodWait] Ждём {e.seconds} сек.")
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
        print(f"[FloodWait] {channel.title}: {e.seconds} сек.")
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
        text = f"🎯 **Конкурсы в канале** {channel_key}\n\n"
        for m in msgs[:5]:
            text += (
                f"• [{m['date'].strftime('%d.%m %H:%M')}] "
                f"{m['message_text'][:150]}...\n"
            )
            if m["link"]:
                text += f"  [Ссылка]({m['link']})\n"
        text += f"\nВсего совпадений: {len(msgs)}"
        try:
            await bot_client.send_message(
                your_id, text, parse_mode="md", link_preview=False
            )
        except Exception as e:
            print(f"[Ошибка отправки] {e}")
        await asyncio.sleep(1)


# ---------- MAIN ----------
async def main():
    cfg = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    # Бот (авторизация по токену — без кода)
    bot_client = TelegramClient(
        os.path.join(DATA_DIR, "bot_session"), cfg["api_id"], cfg["api_hash"]
    )
    await bot_client.start(bot_token=bot_token)
    print("✅ Бот для уведомлений авторизован.")

    # Userbot: пробуем загрузить сохранённую сессию
    user_client = None
    session_string = load_session_string(SESSION_FILE)

    if session_string:
        user_client = TelegramClient(
            StringSession(session_string), cfg["api_id"], cfg["api_hash"]
        )
        await user_client.connect()
        if await user_client.is_user_authorized():
            print("✅ Userbot авторизован (сессия из файла).")
        else:
            print("⚠️ Сохранённая сессия недействительна, запускаем переавторизацию...")
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        print("⚠️ Сессии нет — запускаем интерактивную авторизацию через бота...")
        user_client, session_string = await interactive_auth(cfg, bot_client)
        save_session_string(SESSION_FILE, session_string)

    try:
        print("\n🔎 Этап 1: Поиск каналов...")
        channels = await search_public_channels(user_client, CHANNEL_KEYWORDS)
        print(f"Найдено каналов: {len(channels)}")

        if not channels:
            print("Каналы не найдены.")
            return

        print("\n📄 Этап 2: Проверка сообщений...")
        all_matches = []
        for i, ch in enumerate(channels, 1):
            print(f"[{i}/{len(channels)}] {ch.title} (@{ch.username})")
            matches = await check_channel_for_contests(user_client, ch)
            if matches:
                print(f"   ✅ Конкурсов: {len(matches)}")
                all_matches.extend(matches)
            else:
                print("   — нет")
            await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        if all_matches:
            print(f"\n📨 Отправка уведомлений ({len(all_matches)})...")
            await send_alert(bot_client, cfg["your_id"], all_matches)
            print("✅ Готово.")
        else:
            print("\n😔 Конкурсы не найдены.")
    finally:
        await user_client.disconnect()
        await bot_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
