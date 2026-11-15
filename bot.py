import asyncio
import json
import os
import re
from io import BytesIO

import qrcode
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
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
    "api_id": 0,
    "api_hash": "",
    "phone": "",
    "your_id": 0,
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
AUTH_TIMEOUT = 600

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

def read_session_string(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        s = f.read().strip()
    return s or None

def save_session_string(path: str, session: str):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        f.write(session)
    print(f"[+] Сессия сохранена в {path}")

# ---------- УТИЛИТЫ ----------
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())

def contains_keywords(text: str, keywords) -> bool:
    if not text:
        return False
    norm = normalize_text(text)
    return any(normalize_text(kw) in norm for kw in keywords)

# ---------- QR-АВТОРИЗАЦИЯ (ВСЁ НА ХОСТИНГЕ) ----------
async def qr_auth(cfg: dict, bot_client):
    """
    Авторизация через QR-код.
    Генерирует QR, отправляет фото в чат бота, ждет сканирования,
    запрашивает 2FA пароль при необходимости.
    Возвращает авторизованный user_client.
    """
    user_client = TelegramClient(StringSession(), cfg["api_id"], cfg["api_hash"])
    await user_client.connect()

    if await user_client.is_user_authorized():
        return user_client

    await bot_client.send_message(cfg["your_id"], "🔄 Генерация QR-кода для входа...")
    
    # Генерируем QR-логин
    qr_login = await user_client.qr_login()

    # Создаем изображение QR-кода
    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Отправляем фото через бота
    await bot_client.send_file(
        cfg["your_id"],
        buf,
        caption="📱 **Отсканируйте этот QR-код в Telegram:**\n"
                "Настройки -> Устройства -> Подключить устройство\n\n"
                "Ожидание сканирования (2 минуты)..."
    )

    try:
        await qr_login.wait(timeout=120)
    except SessionPasswordNeededError:
        # Запрос пароля 2FA через бота
        await bot_client.send_message(cfg["your_id"], "🔐 Введите пароль 2FA:")
        
        queue = asyncio.Queue()
        @bot_client.on(events.NewMessage(from_users=cfg["your_id"]))
        async def handler(event):
            await queue.put(event.raw_text.strip())
        
        try:
            password = await asyncio.wait_for(queue.get(), timeout=120)
            await user_client.sign_in(password=password)
        except asyncio.TimeoutError:
            await user_client.disconnect()
            raise RuntimeError("❌ Таймаут ввода пароля 2FA.")
    except Exception as e:
        await user_client.disconnect()
        raise RuntimeError(f"❌ Ошибка QR-входа: {e}")

    if not await user_client.is_user_authorized():
        await user_client.disconnect()
        raise RuntimeError("❌ Авторизация не удалась.")

    # Сохраняем сессию
    session_string = user_client.session.save()
    save_session_string(SESSION_FILE, session_string)
    await bot_client.send_message(cfg["your_id"], "✅ Авторизация успешна! Сессия сохранена.")
    return user_client

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
                    "link": (f"https://t.me/{channel.username}/{msg.id}" if channel.username else None),
                })
    except FloodWaitError as e:
        print(f"[FloodWait] {channel.title}: {e.seconds} сек.")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"[Ошибка чтения] {channel.title}: {e}")
    return matches

async def send_alert(bot_client, your_id, matches):
    if not matches: return
    by_channel = {}
    for m in matches:
        key = m["channel_username"] or m["channel_title"]
        by_channel.setdefault(key, []).append(m)

    for channel_key, msgs in by_channel.items():
        text = f"🎯 **Конкурсы в канале** {channel_key}\n\n"
        for m in msgs[:5]:
            text += f"• [{m['date'].strftime('%d.%m %H:%M')}] {m['message_text'][:150]}...\n"
            if m["link"]:
                text += f"  [Ссылка]({m['link']})\n"
        text += f"\nВсего совпадений: {len(msgs)}"
        try:
            await bot_client.send_message(your_id, text, parse_mode="md", link_preview=False)
        except Exception as e:
            print(f"[Ошибка отправки] {e}")
        await asyncio.sleep(1)

# ---------- MAIN ----------
async def main():
    cfg = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    # Бот для уведомлений и отправки QR
    bot_client = TelegramClient(os.path.join(DATA_DIR, "bot_session"), cfg["api_id"], cfg["api_hash"])
    await bot_client.start(bot_token=bot_token)
    print("✅ Бот авторизован.")

    # Userbot
    session_string = read_session_string(SESSION_FILE)
    user_client = None

    if session_string:
        print("✅ Используем сохранённую сессию.")
        user_client = TelegramClient(StringSession(session_string), cfg["api_id"], cfg["api_hash"])
        await user_client.connect()
        if not await user_client.is_user_authorized():
            print("⚠️ Сессия недействительна. Запускаем QR-вход.")
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        print("⚠️ Запуск QR-авторизации...")
        user_client = await qr_auth(cfg, bot_client)

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
