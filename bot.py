import asyncio
import json
import os
import re
from io import BytesIO

import qrcode
from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
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
    "profiles": {
        "GTA VI": {
            "channel_keywords": ["GTA VI", "GTAVI", "ГТА 6", "ГТА6", "Grand Theft Auto 6"],
            "contest_keywords": ["конкурс", "разыгрываю", "розыгрыш", "приз", "giveaway", "выиграй"]
        },
        "MINECRAFT": {
            "channel_keywords": ["Minecraft", "Майнкрафт", "mcpe"],
            "contest_keywords": ["конкурс", "разыгрываю", "розыгрыш", "приз", "giveaway", "выиграй"]
        }
    }
}

MESSAGES_TO_CHECK = 50
DELAY_BETWEEN_CHANNELS = 3

# ---------- ФАЙЛЫ И КОНФИГ ----------
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
            f"Создан шаблон {CONFIG_FILE}. Заполните api_id, api_hash, your_id "
            f"и перезапустите скрипт."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
    # Автоматическое обновление структуры при старом конфиге
    if "profiles" not in cfg:
        cfg["profiles"] = DEFAULT_CONFIG["profiles"]
        save_config(cfg)

    missing = [k for k in ("api_id", "api_hash", "your_id") if not cfg.get(k)]
    if missing:
        raise ValueError(f"В {CONFIG_FILE} не заполнены поля: {', '.join(missing)}")
    return cfg

def save_config(cfg: dict):
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def read_bot_token(path: str) -> str:
    ensure_data_dir()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл с токеном не найден: {path}. Вставьте токен от @BotFather.")
    with open(path, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise ValueError(f"Файл {path} пустой.")
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

# ---------- УТИЛИТЫ ----------
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())

def contains_keywords(text: str, keywords) -> bool:
    if not text:
        return False
    norm = normalize_text(text)
    return any(normalize_text(kw) in norm for kw in keywords)

# ---------- QR-АВТОРИЗАЦИЯ ----------
async def qr_auth(cfg: dict, bot_client):
    user_client = TelegramClient(StringSession(), cfg["api_id"], cfg["api_hash"])
    await user_client.connect()

    if await user_client.is_user_authorized():
        return user_client

    await bot_client.send_message(cfg["your_id"], "🔄 Генерация QR-кода для входа...")
    qr_login = await user_client.qr_login()

    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await bot_client.send_file(
        cfg["your_id"],
        buf,
        caption="📱 **Отсканируйте этот QR-код в Telegram:**\n"
                "Настройки -> Устройства -> Подключить устройство\n\n"
                "⏳ Ожидание сканирования (5 минут)..."
    )

    try:
        await qr_login.wait(timeout=300)
    except asyncio.TimeoutError:
        await user_client.disconnect()
        await bot_client.send_message(cfg["your_id"], "❌ Время ожидания QR-кода истекло.")
        raise RuntimeError("❌ Таймаут QR-входа.")
    except SessionPasswordNeededError:
        await bot_client.send_message(cfg["your_id"], "🔐 **Требуется 2FA!** Введите ваш облачный пароль:")
        queue = asyncio.Queue()

        async def password_handler(event):
            if event.sender_id == int(cfg["your_id"]):
                await queue.put(event.raw_text.strip())

        bot_client.add_event_handler(password_handler, events.NewMessage(from_users=cfg["your_id"]))
        try:
            for attempt in range(3):
                password = await asyncio.wait_for(queue.get(), timeout=120)
                try:
                    await user_client.sign_in(password=password)
                    break
                except PasswordHashInvalidError:
                    if attempt < 2:
                        await bot_client.send_message(cfg["your_id"], "❌ Неверный пароль! Попробуйте снова:")
                    else:
                        raise RuntimeError("❌ Превышено число попыток 2FA.")
        finally:
            bot_client.remove_event_handler(password_handler)
            
    except Exception as e:
        await user_client.disconnect()
        raise RuntimeError(f"❌ Ошибка QR-входа: {e}")

    if not await user_client.is_user_authorized():
        await user_client.disconnect()
        raise RuntimeError("❌ Авторизация не удалась.")

    session_string = user_client.session.save()
    save_session_string(SESSION_FILE, session_string)
    await bot_client.send_message(cfg["your_id"], "✅ Авторизация успешна!")
    return user_client

# ---------- ЛОГИКА ПАРСЕРА ----------
async def run_parser_task(bot_client, user_client, cfg, profile_name=None):
    profiles_to_run = {}
    if profile_name:
        if profile_name in cfg["profiles"]:
            profiles_to_run[profile_name] = cfg["profiles"][profile_name]
    else:
        profiles_to_run = cfg["profiles"]

    if not profiles_to_run:
        await bot_client.send_message(cfg["your_id"], "⚠️ Нет доступных профилей для поиска.")
        return

    await bot_client.send_message(cfg["your_id"], f"🚀 Запуск поиска розыгрышей (профилей: {len(profiles_to_run)})...")

    for prof_name, data in profiles_to_run.items():
        channel_kw = data.get("channel_keywords", [])
        contest_kw = data.get("contest_keywords", [])

        await bot_client.send_message(cfg["your_id"], f"📂 Профиль: **{prof_name}**\n🔎 Ищем каналы по ключевым словам...")
        
        found_channels = {}
        for kw in channel_kw:
            try:
                result = await user_client(SearchRequest(q=kw, limit=30))
                for chat in result.chats:
                    if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                        if chat.id not in found_channels:
                            found_channels[chat.id] = chat
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                pass
            await asyncio.sleep(1)

        channels_list = list(found_channels.values())
        await bot_client.send_message(cfg["your_id"], f"📌 Найдено каналов для `{prof_name}`: {len(channels_list)}. Проверяем сообщения...")

        all_matches = []
        for ch in channels_list:
            try:
                messages = await user_client.get_messages(ch, limit=MESSAGES_TO_CHECK)
                for msg in messages:
                    if not msg.text:
                        continue
                    if contains_keywords(msg.text, contest_kw):
                        all_matches.append({
                            "channel_title": ch.title,
                            "channel_username": ch.username,
                            "message_id": msg.id,
                            "message_text": msg.text[:300],
                            "date": msg.date,
                            "link": (f"https://t.me/{ch.username}/{msg.id}" if ch.username else None),
                        })
            except Exception:
                pass
            await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        # Отправка результатов профиля
        if all_matches:
            by_channel = {}
            for m in all_matches:
                key = m["channel_username"] or m["channel_title"]
                by_channel.setdefault(key, []).append(m)

            for chan_key, msgs in by_channel.items():
                text = f"🎯 [{prof_name}] Конкурсы в @{chan_key}\n\n"
                for m in msgs[:4]:
                    text += f"• [{m['date'].strftime('%d.%m %H:%M')}] {m['message_text'][:120]}...\n"
                    if m["link"]:
                        text += f"  [Ссылка]({m['link']})\n"
                try:
                    await bot_client.send_message(cfg["your_id"], text, parse_mode="md", link_preview=False)
                except Exception:
                    pass
                await asyncio.sleep(1)
        else:
            await bot_client.send_message(cfg["your_id"], f"😔 В профиле `{prof_name}` новых розыгрышей не найдено.")

    await bot_client.send_message(cfg["your_id"], "🏁 Поиск по всем выбранным профилям завершен!")

# ---------- ИНТЕРАКТИВНОЕ МЕНЮ БОТА ----------
def get_main_menu_buttons(cfg):
    buttons = [
        [Button.inline("🚀 Запустить весь поиск", data=b"run_all")],
        [Button.inline("📂 Выбрать профиль для поиска", data=b"select_run_profile")],
        [Button.inline("⚙️ Управление профилями", data=b"manage_profiles")],
        [Button.inline("➕ Добавить новый профиль", data=b"add_profile")]
    ]
    return buttons

async def setup_bot_interface(bot_client, cfg, user_client):
    @bot_client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if event.sender_id != int(cfg["your_id"]):
            return
        await event.respond(
            "🤖 **Панель управления парсером розыгрышей**\n\n"
            "Выберите нужное действие:",
            buttons=get_main_menu_buttons(cfg)
        )

    @bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        if event.sender_id != int(cfg["your_id"]):
            await event.answer("⛔ Доступ запрещен", alert=True)
            return

        data = event.data.decode("utf-8")

        if data == "main_menu":
            await event.edit("🤖 **Главное меню:**", buttons=get_main_menu_buttons(cfg))

        elif data == "run_all":
            await event.edit("⏳ Запускаю поиск по всем профилям...")
            asyncio.create_task(run_parser_task(bot_client, user_client, cfg))

        elif data == "select_run_profile":
            profiles = list(cfg["profiles"].keys())
            if not profiles:
                await event.answer("Нет созданных профилей!", alert=True)
                return
            buttons = [[Button.inline(p, data=f"run_p_{p}".encode())] for p in profiles]
            buttons.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("📂 Выберите профиль для поиска:", buttons=buttons)

        elif data.startswith("run_p_"):
            p_name = data.replace("run_p_", "")
            await event.edit(f"⏳ Запускаю поиск для профиля: **{p_name}**...")
            asyncio.create_task(run_parser_task(bot_client, user_client, cfg, profile_name=p_name))

        elif data == "manage_profiles":
            profiles = list(cfg["profiles"].keys())
            if not profiles:
                await event.edit("📂 Нет профилей.", buttons=[[Button.inline("« Назад", data=b"main_menu")]])
                return
            buttons = [[Button.inline(f"📁 {p}", data=f"edit_p_{p}".encode())] for p in profiles]
            buttons.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("⚙️ Выберите профиль для настройки:", buttons=buttons)

        elif data.startswith("edit_p_"):
            p_name = data.replace("edit_p_", "")
            prof = cfg["profiles"].get(p_name, {})
            ch_kw = ", ".join(prof.get("channel_keywords", []))
            co_kw = ", ".join(prof.get("contest_keywords", []))
            
            text = (
                f"📂 Профиль: **{p_name}**\n\n"
                f"🔎 **Ключи каналов:** `{ch_kw}`\n\n"
                f"🎁 **Ключи конкурсов:** `{co_kw}`"
            )
            buttons = [
                [Button.inline("✏️ Изменить ключи каналов", data=f"set_chk_{p_name}".encode())],
                [Button.inline("✏️ Изменить ключи конкурсов", data=f"set_cok_{p_name}".encode())],
                [Button.inline("🗑 Удалить профиль", data=f"del_p_{p_name}".encode())],
                [Button.inline("« К списку профилей", data=b"manage_profiles")]
            ]
            await event.edit(text, buttons=buttons, parse_mode="md")

        elif data.startswith("set_chk_") or data.startswith("set_cok_"):
            is_channels = data.startswith("set_chk_")
            p_name = data.replace("set_chk_" if is_channels else "set_cok_", "")
            
            await event.edit(
                f"✍️ Введите новые ключевые слова для профиля **{p_name}** "
                f"({'каналов' if is_channels else 'конкурсов'}), через запятую:"
            )
            
            queue = asyncio.Queue()
            @bot_client.on(events.NewMessage(from_users=cfg["your_id"]))
            async def input_handler(e):
                await queue.put(e.raw_text.strip())

            bot_client.add_event_handler(input_handler, events.NewMessage(from_users=cfg["your_id"]))
            try:
                new_text = await asyncio.wait_for(queue.get(), timeout=60)
                kw_list = [k.strip() for k in new_text.split(",") if k.strip()]
                
                if is_channels:
                    cfg["profiles"][p_name]["channel_keywords"] = kw_list
                else:
                    cfg["profiles"][p_name]["contest_keywords"] = kw_list
                
                save_config(cfg)
                await bot_client.send_message(cfg["your_id"], f"✅ Успешно обновлено для `{p_name}`!", buttons=get_main_menu_buttons(cfg))
            except asyncio.TimeoutError:
                await bot_client.send_message(cfg["your_id"], "❌ Время ввода истекло.", buttons=get_main_menu_buttons(cfg))
            finally:
                bot_client.remove_event_handler(input_handler)

        elif data.startswith("del_p_"):
            p_name = data.replace("del_p_", "")
            if p_name in cfg["profiles"]:
                del cfg["profiles"][p_name]
                save_config(cfg)
            await event.edit(f"🗑 Профиль **{p_name}** удален.", buttons=get_main_menu_buttons(cfg))

        elif data == "add_profile":
            await event.edit("➕ Введите название нового профиля (например: `CS2`, `NFT`):")
            queue = asyncio.Queue()

            @bot_client.on(events.NewMessage(from_users=cfg["your_id"]))
            async def name_handler(e):
                await queue.put(e.raw_text.strip())

            bot_client.add_event_handler(name_handler, events.NewMessage(from_users=cfg["your_id"]))
            try:
                p_name = await asyncio.wait_for(queue.get(), timeout=60)
                if p_name in cfg["profiles"]:
                    await bot_client.send_message(cfg["your_id"], "⚠️ Такой профиль уже существует!", buttons=get_main_menu_buttons(cfg))
                    return
                
                cfg["profiles"][p_name] = {
                    "channel_keywords": [p_name],
                    "contest_keywords": ["конкурс", "розыгрыш", "приз", "giveaway"]
                }
                save_config(cfg)
                await bot_client.send_message(
                    cfg["your_id"], 
                    f"✅ Профиль **{p_name}** создан!\n"
                    f"Теперь вы можете настроить его ключевые слова через «Управление профилями».", 
                    buttons=get_main_menu_buttons(cfg)
                )
            except asyncio.TimeoutError:
                await bot_client.send_message(cfg["your_id"], "❌ Время ввода истекло.", buttons=get_main_menu_buttons(cfg))
            finally:
                bot_client.remove_event_handler(name_handler)

# ---------- MAIN ----------
async def main():
    cfg = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    bot_client = TelegramClient(os.path.join(DATA_DIR, "bot_session"), cfg["api_id"], cfg["api_hash"])
    await bot_client.start(bot_token=bot_token)
    print("✅ Бот запущен и ожидает команд в Telegram (/start).")

    session_string = read_session_string(SESSION_FILE)
    user_client = None

    if session_string:
        print("✅ Используем сохранённую сессию юзербота.")
        user_client = TelegramClient(StringSession(session_string), cfg["api_id"], cfg["api_hash"])
        await user_client.connect()
        if not await user_client.is_user_authorized():
            print("⚠️ Сессия недействительна. Запускаем QR-вход.")
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        print("⚠️ Запуск QR-авторизации...")
        user_client = await qr_auth(cfg, bot_client)

    # Инициализация интерфейса бота
    await setup_bot_interface(bot_client, cfg, user_client)

    print("🟢 Бот и юзербот полностью активны. Перейдите в чат с вашим ботом и нажмите /start")
    
    # Бесконечный цикл, чтобы бот работал и ждал нажатий на кнопки
    await bot_client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
