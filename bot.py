import asyncio
import csv
import json
import os
import random
import re
from io import BytesIO
from datetime import datetime

import qrcode
from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    UserAlreadyParticipantError,
    ChannelsTooMuchError,
    ChannelPrivateError,
    ChatAdminRequiredError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel, Chat

# ---------- ПУТИ ----------
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.txt")
SESSION_FILE = os.path.join(DATA_DIR, "session_string.txt")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")

# ---------- НАСТРОЙКИ ----------
MESSAGES_TO_CHECK = 50
DELAY_BETWEEN_CHANNELS = 1.0
DELAY_BETWEEN_PARTICIPATION = 2.0
AUTO_SCAN_INTERVAL = 900
MAX_CHANNELS_PER_PROFILE = 100

PRESET_CHANNELS = [
    "gtavi247", "cyberleekgtaviofficial", "gta6deluxe", "gta_6_play",
    "GTA6_m", "GTA6_6", "igropapka", "gta_6d", "gta_6k", "mir_gta6",
    "gta6side", "gta6_dailyy", "GrandTheftAuto6_ru", "gta6blog",
    "gta6main", "gta6princ", "ru_gtavi", "psforgta", "gta6news",
    "gtanews", "rockstar_hub", "gta6_leaks", "gta6_community",
    "minecraft_news", "mcpe_hub", "minecraft_giveaway", "free_minecraft"
]

GIVEAWAY_MARKERS = [
    "розыгрыш", "разыгрываю", "разыгрываем", "разыграю", "разыграем",
    "конкурс", "приз", "выиграй", "выиграть", "выиграл", "giveaway",
    "win", "free", "бесплатно", "подарок", "дарю", "дарим",
    "участвуй", "участвовать", "принять участие", "прими участие",
    "join", "enter", "take part", "выигрывай", "получи шанс",
    "шанс выиграть", "разыгрывается", "подарю", "раздача", "раздаю", "халява"
]

GTA6_MENTIONS = [
    "gta vi", "gta 6", "gta6", "grand theft auto vi", "grand theft auto 6",
    "гта 6", "гта6", "гта vi", "гтаvi", "гта-6", "gta", "гта", "rockstar"
]

PARTICIPATE_BUTTON_MARKERS = [
    "участв", "участвую", "принять участие", "прими участие",
    "join", "enter", "giveaway", "розыгрыш", "start", "я в деле",
    "хочу участвовать", "участие", "take part", "i'm in", "get it", "получить"
]

SUBSCRIBE_BUTTON_MARKERS = [
    "подписаться", "subscribe", "проверить подписку", "check subscription", "проверить", "check"
]

DEFAULT_CONFIG = {
    "api_id": 0,
    "api_hash": "",
    "phone": "",
    "your_id": 0,
    "auto_scan_interval_seconds": AUTO_SCAN_INTERVAL,
    "messages_to_check": MESSAGES_TO_CHECK,
    "max_channels_per_profile": MAX_CHANNELS_PER_PROFILE,
    "max_participations_per_run": 0,
    "max_participations_per_day": 0,
    "profiles": {
        "GTA VI": {
            "channel_keywords": ["GTA VI", "GTA6", "GTA 6", "ГТА 6", "ГТА6", "Grand Theft Auto 6"],
            "contest_keywords": GIVEAWAY_MARKERS,
            "topic_keywords": GTA6_MENTIONS,
            "require_buttons": False,
        },
        "MINECRAFT": {
            "channel_keywords": ["Minecraft", "Майнкрафт", "mcpe"],
            "contest_keywords": GIVEAWAY_MARKERS,
            "topic_keywords": ["minecraft", "майнкрафт", "mcpe", "java", "bedrock"],
            "require_buttons": False,
        },
    },
}

bot_client = None
user_client = None
config_data = DEFAULT_CONFIG

_scan_running = False
_stop_event = None

def _is_unlimited(v) -> bool:
    try:
        return int(v) <= 0
    except Exception:
        return True

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
    return cfg

def save_config(cfg: dict):
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_history() -> dict:
    ensure_data_dir()
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {uid: {"status": "unknown", "date": ""} for uid in data}
        return data
    except Exception:
        return {}

def save_history(history: dict):
    ensure_data_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_blacklist() -> list:
    ensure_data_dir()
    if not os.path.exists(BLACKLIST_FILE):
        return []
    try:
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_blacklist(bl: list):
    ensure_data_dir()
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(bl, f, ensure_ascii=False, indent=2)

def load_state() -> dict:
    ensure_data_dir()
    if not os.path.exists(STATE_FILE):
        return {"date": "", "participated_today": 0}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"date": "", "participated_today": 0}

def save_state(state: dict):
    ensure_data_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

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

def normalize_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower().strip())

def contains_any(text: str, keywords) -> bool:
    if not text or not keywords:
        return False
    norm = normalize_text(text)
    return any(normalize_text(kw) in norm for kw in keywords if kw)

def is_relevant_post(msg, profile: dict, ch_title: str = "", ch_username: str = "") -> bool:
    text = getattr(msg, "text", None)
    if not text:
        return False

    # Проверка черного списка каналов
    blacklist = load_blacklist()
    if ch_username and ch_username.lower() in [b.lower() for b in blacklist]:
        return False

    contest_kw = profile.get("contest_keywords", GIVEAWAY_MARKERS)
    topic_kw = profile.get("topic_keywords", [])

    if not contains_any(text, contest_kw):
        return False

    if topic_kw:
        in_text = contains_any(text, topic_kw)
        in_channel = contains_any(ch_title, topic_kw) or contains_any(ch_username, topic_kw)
        if not (in_text or in_channel):
            return False

    return True

def find_participate_button(msg):
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            t = (btn.text or "").lower()
            if any(m in t for m in PARTICIPATE_BUTTON_MARKERS):
                return btn
    return None

def find_subscribe_button(msg):
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            t = (btn.text or "").lower()
            if any(m in t for m in SUBSCRIBE_BUTTON_MARKERS):
                return btn
    return None

async def qr_auth(cfg: dict, b_client):
    u_client = TelegramClient(StringSession(), cfg["api_id"], cfg["api_hash"])
    await u_client.connect()

    if await u_client.is_user_authorized():
        return u_client

    await b_client.send_message(cfg["your_id"], "[QR] Генерация кода...")
    qr_login = await u_client.qr_login()

    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await b_client.send_file(cfg["your_id"], buf, caption="[QR] Отсканируйте код в Telegram.")

    try:
        await qr_login.wait(timeout=300)
    except asyncio.TimeoutError:
        await u_client.disconnect()
        raise RuntimeError("[-] Таймаут QR-входа.")
    except SessionPasswordNeededError:
        await b_client.send_message(cfg["your_id"], "[2FA] Введите облачный пароль:")
        queue = asyncio.Queue()

        @b_client.on(events.NewMessage(from_users=cfg["your_id"]))
        async def password_handler(event):
            await queue.put(event.raw_text.strip())

        try:
            password = await asyncio.wait_for(queue.get(), timeout=120)
            await u_client.sign_in(password=password)
        finally:
            b_client.remove_event_handler(password_handler)
            
    save_session_string(SESSION_FILE, u_client.session.save())
    await b_client.send_message(cfg["your_id"], "[+] Авторизация успешна.")
    return u_client

async def try_participate(u_client, msg, channel_username: str, message_id: int):
    try:
        try:
            ch = await u_client.get_entity(channel_username)
            await u_client(JoinChannelRequest(ch))
        except Exception:
            pass

        await asyncio.sleep(0.5)
        msg = await u_client.get_messages(channel_username, ids=message_id)
        if not msg or not msg.buttons:
            return ("link_only", "Нет интерактивных кнопок")

        btn = find_participate_button(msg) or find_subscribe_button(msg)
        if btn is None or getattr(btn, "url", None):
            return ("link_only", "Кнопка не найдена")

        await btn.click()
        return ("participated", "OK")
    except Exception as e:
        return ("failed", str(e)[:80])

async def run_parser_task(b_client, u_client, cfg, profile_name=None, auto_mode=False, debug=False):
    global _scan_running, _stop_event

    if _scan_running and not debug:
        await b_client.send_message(cfg["your_id"], "[!] Скан уже запущен или завис. Нажмите «СБРОСИТЬ ЗАВИСАНИЕ» в меню.")
        return

    _scan_running = True
    _stop_event = asyncio.Event()

    try:
        profiles_to_run = {}
        if profile_name and profile_name in cfg["profiles"]:
            profiles_to_run[profile_name] = cfg["profiles"][profile_name]
        else:
            profiles_to_run = cfg["profiles"]

        if not profiles_to_run:
            return

        history = load_history()
        state = load_state()

        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("date") != today:
            state = {"date": today, "participated_today": 0}
            save_state(state)

        max_per_run = int(cfg.get("max_participations_per_run", 0))
        max_per_day = int(cfg.get("max_participations_per_day", 0))
        messages_to_check = int(cfg.get("messages_to_check", MESSAGES_TO_CHECK))
        max_channels = int(cfg.get("max_channels_per_profile", MAX_CHANNELS_PER_PROFILE))

        participated_this_run = 0
        new_posts = []
        total_channels = 0

        if not auto_mode:
            await b_client.send_message(cfg["your_id"], "[~] Запущен поиск розыгрышей...")

        for prof_name, data in profiles_to_run.items():
            if _stop_event.is_set():
                break

            channel_kw = data.get("channel_keywords", [])
            found_channels = {}

            for uname in PRESET_CHANNELS:
                if _stop_event.is_set():
                    break
                try:
                    entity = await asyncio.wait_for(u_client.get_entity(uname), timeout=3.0)
                    if entity:
                        found_channels[entity.id] = entity
                except Exception:
                    pass

            for kw in channel_kw:
                if _stop_event.is_set():
                    break
                try:
                    result = await asyncio.wait_for(u_client(SearchRequest(q=kw, limit=30)), timeout=5.0)
                    for chat in result.chats:
                        if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                            found_channels[chat.id] = chat
                except Exception:
                    pass
                await asyncio.sleep(0.2)

            channels_list = list(found_channels.values())[:max_channels]
            total_channels += len(channels_list)

            for ch in channels_list:
                if _stop_event.is_set():
                    break

                ch_title = getattr(ch, "title", "") or ""
                ch_username = getattr(ch, "username", "") or ""
                if not ch_username:
                    continue

                try:
                    messages = await asyncio.wait_for(
                        u_client.get_messages(ch, limit=messages_to_check),
                        timeout=8.0
                    )
                except Exception:
                    continue

                for msg in messages:
                    if _stop_event.is_set():
                        break
                    if not msg or not msg.text:
                        continue

                    uid = f"{ch_username}:{msg.id}"
                    if uid in history:
                        continue

                    if not is_relevant_post(msg, data, ch_title, ch_username):
                        continue

                    link = f"https://t.me/{ch_username}/{msg.id}"
                    
                    run_limit_ok = _is_unlimited(max_per_run) or participated_this_run < max_per_run
                    day_limit_ok = _is_unlimited(max_per_day) or state["participated_today"] < max_per_day

                    if run_limit_ok and day_limit_ok:
                        status, detail = await try_participate(u_client, msg, ch_username, msg.id)
                        if status == "participated":
                            state["participated_today"] += 1
                            participated_this_run += 1
                        await asyncio.sleep(DELAY_BETWEEN_PARTICIPATION)
                    else:
                        status, detail = "link_only", "Лимит исчерпан"

                    history[uid] = {
                        "status": status,
                        "detail": detail,
                        "date": datetime.now().isoformat(timespec="seconds"),
                        "link": link,
                        "profile": prof_name,
                        "channel": ch_title or ch_username,
                    }
                    new_posts.append({
                        "uid": uid,
                        "status": status,
                        "detail": detail,
                        "link": link,
                        "profile": prof_name,
                        "channel": ch_username,
                        "text": msg.text[:400],
                    })

                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        save_history(history)
        save_state(state)

        for p in new_posts:
            marker = {
                "participated": "[+] УЧАСТИЕ",
                "link_only": "[•] РОЗЫГРЫШ",
                "failed": "[-] ОШИБКА",
            }.get(p["status"], "[?]")

            text = (
                f"<b>{marker}</b>\n"
                f"[{p['profile']}] @{p['channel']}\n\n"
                f"{p['text'][:300]}...\n\n"
                f"<a href=\"{p['link']}\">Перейти к посту</a>"
            )
            # Серые/стандартные кнопки действий с инлайн-функционалом
            buttons = [
                [Button.url("🔗 Открыть пост", p["link"])],
                [Button.inline(f"❌ В черный список @{p['channel']}", data=f"bl_add_{p['channel']}".encode())]
            ]
            try:
                await b_client.send_message(cfg["your_id"], text, parse_mode="html", link_preview=False, buttons=buttons)
            except Exception:
                pass
            await asyncio.sleep(0.4)

        if not auto_mode:
            await b_client.send_message(
                cfg["your_id"],
                f"<b>[#] ПОИСК ЗАВЕРШЕН</b>\n"
                f"Каналов проверено: {total_channels}\n"
                f"Новых постов найдено: {len(new_posts)}",
                parse_mode="html"
            )
    except Exception as e:
        await b_client.send_message(cfg["your_id"], f"[-] Ошибка выполнения скана: {str(e)[:100]}")
    finally:
        _scan_running = False
        if _stop_event:
            _stop_event.clear()

async def periodic_scanner(b_client, u_client, cfg, interval: int):
    await asyncio.sleep(30)
    while True:
        if not _scan_running:
            try:
                await run_parser_task(b_client, u_client, cfg, auto_mode=True)
            except Exception:
                pass
        await asyncio.sleep(interval)

def get_main_menu_buttons(cfg):
    running_label = "[■] СТОП (идёт скан)" if _scan_running else "[■] СТОП"
    return [
        [Button.inline("[>] ЗАПУСТИТЬ ПОИСК", data=b"run_all")],
        [Button.inline("[=] ПРОФИЛИ", data=b"manage_profiles")],
        [Button.inline(running_label, data=b"stop_scan")],
        [Button.inline("[!] СБРОСИТЬ ЗАВИСАНИЕ", data=b"force_reset")],
        [Button.inline("[x] СБРОСИТЬ ИСТОРИЮ", data=b"clear_history")],
    ]

async def setup_bot_handlers(b_client):
    @b_client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond(
            "<b>[ПАНЕЛЬ УПРАВЛЕНИЯ]</b>\n\nВыберите действие:",
            buttons=get_main_menu_buttons(config_data),
            parse_mode="html",
        )

    @b_client.on(events.NewMessage(pattern="/reset"))
    async def reset_cmd(event):
        global _scan_running, _stop_event
        if event.sender_id != int(config_data["your_id"]):
            return
        _scan_running = False
        if _stop_event:
            _stop_event.set()
        await event.respond("[+] Состояние принудительно сброшено.")

    @b_client.on(events.CallbackQuery)
    async def cb(event):
        global config_data, user_client, _scan_running, _stop_event
        if event.sender_id != int(config_data["your_id"]):
            return

        data = event.data.decode("utf-8")

        if data == "main_menu":
            await event.edit("<b>[ГЛАВНОЕ МЕНЮ]</b>", buttons=get_main_menu_buttons(config_data), parse_mode="html")
        elif data == "run_all":
            if _scan_running:
                await event.answer("Скан уже идёт", alert=True)
                return
            await event.edit("[~] Запуск...")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data))
        elif data == "stop_scan":
            if _scan_running and _stop_event and not _stop_event.is_set():
                _stop_event.set()
                await event.answer("Остановка...", alert=True)
            else:
                await event.answer("Скан не запущен", alert=True)
        elif data == "force_reset":
            _scan_running = False
            if _stop_event:
                _stop_event.set()
            await event.answer("Зависание сброшено!", alert=True)
            await event.edit("<b>[ГЛАВНОЕ МЕНЮ]</b>", buttons=get_main_menu_buttons(config_data), parse_mode="html")
        elif data == "manage_profiles":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.edit("📂 Нет профилей.", buttons=[[Button.inline("« Назад", data=b"main_menu")]])
                return
            btns = [[Button.inline(f"📁 {p}", data=f"edit_p_{p}".encode())] for p in profiles]
            btns.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("<b>[УПРАВЛЕНИЕ ПРОФИЛЯМИ]</b>", buttons=btns, parse_mode="html")
        elif data.startswith("edit_p_"):
            p_name = data.replace("edit_p_", "")
            prof = config_data["profiles"].get(p_name, {})
            ch_kw = ", ".join(prof.get("channel_keywords", []))
            co_kw = ", ".join(prof.get("contest_keywords", []))
            text = (
                f"<b>Профиль: {p_name}</b>\n\n"
                f"Ключи каналов: <code>{ch_kw}</code>\n"
            )
            btns = [
                [Button.inline("🗑 Удалить профиль", data=f"del_p_{p_name}".encode())],
                [Button.inline("« К списку", data=b"manage_profiles")]
            ]
            await event.edit(text, buttons=btns, parse_mode="html")
        elif data.startswith("del_p_"):
            p_name = data.replace("del_p_", "")
            config_data["profiles"].pop(p_name, None)
            save_config(config_data)
            await event.edit(f"🗑 Профиль <b>{p_name}</b> удален.", buttons=get_main_menu_buttons(config_data), parse_mode="html")
        elif data.startswith("bl_add_"):
            chan = data.replace("bl_add_", "")
            bl = load_blacklist()
            if chan.lower() not in [b.lower() for b in bl]:
                bl.append(chan)
                save_blacklist(bl)
            await event.answer(f"Канал @{chan} добавлен в черный список!", alert=True)
        elif data == "clear_history":
            save_history({})
            await event.answer("История сброшена", alert=True)
            await event.edit("<b>[ГЛАВНОЕ МЕНЮ]</b>", buttons=get_main_menu_buttons(config_data), parse_mode="html")

async def main():
    global bot_client, user_client, config_data
    config_data = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    bot_client = TelegramClient(os.path.join(DATA_DIR, "bot_session"), config_data["api_id"], config_data["api_hash"])
    await bot_client.start(bot_token=bot_token)
    print("[+] Бот запущен.")

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

    interval = int(config_data.get("auto_scan_interval_seconds", AUTO_SCAN_INTERVAL))
    asyncio.create_task(periodic_scanner(bot_client, user_client, config_data, interval))
    
    await bot_client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
