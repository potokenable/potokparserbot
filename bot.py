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
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

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
DELAY_BETWEEN_CHANNELS = 2

# Глобальные переменные
bot_client = None
user_client = None
config_data = DEFAULT_CONFIG

# ---------- ФАЙЛЫ И КОНФИГ ----------
def ensure_data_dir():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def load_config() -> dict:
    ensure_data_dir()
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        raise FileNotFoundError(f"Создан шаблон {CONFIG_FILE}. Заполните api_id, api_hash, your_id.")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
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

def load_history() -> list:
    ensure_data_dir()
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(history: list):
    ensure_data_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def read_bot_token(path: str) -> str:
    ensure_data_dir()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл с токеном не найден: {path}.")
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
async def qr_auth(cfg: dict, b_client):
    u_client = TelegramClient(StringSession(), cfg["api_id"], cfg["api_hash"])
    await u_client.connect()

    if await u_client.is_user_authorized():
        return u_client

    await b_client.send_message(cfg["your_id"], "🔄 Генерация QR-кода для входа...")
    qr_login = await u_client.qr_login()

    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await b_client.send_file(
        cfg["your_id"],
        buf,
        caption="📱 **Отсканируйте этот QR-код в Telegram:**\n"
                "Настройки -> Устройства -> Подключить устройство"
    )

    try:
        await qr_login.wait(timeout=300)
    except asyncio.TimeoutError:
        await u_client.disconnect()
        raise RuntimeError("❌ Таймаут QR-входа.")
    except SessionPasswordNeededError:
        await b_client.send_message(cfg["your_id"], "🔐 **Требуется 2FA!** Введите ваш облачный пароль:")
        queue = asyncio.Queue()

        @b_client.on(events.NewMessage(from_users=cfg["your_id"]))
        async def password_handler(event):
            await queue.put(event.raw_text.strip())

        try:
            password = await asyncio.wait_for(queue.get(), timeout=120)
            await u_client.sign_in(password=password)
        finally:
            b_client.remove_event_handler(password_handler)
            
    except Exception as e:
        await u_client.disconnect()
        raise RuntimeError(f"❌ Ошибка QR-входа: {e}")

    session_string = u_client.session.save()
    save_session_string(SESSION_FILE, session_string)
    await b_client.send_message(cfg["your_id"], "✅ Авторизация успешна!")
    return u_client

# ---------- ЛОГИКА ПАРСЕРА ----------
async def run_parser_task(b_client, u_client, cfg, profile_name=None):
    profiles_to_run = {}
    if profile_name:
        if profile_name in cfg["profiles"]:
            profiles_to_run[profile_name] = cfg["profiles"][profile_name]
    else:
        profiles_to_run = cfg["profiles"]

    if not profiles_to_run:
        await b_client.send_message(cfg["your_id"], "⚠️ Нет доступных профилей для поиска.")
        return

    history = load_history()
    await b_client.send_message(cfg["your_id"], f"🚀 Запуск поиска розыгрышей (профилей: {len(profiles_to_run)})...")

    new_posts_found = 0

    for prof_name, data in profiles_to_run.items():
        channel_kw = data.get("channel_keywords", [])
        contest_kw = data.get("contest_keywords", [])

        await b_client.send_message(cfg["your_id"], f"📂 Профиль: **{prof_name}**\n🔎 Ищем каналы...")
        
        found_channels = {}
        for kw in channel_kw:
            try:
                result = await u_client(SearchRequest(q=kw, limit=25))
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
        await b_client.send_message(cfg["your_id"], f"📌 Найдено каналов для `{prof_name}`: {len(channels_list)}. Проверяем посты...")

        all_matches = []
        for ch in channels_list:
            try:
                messages = await u_client.get_messages(ch, limit=MESSAGES_TO_CHECK)
                for msg in messages:
                    if not msg.text:
                        continue
                    
                    chan_username = ch.username or str(ch.id)
                    post_uid = f"{chan_username}:{msg.id}"

                    if post_uid not in history and contains_keywords(msg.text, contest_kw):
                        all_matches.append({
                            "uid": post_uid,
                            "channel_title": ch.title,
                            "channel_username": chan_username,
                            "message_id": msg.id,
                            "message_text": msg.text[:300],
                            "date": msg.date,
                            "link": f"https://t.me/{chan_username}/{msg.id}" if ch.username else None,
                        })
            except Exception:
                pass
            await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        if all_matches:
            by_channel = {}
            for m in all_matches:
                key = m["channel_username"]
                by_channel.setdefault(key, []).append(m)

            for chan_key, msgs in by_channel.items():
                text = f"🎯 [{prof_name}] Новые конкурсы в @{chan_key}\n\n"
                for m in msgs[:4]:
                    text += f"• [{m['date'].strftime('%d.%m %H:%M')}] {m['message_text'][:120]}...\n"
                    if m["link"]:
                        text += f"  [Ссылка]({m['link']})\n"
                    
                    if m["uid"] not in history:
                        history.append(m["uid"])
                        new_posts_found += 1

                try:
                    await b_client.send_message(cfg["your_id"], text, parse_mode="md", link_preview=False)
                except Exception:
                    pass
                await asyncio.sleep(1)
        else:
            await b_client.send_message(cfg["your_id"], f"😔 В профиле `{prof_name}` новых уникальных розыгрышей нет.")

    save_history(history)
    await b_client.send_message(cfg["your_id"], f"🏁 Поиск завершен! Новых уникальных постов отправлено: {new_posts_found}")

# ---------- ИНТЕРАКТИВНОЕ МЕНЮ БОТА ----------
def get_main_menu_buttons(cfg):
    return [
        [Button.inline("🚀 Запустить весь поиск", data=b"run_all")],
        [Button.inline("📂 Выбрать профиль для поиска", data=b"select_run_profile")],
        [Button.inline("⚙️ Управление профилями", data=b"manage_profiles")],
        [Button.inline("➕ Добавить новый профиль", data=b"add_profile")],
        [Button.inline("🗑 Сбросить историю отправленных", data=b"clear_history")]
    ]

async def setup_bot_handlers(b_client):
    @b_client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond(
            "🤖 **Панель управления парсером розыгрышей**\n\n"
            "Выберите нужное действие:",
            buttons=get_main_menu_buttons(config_data)
        )

    @b_client.on(events.CallbackQuery)
    async def callback_handler(event):
        global config_data, user_client
        if event.sender_id != int(config_data["your_id"]):
            await event.answer("⛔ Доступ запрещен", alert=True)
            return

        data = event.data.decode("utf-8")

        if data == "main_menu":
            await event.edit("🤖 **Главное меню:**", buttons=get_main_menu_buttons(config_data))

        elif data == "run_all":
            await event.edit("⏳ Поиск запущен в фоновом режиме. Вы можете продолжать пользоваться меню.")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data))

        elif data == "select_run_profile":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.answer("Нет созданных профилей!", alert=True)
                return
            buttons = [[Button.inline(p, data=f"run_p_{p}".encode())] for p in profiles]
            buttons.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("📂 Выберите профиль для поиска:", buttons=buttons)

        elif data.startswith("run_p_"):
            p_name = data.replace("run_p_", "")
            await event.edit(f"⏳ Поиск для профиля **{p_name}** запущен в фоновом режиме.")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data, profile_name=p_name))

        elif data == "manage_profiles":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.edit("📂 Нет профилей.", buttons=[[Button.inline("« Назад", data=b"main_menu")]])
                return
            buttons = [[Button.inline(f"📁 {p}", data=f"edit_p_{p}".encode())] for p in profiles]
            buttons.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("⚙️ Выберите профиль для настройки:", buttons=buttons)

        elif data.startswith("edit_p_"):
            p_name = data.replace("edit_p_", "")
            prof = config_data["profiles"].get(p_name, {})
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
            
            await event.edit(f"✍️ Введите новые ключевые слова для профиля **{p_name}** через запятую:")
            
            queue = asyncio.Queue()
            @b_client.on(events.NewMessage(from_users=config_data["your_id"]))
            async def input_handler(e):
                await queue.put(e.raw_text.strip())

            try:
                new_text = await asyncio.wait_for(queue.get(), timeout=60)
                kw_list = [k.strip() for k in new_text.split(",") if k.strip()]
                
                if is_channels:
                    config_data["profiles"][p_name]["channel_keywords"] = kw_list
                else:
                    config_data["profiles"][p_name]["contest_keywords"] = kw_list
                
                save_config(config_data)
                await b_client.send_message(config_data["your_id"], f"✅ Успешно обновлено!", buttons=get_main_menu_buttons(config_data))
            except asyncio.TimeoutError:
                await b_client.send_message(config_data["your_id"], "❌ Время ввода истекло.", buttons=get_main_menu_buttons(config_data))
            finally:
                b_client.remove_event_handler(input_handler)

        elif data.startswith("del_p_"):
            p_name = data.replace("del_p_", "")
            if p_name in config_data["profiles"]:
                del config_data["profiles"][p_name]
                save_config(config_data)
            await event.edit(f"🗑 Профиль **{p_name}** удален.", buttons=get_main_menu_buttons(config_data))

        elif data == "add_profile":
            await event.edit("➕ Введите название нового профиля (например: `CS2`):")
            queue = asyncio.Queue()

            @b_client.on(events.NewMessage(from_users=config_data["your_id"]))
            async def name_handler(e):
                await queue.put(e.raw_text.strip())

            try:
                p_name = await asyncio.wait_for(queue.get(), timeout=60)
                if p_name in config_data["profiles"]:
                    await b_client.send_message(config_data["your_id"], "⚠️ Такой профиль уже существует!", buttons=get_main_menu_buttons(config_data))
                    return
                
                config_data["profiles"][p_name] = {
                    "channel_keywords": [p_name],
                    "contest_keywords": ["конкурс", "розыгрыш", "приз", "giveaway"]
                }
                save_config(config_data)
                await b_client.send_message(config_data["your_id"], f"✅ Профиль **{p_name}** создан!", buttons=get_main_menu_buttons(config_data))
            except asyncio.TimeoutError:
                await b_client.send_message(config_data["your_id"], "❌ Время ввода истекло.", buttons=get_main_menu_buttons(config_data))
            finally:
                b_client.remove_event_handler(name_handler)

        elif data == "clear_history":
            save_history([])
            await event.answer("🗑 История сброшена!", alert=True)
            await event.edit("🤖 **Главное меню:**", buttons=get_main_menu_buttons(config_data))

# ---------- MAIN ----------
async def main():
    global bot_client, user_client, config_data
    config_data = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    bot_client = TelegramClient(os.path.join(DATA_DIR, "bot_session"), config_data["api_id"], config_data["api_hash"])
    await bot_client.start(bot_token=bot_token)
    print("✅ Бот запущен.")

    await setup_bot_handlers(bot_client)

    session_string = read_session_string(SESSION_FILE)
    user_client = None

    if session_string:
        user_client = TelegramClient(StringSession(session_string), config_data["api_id"], config_data["api_hash"])
        await user_client.connect()
        if not await user_client.is_user_authorized():
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        user_client = await qr_auth(config_data, bot_client)

    print("🟢 Бот полностью активен. Напишите /start вашему боту в Telegram.")
    await bot_client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
