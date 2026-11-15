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

MESSAGES_TO_CHECK = 50
DELAY_BETWEEN_CHANNELS = 3
DELAY_BETWEEN_PARTICIPATION = 6
AUTO_SCAN_INTERVAL = 900
MAX_CHANNELS_PER_PROFILE = 60

# ---------- СЛОВАРИ ----------

GTA6_MENTIONS = [
    "gta vi", "gta 6", "gta6", "grand theft auto vi", "grand theft auto 6",
    "grand theft auto", "gta-v", "gta-v", "gta v",
    "гта 6", "гта6", "гта vi", "гтаvi", "гта-6", "gta-vi", "гта", "гта5", "гта 5",
    "gta v1", "gta vl", "gta 6i", "gta6i", "gta six", "gta ⅵ", "gta Ⅵ",
    "gta6️⃣", "gta 6️⃣", "гта шестой", "гта шестая", "гта 6-я", "гта 6ая",
    "gta sixth", "gta 6ой", "gta 6-ой", "гта 6 шестая часть",
    "gta vi ultimate", "gta 6 ultimate", "gta vi collector",
    "gta 6 collector", "gta vi deluxe", "gta 6 deluxe",
    "gta vi premium", "gta 6 premium edition",
    "gta vi standard", "gta 6 стандартное издание",
    "gta vi key", "gta 6 key", "gta vi code", "gta 6 code",
    "gta vi аккаунт", "gta 6 аккаунт", "gta vi steam", "gta 6 steam",
    "gta vi epic", "gta 6 epic games", "gta vi psn", "gta 6 psn",
    "gta vi xbox live", "gta 6 xbox", "gta vi rockstar", "gta 6 rockstar",
    "gta vi активация", "gta 6 активация", "ключ gta vi", "ключ gta 6",
    "ps5 gta", "playstation 5 gta", "ps5 gta vi", "ps5 gta 6",
    "xbox gta", "xbox series gta", "xbox series x gta", "xbox series s gta",
    "gta + ps5", "gta + xbox", "gta vi ps5", "gta 6 ps5",
    "gta vi xbox series x", "gta 6 xbox series",
    "предзаказ gta", "preorder gta", "gta vi preorder", "gta 6 preorder",
    "gta vi предзаказ", "gta 6 предзаказ",
    "розыгрыш gta", "разыгрываю gta", "разыгрываем gta", "конкурс gta",
    "приз gta", "выиграй gta", "выиграть gta", "получить gta бесплатно",
    "бесплатная gta", "gta в подарок", "gta за подписку", "gta за репост",
    "gta за комментарий", "gta за активность", "giveaway gta",
    "разыграть gta", "разыграем gta", "дарим gta", "подарить gta",
    "вручить gta", "отдать gta", "получить ключ gta", "получить аккаунт gta",
    "gta vi giveaway", "gta 6 giveaway", "win gta vi", "win gta 6",
    "free gta vi", "free gta 6", "gta vi free copy", "gta 6 key giveaway",
    "giveaway grand theft auto", "grand theft auto giveaway",
    "win a copy of gta", "free copy of gta",
    "gta 🎮", "gta 🎁", "gta 6 🎮", "gta vi 🎁", "🎁gta", "🎮gta",
    "#gta", "#gta6", "#gtavi", "#gtav", "#gtaonline", "#rockstar",
    "#grandtheftauto", "#розыгрышgta", "#giveawaygta",
    "гта онлайн", "gta online",
    "gta vi giveaway", "gta 6 giveaway", "gta vi конкурс", "gta 6 конкурс",
    "gta vi розыгрыш", "gta 6 розыгрыш", "gta vi выиграть", "gta 6 выиграть",
    "gta + ps5 + giveaway", "gta + xbox + giveaway",
    "gta + steam + giveaway", "gta + аккаунт",
    "gta vi + подписка", "gta 6 + подписка",
    "джта 6", "джта vi", "гта 6 (gta)", "gta (гта 6)", "gta 6 (гта)",
    "gta-six", "gta 6-vi", "gtavi", "gta-6", "gta-vi-6",
]

GIVEAWAY_MARKERS = [
    "розыгрыш", "разыгрываю", "разыгрываем", "разыграю", "разыграем",
    "конкурс", "приз", "выиграй", "выиграть", "выиграл", "giveaway",
    "win", "free", "бесплатно", "подарок", "дарю", "дарим",
    "участвуй", "участвовать", "принять участие", "прими участие",
    "join", "enter", "take part", "выигрывай",
    "получи шанс", "шанс получить", "шанс выиграть", "chance to win",
    "разыграть", "разыграем", "подарить", "вручить", "отдать",
    "получить бесплатно", "за подписку", "за репост", "за комментарий",
    "за активность", "sweepstakes", "contest",
    "бесплатный доступ", "free access", "free copy", "free key",
    "give-away", "give away", "разыгрывается",
]

PARTICIPATE_BUTTON_MARKERS = [
    "участв", "участвую", "принять участие", "прими участие",
    "join", "enter", "giveaway", "розыгрыш", "start",
    "я в деле", "хочу участвовать", "хочу", "буду участвовать",
    "участие", "take part", "i'm in", "im in", "get it",
    "получить", "забрать", "выиграть", "получить приз",
]

SUBSCRIBE_BUTTON_MARKERS = [
    "подписаться", "subscribe", "проверить подписку", "check subscription",
    "проверить", "check", "verify",
]

# ---------- КОНФИГ ПО УМОЛЧАНИЮ ----------
DEFAULT_CONFIG = {
    "api_id": 0,
    "api_hash": "",
    "phone": "",
    "your_id": 0,
    "auto_scan_interval_seconds": AUTO_SCAN_INTERVAL,
    "max_participations_per_run": 5,
    "max_participations_per_day": 30,
    "profiles": {
        "GTA VI": {
            # ВАЖНО: эти слова ищут ИМЕНА каналов, а не содержимое постов.
            # Только широкие темы — так находится больше каналов.
            "channel_keywords": [
                "GTA VI", "GTA6", "GTA 6", "ГТА 6", "ГТА6",
                "Grand Theft Auto 6", "Grand Theft Auto VI",
                "GTA", "ГТА", "Rockstar Games",
            ],
            "contest_keywords": GIVEAWAY_MARKERS,
            "topic_keywords": GTA6_MENTIONS,
            "require_buttons": False,
        },
        "MINECRAFT": {
            "channel_keywords": [
                "Minecraft", "Майнкрафт", "mcpe", "Minecraft PE",
                "Minecraft Bedrock", "Minecraft Java",
            ],
            "contest_keywords": GIVEAWAY_MARKERS,
            "topic_keywords": [
                "minecraft", "майнкрафт", "mine craft", "майн крафт",
                "minecraft java", "minecraft bedrock", "minecraft pe",
                "майнкрафт pe", "майнкрафт бедрок", "майнкрафт джава",
                "minecraft account", "майнкрафт аккаунт", "minecraft premium",
            ],
            "require_buttons": False,
        },
    },
}

bot_client = None
user_client = None
config_data = DEFAULT_CONFIG


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
            f"Создан шаблон {CONFIG_FILE}. Заполните api_id, api_hash, your_id "
            f"и перезапустите скрипт."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if "profiles" not in cfg:
        cfg["profiles"] = DEFAULT_CONFIG["profiles"]
        save_config(cfg)

    migrated = False
    for name, prof in cfg["profiles"].items():
        if "topic_keywords" not in prof:
            if name in DEFAULT_CONFIG["profiles"]:
                prof["topic_keywords"] = DEFAULT_CONFIG["profiles"][name]["topic_keywords"]
            else:
                prof["topic_keywords"] = [name.lower()]
            migrated = True
        if "contest_keywords" not in prof:
            prof["contest_keywords"] = GIVEAWAY_MARKERS
            migrated = True
        if "require_buttons" not in prof:
            prof["require_buttons"] = False
            migrated = True
        # принудительное отключение жёсткого фильтра кнопок
        # (это ломало поиск в предыдущей версии)
        if prof.get("require_buttons") is True:
            print(f"[!] Профиль '{name}': require_buttons True->False (фикс фильтра)")
            prof["require_buttons"] = False
            migrated = True

    if migrated:
        save_config(cfg)

    missing = [k for k in ("api_id", "api_hash", "your_id") if not cfg.get(k)]
    if missing:
        raise ValueError(f"В {CONFIG_FILE} не заполнены поля: {', '.join(missing)}")
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


# ---------- УТИЛИТЫ ----------
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
    """
    Пост релевантен, если:
      1) в тексте есть giveaway-маркер
      2) тема (topic_keywords) есть в тексте ИЛИ в названии/юзернейме канала
    Кнопки больше НЕ обязательны для фильтра — только для авто-участия.
    """
    text = getattr(msg, "text", None)
    if not text:
        return False

    topic_kw = profile.get("topic_keywords", [])
    contest_kw = profile.get("contest_keywords", GIVEAWAY_MARKERS)

    if not contains_any(text, contest_kw):
        return False

    if topic_kw:
        in_text = contains_any(text, topic_kw)
        in_channel = (
            contains_any(ch_title or "", topic_kw)
            or contains_any(ch_username or "", topic_kw)
        )
        if not (in_text or in_channel):
            return False

    return True


def find_participate_button(msg):
    """Возвращает MessageButton участия или None."""
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
        cfg["your_id"], buf,
        caption="📱 Отсканируйте QR-код в Telegram:\n"
                "Настройки -> Устройства -> Подключить устройство\n\n"
                "⏳ Ожидание (5 минут)..."
    )

    try:
        await qr_login.wait(timeout=300)
    except asyncio.TimeoutError:
        await u_client.disconnect()
        raise RuntimeError("❌ Таймаут QR-входа.")
    except SessionPasswordNeededError:
        await b_client.send_message(cfg["your_id"], "🔐 Требуется 2FA. Введите облачный пароль:")
        queue = asyncio.Queue()

        async def password_handler(event):
            if event.sender_id == int(cfg["your_id"]):
                await queue.put(event.raw_text.strip())

        b_client.add_event_handler(password_handler, events.NewMessage(from_users=cfg["your_id"]))
        try:
            for attempt in range(3):
                password = await asyncio.wait_for(queue.get(), timeout=120)
                try:
                    await u_client.sign_in(password=password)
                    break
                except PasswordHashInvalidError:
                    if attempt < 2:
                        await b_client.send_message(cfg["your_id"], "❌ Неверный пароль, ещё раз:")
                    else:
                        raise RuntimeError("❌ Превышено число попыток 2FA.")
        finally:
            b_client.remove_event_handler(password_handler)
    except Exception as e:
        await u_client.disconnect()
        raise RuntimeError(f"❌ Ошибка QR-входа: {e}")

    if not await u_client.is_user_authorized():
        await u_client.disconnect()
        raise RuntimeError("❌ Авторизация не удалась.")

    save_session_string(SESSION_FILE, u_client.session.save())
    await b_client.send_message(cfg["your_id"], "✅ Авторизация успешна!")
    return u_client


# ---------- АВТО-УЧАСТИЕ ----------
async def try_participate(u_client, msg, channel_username: str, message_id: int):
    """(status, detail) — participated / link_only / failed."""
    try:
        try:
            ch = await u_client.get_entity(channel_username)
            await u_client(JoinChannelRequest(ch))
        except (UserAlreadyParticipantError, ChannelsTooMuchError):
            pass
        except ChannelPrivateError:
            return ("link_only", "Канал приватный")
        except Exception:
            pass

        await asyncio.sleep(1.5)

        try:
            msg = await u_client.get_messages(channel_username, ids=message_id)
        except Exception as e:
            return ("failed", f"get_messages: {str(e)[:80]}")

        if not msg:
            return ("link_only", "Сообщение недоступно")

        if not msg.buttons:
            return ("link_only", "Нет inline-кнопок (участие вручную)")

        btn = find_participate_button(msg) or find_subscribe_button(msg)
        if btn is None:
            return ("link_only", "Кнопка 'Участвовать' не найдена")

        if getattr(btn, "url", None):
            return ("link_only", f"URL-кнопка: {btn.url}")

        try:
            await btn.click()
            return ("participated", "OK")
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            return ("failed", f"FloodWait {e.seconds}s")
        except ChatAdminRequiredError:
            return ("link_only", "Требуются права админа")
        except Exception as e:
            return ("failed", str(e)[:120])

    except Exception as e:
        return ("failed", str(e)[:120])


# ---------- ОСНОВНОЙ ПАРСЕР ----------
async def run_parser_task(b_client, u_client, cfg, profile_name=None, auto_mode=False, debug=False):
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

    max_per_run = int(cfg.get("max_participations_per_run", 5))
    max_per_day = int(cfg.get("max_participations_per_day", 30))
    participated_this_run = 0
    new_posts = []
    debug_lines = []

    if debug:
        await b_client.send_message(cfg["your_id"], "🔍 Режим диагностики запущен...")

    for prof_name, data in profiles_to_run.items():
        channel_kw = data.get("channel_keywords", [])
        if not channel_kw:
            debug_lines.append(f"❌ {prof_name}: пустой channel_keywords")
            continue

        found_channels = {}
        search_errors = 0
        for kw in channel_kw:
            try:
                result = await u_client(SearchRequest(q=kw, limit=25))
                for chat in result.chats:
                    if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                        found_channels[chat.id] = chat
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception as e:
                search_errors += 1
                debug_lines.append(f"⚠️ search '{kw}': {str(e)[:80]}")
            await asyncio.sleep(0.8)

        channels_list = list(found_channels.values())[:MAX_CHANNELS_PER_PROFILE]

        if debug:
            debug_lines.append(
                f"📂 <b>{prof_name}</b>: каналов {len(channels_list)} "
                f"(ошибок поиска: {search_errors})"
            )

        for ch in channels_list:
            ch_title = getattr(ch, "title", "") or ""
            ch_username = getattr(ch, "username", "") or ""

            try:
                messages = await u_client.get_messages(ch, limit=MESSAGES_TO_CHECK)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                if debug:
                    debug_lines.append(f"   ⚠️ чтение @{ch_username}: {str(e)[:60]}")
                continue

            # Статистика для debug
            giveaway_text_posts = 0
            with_buttons = 0
            relevant_posts = 0

            for msg in messages:
                if not msg or not msg.text:
                    continue

                if contains_any(msg.text, data.get("contest_keywords", GIVEAWAY_MARKERS)):
                    giveaway_text_posts += 1
                    if msg.buttons:
                        with_buttons += 1

                uid = f"{ch_username}:{msg.id}"
                if uid in history:
                    continue

                if not is_relevant_post(msg, data, ch_title, ch_username):
                    continue

                relevant_posts += 1
                link = f"https://t.me/{ch_username}/{msg.id}"

                status, detail = "link_only", "Лимит"
                can_participate = (
                    participated_this_run < max_per_run
                    and state["participated_today"] < max_per_day
                )
                if can_participate:
                    status, detail = await try_participate(
                        u_client, msg, ch_username, msg.id
                    )
                    if status == "participated":
                        state["participated_today"] += 1
                        participated_this_run += 1
                    await asyncio.sleep(DELAY_BETWEEN_PARTICIPATION + random.uniform(0, 2))

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
                    "channel": ch_title or ch_username,
                    "text": msg.text[:500],
                })

            if debug:
                debug_lines.append(
                    f"   • @{ch_username}: всего {len(messages)} | "
                    f"giveaway-слов {giveaway_text_posts} | "
                    f"с кнопками {with_buttons} | "
                    f"прошло фильтр {relevant_posts}"
                )

            await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

    save_history(history)
    save_state(state)

    if debug:
        header = "🔍 <b>Диагностика</b>\n\n" + "\n".join(debug_lines)
        try:
            await b_client.send_message(cfg["your_id"], header[:4000], parse_mode="html")
        except Exception:
            pass

    # ---- ОТПРАВКА УВЕДОМЛЕНИЙ ----
    for p in new_posts:
        emoji, header = {
            "participated": ("✅", "УЧАСТИЕ ПРИНЯТО"),
            "link_only":    ("🔗", "НУЖНО ВРУЧНУЮ"),
            "failed":       ("⚠️", "ОШИБКА УЧАСТИЯ"),
        }.get(p["status"], ("❓", "?"))

        text = (
            f"{emoji} <b>{header}</b>\n"
            f"📂 {p['profile']} | 📢 {p['channel']}\n"
        )
        if p["status"] != "participated":
            text += f"ℹ️ {p['detail']}\n"
        text += f"\n📝 {p['text'][:300]}...\n\n"
        text += f"🔗 <a href=\"{p['link']}\">Открыть пост</a>"

        try:
            await b_client.send_message(
                cfg["your_id"], text, parse_mode="html", link_preview=False,
            )
        except Exception:
            pass
        await asyncio.sleep(1)

    if not new_posts and not auto_mode:
        await b_client.send_message(cfg["your_id"], "😔 Новых розыгрышей не найдено.")

    if not auto_mode:
        await b_client.send_message(
            cfg["your_id"],
            f"🏁 Готово!\n"
            f"Новых постов: {len(new_posts)}\n"
            f"Участий в этот запуск: {participated_this_run}\n"
            f"Всего сегодня: {state['participated_today']}/{max_per_day}"
        )


# ---------- АВТО-СКАНЕР ----------
async def periodic_scanner(b_client, u_client, cfg, interval: int):
    await asyncio.sleep(30)
    while True:
        try:
            await run_parser_task(b_client, u_client, cfg, auto_mode=True)
        except Exception as e:
            try:
                await b_client.send_message(cfg["your_id"], f"⚠️ Авто-сканер: {str(e)[:200]}")
            except Exception:
                pass
        await asyncio.sleep(interval)


# ---------- CSV ----------
def export_history_csv() -> str:
    history = load_history()
    path = os.path.join(DATA_DIR, "history.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["uid", "status", "detail", "date", "link", "profile", "channel"])
        for uid, info in history.items():
            w.writerow([
                uid,
                info.get("status", ""),
                info.get("detail", ""),
                info.get("date", ""),
                info.get("link", ""),
                info.get("profile", ""),
                info.get("channel", ""),
            ])
    return path


# ---------- МЕНЮ ----------
def get_main_menu_buttons(cfg):
    return [
        [Button.inline("🚀 Запустить весь поиск", data=b"run_all")],
        [Button.inline("📂 Профиль для поиска", data=b"select_run_profile")],
        [Button.inline("⚙️ Управление профилями", data=b"manage_profiles")],
        [Button.inline("➕ Добавить профиль", data=b"add_profile")],
        [Button.inline("🔍 Диагностика", data=b"debug")],
        [Button.inline("📊 Статистика", data=b"stats")],
        [Button.inline("📥 Экспорт CSV", data=b"export_csv")],
        [Button.inline("🗑 Сбросить историю", data=b"clear_history")],
    ]


async def _text_input(b_client, cfg, timeout=60) -> str:
    queue = asyncio.Queue()

    async def handler(e):
        await queue.put(e.raw_text.strip())

    b_client.add_event_handler(handler, events.NewMessage(from_users=int(cfg["your_id"])))
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    finally:
        b_client.remove_event_handler(handler)


async def _show_profile_edit(event, p_name):
    prof = config_data["profiles"].get(p_name, {})
    ch_kw = ", ".join(prof.get("channel_keywords", []))
    co_kw = ", ".join(prof.get("contest_keywords", []))
    tp_kw = prof.get("topic_keywords", [])
    tp_preview = ", ".join(tp_kw[:15]) + (" ..." if len(tp_kw) > 15 else "")
    btn_req = prof.get("require_buttons", False)

    text = (
        f"📂 <b>{p_name}</b>\n\n"
        f"🔎 <b>Ключи каналов:</b>\n<code>{ch_kw}</code>\n\n"
        f"🎁 <b>Ключи конкурсов:</b>\n<code>{co_kw}</code>\n\n"
        f"🎯 <b>Тема ({len(tp_kw)}):</b>\n<code>{tp_preview}</code>\n\n"
        f"🔘 <b>Требовать кнопки (фильтр):</b> {'да' if btn_req else 'нет'}"
    )
    btns = [
        [Button.inline("✏️ Ключи каналов", data=f"set_chk_{p_name}".encode())],
        [Button.inline("✏️ Ключи конкурсов", data=f"set_cok_{p_name}".encode())],
        [Button.inline("✏️ Ключи темы", data=f"set_tpk_{p_name}".encode())],
        [Button.inline(
            f"🔘 Требовать кнопки: {'вкл' if btn_req else 'выкл'}",
            data=f"tgl_btn_{p_name}".encode())],
        [Button.inline("🗑 Удалить профиль", data=f"del_p_{p_name}".encode())],
        [Button.inline("« К списку", data=b"manage_profiles")],
    ]
    await event.edit(text, buttons=btns, parse_mode="html")


async def setup_bot_handlers(b_client):
    @b_client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond(
            "🤖 <b>Панель парсера розыгрышей</b>\n\n"
            f"Автоскан: каждые "
            f"{config_data.get('auto_scan_interval_seconds', AUTO_SCAN_INTERVAL) // 60} мин.\n"
            "Команды: /find /debug",
            buttons=get_main_menu_buttons(config_data),
            parse_mode="html",
        )

    @b_client.on(events.NewMessage(pattern="/find"))
    async def find_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond("⏳ Запускаю поиск...")
        asyncio.create_task(run_parser_task(b_client, user_client, config_data))

    @b_client.on(events.NewMessage(pattern="/debug"))
    async def debug_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond("🔍 Запускаю диагностику...")
        asyncio.create_task(run_parser_task(b_client, user_client, config_data, debug=True))

    @b_client.on(events.CallbackQuery)
    async def cb(event):
        global config_data, user_client
        if event.sender_id != int(config_data["your_id"]):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        data = event.data.decode("utf-8")

        if data == "main_menu":
            await event.edit("🤖 <b>Главное меню</b>",
                             buttons=get_main_menu_buttons(config_data),
                             parse_mode="html")

        elif data == "run_all":
            await event.edit("⏳ Запускаю поиск по всем профилям...")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data))

        elif data == "debug":
            await event.edit("🔍 Диагностика...")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data, debug=True))

        elif data == "select_run_profile":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.answer("Нет профилей!", alert=True)
                return
            btns = [[Button.inline(p, data=f"run_p_{p}".encode())] for p in profiles]
            btns.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("📂 Выберите профиль:", buttons=btns)

        elif data.startswith("run_p_"):
            p_name = data.replace("run_p_", "")
            await event.edit(f"⏳ Запуск: <b>{p_name}</b>...", parse_mode="html")
            asyncio.create_task(run_parser_task(b_client, user_client, config_data, profile_name=p_name))

        elif data == "manage_profiles":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.edit("📂 Нет профилей.",
                                 buttons=[[Button.inline("« Назад", data=b"main_menu")]])
                return
            btns = [[Button.inline(f"📁 {p}", data=f"edit_p_{p}".encode())] for p in profiles]
            btns.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("⚙️ Выберите профиль:", buttons=btns)

        elif data.startswith("edit_p_"):
            p_name = data.replace("edit_p_", "")
            await _show_profile_edit(event, p_name)

        elif data.startswith("tgl_btn_"):
            p_name = data.replace("tgl_btn_", "")
            if p_name in config_data["profiles"]:
                cur = config_data["profiles"][p_name].get("require_buttons", False)
                config_data["profiles"][p_name]["require_buttons"] = not cur
                save_config(config_data)
            await _show_profile_edit(event, p_name)

        elif data.startswith(("set_chk_", "set_cok_", "set_tpk_")):
            is_ch = data.startswith("set_chk_")
            is_co = data.startswith("set_cok_")
            is_tp = data.startswith("set_tpk_")
            p_name = (data.replace("set_chk_", "")
                          .replace("set_cok_", "")
                          .replace("set_tpk_", ""))
            kind = "каналов" if is_ch else ("конкурсов" if is_co else "темы")
            await event.edit(
                f"✍️ Введите новые ключи <b>{kind}</b> для <b>{p_name}</b> через запятую:",
                parse_mode="html",
            )
            try:
                new_text = await _text_input(b_client, config_data)
            except asyncio.TimeoutError:
                await b_client.send_message(config_data["your_id"], "❌ Время истекло.",
                                            buttons=get_main_menu_buttons(config_data))
                return
            kw = [k.strip() for k in new_text.split(",") if k.strip()]
            if is_ch:
                config_data["profiles"][p_name]["channel_keywords"] = kw
            elif is_co:
                config_data["profiles"][p_name]["contest_keywords"] = kw
            else:
                config_data["profiles"][p_name]["topic_keywords"] = kw
            save_config(config_data)
            await b_client.send_message(
                config_data["your_id"],
                f"✅ Обновлено ({kind}) для <b>{p_name}</b>: {len(kw)} ключей.",
                buttons=get_main_menu_buttons(config_data),
                parse_mode="html",
            )

        elif data.startswith("del_p_"):
            p_name = data.replace("del_p_", "")
            config_data["profiles"].pop(p_name, None)
            save_config(config_data)
            await event.edit(f"🗑 Профиль <b>{p_name}</b> удалён.",
                             buttons=get_main_menu_buttons(config_data),
                             parse_mode="html")

        elif data == "add_profile":
            await event.edit("➕ Введите название нового профиля:")
            try:
                p_name = await _text_input(b_client, config_data)
            except asyncio.TimeoutError:
                await b_client.send_message(config_data["your_id"], "❌ Время истекло.",
                                            buttons=get_main_menu_buttons(config_data))
                return
            if p_name in config_data["profiles"]:
                await b_client.send_message(config_data["your_id"], "⚠️ Уже существует.",
                                            buttons=get_main_menu_buttons(config_data))
                return
            config_data["profiles"][p_name] = {
                "channel_keywords": [p_name],
                "contest_keywords": GIVEAWAY_MARKERS,
                "topic_keywords": [p_name.lower()],
                "require_buttons": False,
            }
            save_config(config_data)
            await b_client.send_message(
                config_data["your_id"],
                f"✅ Профиль <b>{p_name}</b> создан.",
                buttons=get_main_menu_buttons(config_data),
                parse_mode="html",
            )

        elif data == "stats":
            history = load_history()
            state = load_state()
            total = len(history)
            by_status, by_profile = {}, {}
            for uid, info in history.items():
                s = info.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
                p = info.get("profile", "—")
                by_profile[p] = by_profile.get(p, 0) + 1
            text = (
                f"📊 <b>Статистика</b>\n\n"
                f"Всего постов: <b>{total}</b>\n"
                f"✅ Участий: <b>{by_status.get('participated', 0)}</b>\n"
                f"🔗 Только ссылки: <b>{by_status.get('link_only', 0)}</b>\n"
                f"⚠️ Ошибок: <b>{by_status.get('failed', 0)}</b>\n\n"
                f"Сегодня: {state.get('participated_today', 0)}/"
                f"{config_data.get('max_participations_per_day', 30)}\n\n"
                f"<b>По профилям:</b>\n"
            )
            for p, n in sorted(by_profile.items(), key=lambda x: -x[1]):
                text += f"• {p}: {n}\n"
            await event.edit(text,
                             buttons=[[Button.inline("« Назад", data=b"main_menu")]],
                             parse_mode="html")

        elif data == "export_csv":
            path = export_history_csv()
            try:
                await b_client.send_file(config_data["your_id"], path,
                                         caption=f"📥 {path}")
            except Exception as e:
                await event.answer(f"Ошибка: {e}", alert=True)

        elif data == "clear_history":
            save_history({})
            save_state({"date": datetime.now().strftime("%Y-%m-%d"),
                        "participated_today": 0})
            await event.answer("🗑 История и счётчик сброшены!", alert=True)
            await event.edit("🤖 <b>Главное меню</b>",
                             buttons=get_main_menu_buttons(config_data),
                             parse_mode="html")


# ---------- MAIN ----------
async def main():
    global bot_client, user_client, config_data
    config_data = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    bot_client = TelegramClient(
        os.path.join(DATA_DIR, "bot_session"),
        config_data["api_id"], config_data["api_hash"],
    )
    await bot_client.start(bot_token=bot_token)
    print("✅ Бот запущен.")

    await setup_bot_handlers(bot_client)

    session_string = read_session_string(SESSION_FILE)
    user_client = None
    if session_string:
        print("✅ Используем сохранённую сессию юзербота.")
        user_client = TelegramClient(
            StringSession(session_string),
            config_data["api_id"], config_data["api_hash"],
        )
        await user_client.connect()
        if not await user_client.is_user_authorized():
            print("⚠️ Сессия недействительна. QR-вход.")
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        print("⚠️ Запуск QR-авторизации...")
        user_client = await qr_auth(config_data, bot_client)

    interval = int(config_data.get("auto_scan_interval_seconds", AUTO_SCAN_INTERVAL))
    asyncio.create_task(periodic_scanner(bot_client, user_client, config_data, interval))
    print(f"🟢 Авто-сканер каждые {interval // 60} мин. /start в боте.")

    await bot_client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
