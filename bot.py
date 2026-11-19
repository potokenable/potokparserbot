import asyncio
import hashlib
import json
import os
import re
from io import BytesIO
from datetime import datetime, timezone, timedelta

import qrcode
from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    UserAlreadyParticipantError,
    ChannelsTooMuchError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel, Chat

# ==================== ПУТИ ====================
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.txt")
SESSION_FILE = os.path.join(DATA_DIR, "session_string.txt")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")
BOTS_WHITELIST_FILE = os.path.join(DATA_DIR, "known_giveaway_bots.json")

# ==================== НАСТРОЙКИ ====================
SCAN_INTERVAL = 900
REPORT_INTERVAL = 1800
MESSAGES_TO_CHECK = 40
DELAY_BETWEEN_CHANNELS = 1.5
DELAY_BETWEEN_PARTICIPATION = 3.0
MAX_CHANNELS_PER_PROFILE = 120
MAX_POST_AGE_DAYS = 30
MIN_SCORE = 5

# ==================== КЛЮЧЕВЫЕ СЛОВА ====================
STRONG_GIVEAWAY = [
    "розыгрыш", "разыгрываю", "разыгрываем", "разыгрывается", "разыграю", "разыграем",
    "giveaway", "give away", "конкурс", "raffle", "выиграй", "выиграть", "выиграл",
    "раздача", "раздаю", "раздаем", "халява",
    "принять участие", "прими участие", "участвуй", "участвуйте", "я в деле",
    "разагривается", "приз", "prize", "победитель получит", "победитель",
    "winner will get", "contest", "бесплатная раздача",
]

WEAK_GIVEAWAY = [
    "бесплатно", "free", "подарок", "дарю", "дарим", "подарю",
    "шанс", "chance", "получить", "получи", "gift", "бонус", "bonus",
    "промокод", "promocode", "promo code",
]

CONDITION_MARKERS = [
    "подпишитесь", "подписаться на", "нужна подписка", "subscribe to",
    "перейдите", "нажмите", "выполните", "условия участия",
    "чтобы участвовать", "to participate", "to enter", "обязательное условие",
]

NEGATIVE = [
    "реклама", "рекламный", "продам", "продается", "продаю", "купить", "куплю",
    "цена", "стоимость", "оплата", "прайс", "обзор", "рейтинг", "новости", "новость",
    "подборка", "топ-", "топ ", "обсуждение", "вопрос", "помогите", "подскажите",
    "как получить", "инструкция", "гайд", "туториал", "скачать", "apk", "взлом",
    "чит", "cheat", "mod menu", "взломанный", "инвайт", "invite",
    "предзаказ", "pre-order", "вопрос-ответ", "faq",
]

PRESET_CHANNELS = [
    "giveaway_ru", "giveaway_tg", "tg_giveaways", "giveaway_all",
    "free_telegram", "giveaway_channel", "tg_giveaway_hub",
    "contests_ru", "raffle_ru", "giveaway_hunter",
]

SEARCH_QUERIES = [
    "giveaway", "розыгрыш", "конкурс", "раздача", "халява",
    "giveaway steam", "giveaway pc", "giveaway iphone",
    "giveaway crypto", "giveaway premium",
    "розыгрыш пк", "розыгрыш денег", "розыгрыш айфон",
    "розыгрыш премиум", "розыгрыш крипты", "giveaway nft",
    "free nft", "раздача крипты", "розыгрыш телефона",
]

PARTICIPATE_MARKERS = [
    "участв", "принять участие", "прими участие", "принять",
    "join", "enter", "розыгрыш", "начать", "start",
    "я в деле", "хочу участвовать", "участие",
    "take part", "i'm in", "i am in", "получить", "получи",
    "играть", "play", "крутить", "spin",
]

SUBSCRIBE_MARKERS = [
    "подписаться", "subscribe", "подпишись", "проверить подписку",
    "check subscription", "проверить", "check",
    "я подписался", "i subscribed", "готово", "done",
    "продолжить", "continue",
]

DEFAULT_BOTS = [
    "givesharebot", "voterbibot", "randstuff_bot", "random1zebot",
    "givaway_bot", "getlike_bot", "contestsbot", "lizaonair_bot",
    "giveawaybot", "tgiveawaybot",
]

DEFAULT_CONFIG = {
    "api_id": 0,
    "api_hash": "",
    "phone": "",
    "your_id": 0,
    "auto_scan_interval_seconds": SCAN_INTERVAL,
    "report_interval_seconds": REPORT_INTERVAL,
    "messages_to_check": MESSAGES_TO_CHECK,
    "max_channels_per_profile": MAX_CHANNELS_PER_PROFILE,
    "max_participations_per_run": 0,
    "max_participations_per_day": 0,
    "min_score_for_participation": MIN_SCORE,
    "profiles": {
        "ALL GIVEAWAYS": {
            "channel_keywords": [
                "giveaway", "розыгрыш", "конкурс", "раздача", "халява", "free"
            ],
            "topic_keywords": [],
            "min_score": MIN_SCORE,
        }
    },
}

# ==================== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ====================
bot_client = None
user_client = None
config_data = DEFAULT_CONFIG

_scan_running = False
_stop_event = None

# Буфер для отчёта
_pending_report = {
    "participated": [],   # [{link, channel, date}]
    "subscribed": set(),  # {channel_username}
    "failed": [],         # [{link, channel, reason}]
}


# ==================== I/O ====================
def ensure_data_dir():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)


def load_config() -> dict:
    ensure_data_dir()
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        raise FileNotFoundError(
            f"Создан шаблон {CONFIG_FILE}. Заполните api_id, api_hash, your_id."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    if not cfg.get("profiles"):
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
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_history(history: dict):
    ensure_data_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_blacklist() -> list:
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


def load_giveaway_bots() -> list:
    ensure_data_dir()
    if not os.path.exists(BOTS_WHITELIST_FILE):
        save_giveaway_bots(DEFAULT_BOTS)
        return list(DEFAULT_BOTS)
    try:
        with open(BOTS_WHITELIST_FILE, "r", encoding="utf-8") as f:
            bots = json.load(f)
        return list(set(bots + DEFAULT_BOTS))
    except Exception:
        return list(DEFAULT_BOTS)


def save_giveaway_bots(bots: list):
    ensure_data_dir()
    with open(BOTS_WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump(list(set(bots)), f, ensure_ascii=False, indent=2)


def load_state() -> dict:
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
        raise FileNotFoundError(f"Файл с токеном не найден: {path}")
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


# ==================== УТИЛИТЫ ====================
def normalize_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower().strip())


def get_message_text(msg) -> str:
    if not msg:
        return ""
    return (
        getattr(msg, "raw_text", None)
        or getattr(msg, "text", None)
        or getattr(msg, "message", None)
        or ""
    )


def text_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.md5(normalize_text(text)[:300].encode("utf-8")).hexdigest()[:16]


def extract_bot_username_from_url(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"t\.me/([a-zA-Z0-9_]+)", url)
    return m.group(1).lower() if m else ""


def find_bot_mention(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"@([a-zA-Z][a-zA-Z0-9_]{4,31}bot)\b", text, re.IGNORECASE)
    return m.group(1).lower() if m else ""


def is_unlimited(v) -> bool:
    try:
        return int(v) <= 0
    except Exception:
        return True


# ==================== КЛАССИФИКАЦИЯ ====================
def find_participate_button(msg):
    if not msg or not getattr(msg, "buttons", None):
        return None
    for row in msg.buttons:
        for btn in row:
            t = (getattr(btn, "text", "") or "").lower()
            if any(m in t for m in PARTICIPATE_MARKERS):
                return btn
    return None


def find_subscribe_button(msg):
    if not msg or not getattr(msg, "buttons", None):
        return None
    for row in msg.buttons:
        for btn in row:
            t = (getattr(btn, "text", "") or "").lower()
            if any(m in t for m in SUBSCRIBE_MARKERS):
                return btn
    return None


def classify_post(msg, profile: dict, ch_title: str, ch_username: str):
    """
    Возвращает (is_giveaway, score, reasons).
    Умный скоринг: ловит реальные розыгрыши, режет новости/рекламу.
    """
    text = get_message_text(msg)
    if not text or len(text) < 15:
        return False, 0, ["empty"]

    # Возраст поста
    msg_date = getattr(msg, "date", None)
    if msg_date:
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - msg_date) > timedelta(days=MAX_POST_AGE_DAYS):
            return False, 0, ["old"]

    norm = normalize_text(text)
    score = 0
    reasons = []

    # 1) Сильные маркеры
    strong_hits = sum(1 for kw in STRONG_GIVEAWAY if normalize_text(kw) in norm)
    if strong_hits:
        score += min(strong_hits, 3) * 4
        reasons.append(f"strong:{strong_hits}")

    # 2) Слабые маркеры
    weak_hits = sum(1 for kw in WEAK_GIVEAWAY if normalize_text(kw) in norm)
    if weak_hits:
        score += min(weak_hits, 3)
        reasons.append(f"weak:{weak_hits}")

    # 3) Условия участия
    cond_hits = sum(1 for kw in CONDITION_MARKERS if normalize_text(kw) in norm)
    if cond_hits:
        score += min(cond_hits, 2) * 2
        reasons.append(f"cond:{cond_hits}")

    # 4) Негативные маркеры — жирный минус
    neg_hits = sum(1 for kw in NEGATIVE if normalize_text(kw) in norm)
    if neg_hits:
        score -= min(neg_hits, 4) * 6
        reasons.append(f"neg:{neg_hits}")

    # 5) Кнопки
    has_part_btn = find_participate_button(msg) is not None
    has_sub_btn = find_subscribe_button(msg) is not None
    if has_part_btn:
        score += 5
        reasons.append("btn_part")
    if has_sub_btn:
        score += 2
        reasons.append("btn_sub")

    # 6) Кнопка/ссылка на известного бота
    known_bots = [b.lower() for b in load_giveaway_bots()]
    if getattr(msg, "buttons", None):
        for row in msg.buttons:
            for btn in row:
                url = getattr(btn, "url", "") or ""
                if "t.me/" in url:
                    bn = extract_bot_username_from_url(url)
                    if bn and (bn in known_bots or bn.endswith("bot")):
                        score += 3
                        reasons.append(f"bot:{bn}")
                        break

    # 7) Упоминание бота в тексте
    bot_mention = find_bot_mention(text)
    if bot_mention:
        score += 2
        reasons.append(f"bot_mention:{bot_mention}")

    # 8) Название канала
    ch_lower = (ch_title + " " + ch_username).lower()
    if any(w in ch_lower for w in (
        "giveaway", "розыгрыш", "конкурс", "раздача",
        "free", "подарок", "бесплат", "халява", "raffle",
    )):
        score += 3
        reasons.append("channel_name")

    # 9) Длинный пост — вероятно новость
    if len(text) > 3000:
        score -= 5
        reasons.append("too_long")

    # 10) Короткий пост без кнопок
    if len(text) < 60 and not has_part_btn:
        score -= 4
        reasons.append("too_short_no_btn")

    # 11) Эмодзи-подарки
    if re.search(r"[🎁🎉🎊🏆🎯💰💎🔥🎰]", text):
        score += 1

    threshold = int(profile.get("min_score", MIN_SCORE))
    return score >= threshold, score, reasons


def is_duplicate_text(history: dict, ch_username: str, text: str) -> bool:
    """Тот же самый текст поста в этом же канале за последние 14 дней."""
    if not text:
        return False
    th = text_hash(text)
    cutoff = datetime.now() - timedelta(days=14)
    for uid, info in history.items():
        if not uid.startswith(f"{ch_username}:"):
            continue
        if info.get("text_hash") != th:
            continue
        try:
            if datetime.fromisoformat(info.get("date", "")) > cutoff:
                return True
        except Exception:
            pass
    return False


# ==================== АВТОРИЗАЦИЯ ====================
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

        async def password_handler(event):
            await queue.put(event.raw_text.strip())

        b_client.add_event_handler(password_handler, events.NewMessage(from_users=cfg["your_id"]))
        try:
            password = await asyncio.wait_for(queue.get(), timeout=120)
            await u_client.sign_in(password=password)
        except PasswordHashInvalidError:
            await b_client.send_message(cfg["your_id"], "[-] Неверный пароль 2FA.")
            await u_client.disconnect()
            raise
        finally:
            b_client.remove_event_handler(password_handler)

    save_session_string(SESSION_FILE, u_client.session.save())
    await b_client.send_message(cfg["your_id"], "[+] Авторизация успешна.")
    return u_client


# ==================== УЧАСТИЕ ====================
async def try_join_channel(u_client, ch_username: str) -> bool:
    """True если подписка была новой."""
    try:
        ch = await u_client.get_entity(ch_username)
    except Exception:
        return False
    try:
        await u_client(JoinChannelRequest(ch))
        return True
    except UserAlreadyParticipantError:
        return False
    except ChannelsTooMuchError:
        raise
    except Exception:
        return False


async def try_participate(u_client, msg, ch_username: str):
    """
    Возвращает dict:
      status: 'participated' | 'manual_required' | 'failed'
      reason: str
      subscribed: bool
    """
    result = {"status": "failed", "reason": "", "subscribed": False}

    # 1) Подписываемся на канал
    try:
        if await try_join_channel(u_client, ch_username):
            result["subscribed"] = True
            await asyncio.sleep(1.2)
    except FloodWaitError as e:
        result["reason"] = f"FloodWait {e.seconds}с"
        raise

    # 2) Кнопка в текущем сообщении
    btn = find_participate_button(msg)
    sub_btn = find_subscribe_button(msg)

    if not btn and not sub_btn:
        result["reason"] = "Нет кнопки участия"
        return result

    # 3) Если только кнопка подписки — жмём, потом ищем кнопку участия
    if not btn and sub_btn:
        url = getattr(sub_btn, "url", "") or ""
        if url:
            bn = extract_bot_username_from_url(url)
            if bn:
                try:
                    await u_client.send_message(bn, "/start")
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
                result["status"] = "manual_required"
                result["reason"] = f"Бот @{bn} — подписка/участие вручную"
                return result
            result["status"] = "manual_required"
            result["reason"] = "Кнопка ведёт на внешнюю ссылку"
            return result
        try:
            await sub_btn.click()
            await asyncio.sleep(2)
            fresh = await u_client.get_messages(ch_username, ids=msg.id)
            if fresh:
                msg = fresh
                btn = find_participate_button(fresh)
        except Exception:
            pass

    if not btn:
        result["reason"] = "Кнопка участия не появилась"
        return result

    # 4) Если кнопка — URL (бот/внешняя ссылка) — пытаемся стартовать бота
    url = getattr(btn, "url", "") or ""
    if url:
        bn = extract_bot_username_from_url(url)
        if bn:
            bots = load_giveaway_bots()
            if bn not in bots:
                bots.append(bn)
                save_giveaway_bots(bots)
            try:
                await u_client.send_message(bn, "/start")
                await asyncio.sleep(1.5)
            except Exception:
                pass
            result["status"] = "manual_required"
            result["reason"] = f"Участие в боте @{bn}"
            return result
        result["status"] = "manual_required"
        result["reason"] = "Внешняя ссылка"
        return result

    # 5) Callback-кнопка — кликаем
    try:
        await btn.click()
        result["status"] = "participated"
        return result
    except FloodWaitError as e:
        result["reason"] = f"FloodWait {e.seconds}с"
        raise
    except Exception as e:
        result["reason"] = f"Ошибка: {str(e)[:60]}"
        return result


# ==================== СКАНЕР ====================
async def discover_channels(u_client, profile: dict, max_channels: int) -> dict:
    """Возвращает {id: entity} каналов для проверки."""
    found = {}
    keywords = profile.get("channel_keywords", [])

    # 1) Пресеты
    for uname in PRESET_CHANNELS:
        try:
            ent = await asyncio.wait_for(u_client.get_entity(uname), timeout=3.0)
            if ent:
                found[ent.id] = ent
        except Exception:
            pass

    # 2) Поиск по ключам профиля
    for kw in keywords:
        try:
            r = await asyncio.wait_for(
                u_client(SearchRequest(q=kw, limit=30)), timeout=6.0
            )
            for chat in r.chats:
                if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                    found[chat.id] = chat
        except Exception:
            pass
        await asyncio.sleep(0.3)

    # 3) Поиск по общим giveaway-запросам (если профиль "all")
    if not keywords or any("giveaway" in k.lower() for k in keywords):
        for q in SEARCH_QUERIES:
            try:
                r = await asyncio.wait_for(
                    u_client(SearchRequest(q=q, limit=20)), timeout=6.0
                )
                for chat in r.chats:
                    if isinstance(chat, (Channel, Chat)) and getattr(chat, "username", None):
                        found[chat.id] = chat
            except Exception:
                pass
            await asyncio.sleep(0.25)

    return dict(list(found.items())[:max_channels])


async def run_parser_task(b_client, u_client, cfg, auto_mode=False):
    global _scan_running, _stop_event, _pending_report

    if _scan_running and not auto_mode:
        await b_client.send_message(
            cfg["your_id"],
            "[!] Скан уже запущен. Нажмите «СБРОСИТЬ ЗАВИСАНИЕ».",
        )
        return

    _scan_running = True
    _stop_event = asyncio.Event()

    try:
        profiles = cfg.get("profiles", {})
        if not profiles:
            return

        history = load_history()
        seen_uids = set(history.keys())
        state = load_state()

        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("date") != today:
            state = {"date": today, "participated_today": 0}
            save_state(state)

        max_per_run = int(cfg.get("max_participations_per_run", 0))
        max_per_day = int(cfg.get("max_participations_per_day", 0))
        messages_to_check = int(cfg.get("messages_to_check", MESSAGES_TO_CHECK))
        max_channels = int(cfg.get("max_channels_per_profile", MAX_CHANNELS_PER_PROFILE))

        participated_run = 0
        blacklist = [b.lower() for b in load_blacklist()]

        if not auto_mode:
            await b_client.send_message(cfg["your_id"], "[~] Запуск умного поиска розыгрышей...")

        for prof_name, data in profiles.items():
            if _stop_event.is_set():
                break

            try:
                channels = await discover_channels(u_client, data, max_channels)
            except Exception as e:
                print(f"[discover] {e}")
                continue

            for ch_id, ch in channels.items():
                if _stop_event.is_set():
                    break

                ch_title = getattr(ch, "title", "") or ""
                ch_username = getattr(ch, "username", "") or ""
                if not ch_username:
                    continue
                if ch_username.lower() in blacklist:
                    continue

                try:
                    messages = await asyncio.wait_for(
                        u_client.get_messages(ch, limit=messages_to_check),
                        timeout=10.0,
                    )
                except Exception:
                    continue

                for msg in messages:
                    if _stop_event.is_set():
                        break
                    if not msg:
                        continue

                    text = get_message_text(msg)
                    if not text:
                        continue

                    uid = f"{ch_username}:{msg.id}"
                    if uid in seen_uids:
                        continue

                    is_ga, score, _reasons = classify_post(msg, data, ch_title, ch_username)
                    if not is_ga:
                        continue

                    # Дубль текста (репост того же розыгрыша)
                    if is_duplicate_text(history, ch_username, text):
                        history[uid] = {
                            "status": "duplicate_skip",
                            "date": datetime.now().isoformat(timespec="seconds"),
                            "text_hash": text_hash(text),
                        }
                        seen_uids.add(uid)
                        continue

                    run_ok = is_unlimited(max_per_run) or participated_run < max_per_run
                    day_ok = is_unlimited(max_per_day) or state["participated_today"] < max_per_day

                    if not (run_ok and day_ok):
                        history[uid] = {
                            "status": "limit_skip",
                            "date": datetime.now().isoformat(timespec="seconds"),
                            "text_hash": text_hash(text),
                        }
                        seen_uids.add(uid)
                        continue

                    # Пробуем участие
                    link = f"https://t.me/{ch_username}/{msg.id}"
                    try:
                        res = await try_participate(u_client, msg, ch_username)
                    except FloodWaitError as e:
                        await notify_critical(
                            b_client, cfg,
                            f"FloodWait при участии: {e.seconds}с. Скан остановлен."
                        )
                        _stop_event.set()
                        break

                    status = res["status"]
                    reason = res["reason"]
                    subscribed = res.get("subscribed", False)

                    if status == "participated":
                        state["participated_today"] += 1
                        participated_run += 1
                        _pending_report["participated"].append({
                            "link": link,
                            "channel": ch_username,
                            "date": datetime.now().isoformat(timespec="seconds"),
                        })
                    elif status == "manual_required":
                        _pending_report["failed"].append({
                            "link": link,
                            "channel": ch_username,
                            "reason": reason,
                        })

                    if subscribed:
                        _pending_report["subscribed"].add(ch_username)

                    history[uid] = {
                        "status": status,
                        "detail": reason,
                        "date": datetime.now().isoformat(timespec="seconds"),
                        "text_hash": text_hash(text),
                        "link": link,
                        "profile": prof_name,
                        "channel": ch_username,
                        "channel_title": ch_title,
                    }
                    seen_uids.add(uid)

                    await asyncio.sleep(DELAY_BETWEEN_PARTICIPATION)

                save_history(history)
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

        save_history(history)
        save_state(state)

        if not auto_mode:
            await b_client.send_message(
                cfg["your_id"],
                f"<b>[#] СКАН ЗАВЕРШЁН</b>\n"
                f"Участий за запуск: {participated_run}",
                parse_mode="html",
            )

    except Exception as e:
        await notify_critical(b_client, cfg, f"Ошибка сканера: {str(e)[:120]}")
    finally:
        _scan_running = False
        if _stop_event:
            _stop_event.clear()


# ==================== ОТЧЁТЫ ====================
async def notify_critical(b_client, cfg, text: str):
    try:
        await b_client.send_message(
            cfg["your_id"],
            f"🚨 <b>КРИТИЧЕСКАЯ ОШИБКА</b>\n\n{text}",
            parse_mode="html",
        )
    except Exception:
        pass


async def send_report(b_client, cfg):
    global _pending_report

    part = _pending_report["participated"]
    subs = _pending_report["subscribed"]
    fails = _pending_report["failed"]

    if not part and not subs and not fails:
        return  # нет активности — молчим

    text = "<b>[ОТЧЁТ ЗА 30 МИНУТ]</b>\n\n"
    text += f"✅ Поучаствовал в розыгрышах: <b>{len(part)}</b>\n"
    text += f"📢 Подписался на каналов: <b>{len(subs)}</b>\n"
    text += f"⚠️ Требуют ручного участия: <b>{len(fails)}</b>\n"

    if fails:
        text += "\n<b>Ручное участие (нужна ваша ссылка):</b>\n"
        for f in fails[:8]:
            text += f"• @{f['channel']} — {f['reason']}\n"
        if len(fails) > 8:
            text += f"...и ещё {len(fails) - 8}\n"

    buttons = []
    for f in fails[:10]:
        buttons.append([Button.url(f"🔗 @{f['channel']}", f["link"])])
    buttons.append([Button.inline("📋 Все мои розыгрыши", data=b"my_giveaways")])

    try:
        await b_client.send_message(
            cfg["your_id"], text,
            buttons=buttons, parse_mode="html", link_preview=False,
        )
    except Exception:
        pass

    _pending_report = {
        "participated": [],
        "subscribed": set(),
        "failed": [],
    }


async def periodic_scanner(b_client, u_client, cfg):
    await asyncio.sleep(30)
    interval = int(cfg.get("auto_scan_interval_seconds", SCAN_INTERVAL))
    while True:
        if not _scan_running:
            try:
                await run_parser_task(b_client, u_client, cfg, auto_mode=True)
            except Exception as e:
                print(f"[scanner] {e}")
        await asyncio.sleep(interval)


async def periodic_reporter(b_client, cfg):
    await asyncio.sleep(30)
    interval = int(cfg.get("report_interval_seconds", REPORT_INTERVAL))
    while True:
        await asyncio.sleep(interval)
        try:
            await send_report(b_client, cfg)
        except Exception as e:
            print(f"[reporter] {e}")


# ==================== UI ====================
def get_main_menu_buttons():
    running = " ■ СТОП" if _scan_running else ""
    return [
        [Button.inline(f"[>] ЗАПУСТИТЬ ПОИСК{running}", data=b"run_all")],
        [Button.inline("[=] ПРОФИЛИ", data=b"manage_profiles")],
        [Button.inline("📋 ВСЕ МОИ РОЗЫГРЫШИ", data=b"my_giveaways")],
        [Button.inline("[!] СБРОСИТЬ ЗАВИСАНИЕ", data=b"force_reset")],
        [Button.inline("🚫 ЧЁРНЫЙ СПИСОК", data=b"view_blacklist")],
    ]


async def show_my_giveaways(event, page: int = 0):
    history = load_history()
    items = []
    for uid, info in history.items():
        st = info.get("status")
        if st in ("participated", "manual_required", "failed"):
            items.append((uid, info))

    items.sort(key=lambda x: x[1].get("date", ""), reverse=True)

    if not items:
        await event.edit(
            "📋 Розыгрышей пока нет.",
            buttons=[[Button.inline("« Назад", data=b"main_menu")]],
        )
        return

    page_size = 8
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * page_size:(page + 1) * page_size]

    text = f"<b>[МОИ РОЗЫГРЫШИ]</b> ({page + 1}/{total_pages})\n\n"
    for _, info in chunk:
        st = info.get("status")
        emoji = {
            "participated": "✅",
            "manual_required": "⚠️",
            "failed": "❌",
        }.get(st, "•")
        date = (info.get("date", "") or "")[:16].replace("T", " ")
        ch = info.get("channel", "?")
        link = info.get("link", "")
        text += f"{emoji} {date} — @{ch}\n<a href=\"{link}\">→ открыть пост</a>\n\n"

    btns = []
    nav = []
    if page > 0:
        nav.append(Button.inline("◀️", data=f"my_ga_{page-1}".encode()))
    nav.append(Button.inline(f"{page+1}/{total_pages}", data=b"ignore"))
    if page < total_pages - 1:
        nav.append(Button.inline("▶️", data=f"my_ga_{page+1}".encode()))
    btns.append(nav)
    btns.append([Button.inline("« В главное меню", data=b"main_menu")])

    await event.edit(text, buttons=btns, parse_mode="html", link_preview=False)


async def setup_bot_handlers(b_client):
    @b_client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if event.sender_id != int(config_data["your_id"]):
            return
        await event.respond(
            "<b>[ПАНЕЛЬ УПРАВЛЕНИЯ]</b>\n\nВыберите действие:",
            buttons=get_main_menu_buttons(), parse_mode="html",
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
            await event.edit(
                "<b>[ГЛАВНОЕ МЕНЮ]</b>",
                buttons=get_main_menu_buttons(), parse_mode="html",
            )
        elif data == "ignore":
            await event.answer()
        elif data == "run_all":
            if _scan_running:
                await event.answer("Скан уже идёт", alert=True)
                return
            await event.edit("[~] Запуск умного поиска...")
            asyncio.create_task(
                run_parser_task(b_client, user_client, config_data, auto_mode=False)
            )
            await asyncio.sleep(1)
            await event.edit(
                "<b>[ГЛАВНОЕ МЕНЮ]</b>",
                buttons=get_main_menu_buttons(), parse_mode="html",
            )
        elif data == "force_reset":
            _scan_running = False
            if _stop_event:
                _stop_event.set()
            await event.answer("Сброшено!", alert=True)
            await event.edit(
                "<b>[ГЛАВНОЕ МЕНЮ]</b>",
                buttons=get_main_menu_buttons(), parse_mode="html",
            )
        elif data == "my_giveaways":
            await show_my_giveaways(event, 0)
        elif data.startswith("my_ga_"):
            try:
                p = int(data.replace("my_ga_", ""))
            except ValueError:
                p = 0
            await show_my_giveaways(event, p)
        elif data == "view_blacklist":
            bl = load_blacklist()
            if not bl:
                await event.edit(
                    "🚫 Чёрный список пуст.",
                    buttons=[[Button.inline("« Назад", data=b"main_menu")]],
                )
                return
            text = "<b>[ЧЁРНЫЙ СПИСОК]</b>\n\n"
            for ch in bl:
                text += f"• @{ch}\n"
            btns = [[Button.inline(f"❌ Удалить @{ch}", data=f"bl_del_{ch}".encode())] for ch in bl[:10]]
            btns.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit(text, buttons=btns, parse_mode="html")
        elif data.startswith("bl_del_"):
            ch = data.replace("bl_del_", "")
            bl = load_blacklist()
            bl = [b for b in bl if b.lower() != ch.lower()]
            save_blacklist(bl)
            await event.answer(f"@{ch} удалён из ЧС", alert=True)
            await event.edit(
                "<b>[ГЛАВНОЕ МЕНЮ]</b>",
                buttons=get_main_menu_buttons(), parse_mode="html",
            )
        elif data.startswith("bl_add_"):
            ch = data.replace("bl_add_", "")
            bl = load_blacklist()
            if ch.lower() not in [b.lower() for b in bl]:
                bl.append(ch)
                save_blacklist(bl)
            await event.answer(f"@{ch} добавлен в ЧС", alert=True)
        elif data == "manage_profiles":
            profiles = list(config_data["profiles"].keys())
            if not profiles:
                await event.edit(
                    "📂 Нет профилей.",
                    buttons=[[Button.inline("« Назад", data=b"main_menu")]],
                )
                return
            btns = [[Button.inline(f"📁 {p}", data=f"edit_p_{p}".encode())] for p in profiles]
            btns.append([Button.inline("« Назад", data=b"main_menu")])
            await event.edit("<b>[ПРОФИЛИ]</b>", buttons=btns, parse_mode="html")
        elif data.startswith("edit_p_"):
            p_name = data.replace("edit_p_", "")
            prof = config_data["profiles"].get(p_name, {})
            ch_kw = ", ".join(prof.get("channel_keywords", []))
            text = (
                f"<b>Профиль: {p_name}</b>\n\n"
                f"Ключи каналов: <code>{ch_kw}</code>\n"
                f"Мин. скоринг: <code>{prof.get('min_score', MIN_SCORE)}</code>\n"
            )
            btns = [
                [Button.inline("🗑 Удалить профиль", data=f"del_p_{p_name}".encode())],
                [Button.inline("« К списку", data=b"manage_profiles")],
            ]
            await event.edit(text, buttons=btns, parse_mode="html")
        elif data.startswith("del_p_"):
            p_name = data.replace("del_p_", "")
            config_data["profiles"].pop(p_name, None)
            save_config(config_data)
            await event.edit(
                f"🗑 Профиль <b>{p_name}</b> удалён.",
                buttons=get_main_menu_buttons(), parse_mode="html",
            )


# ==================== MAIN ====================
async def main():
    global bot_client, user_client, config_data

    config_data = load_config()
    bot_token = read_bot_token(TOKEN_FILE)

    bot_client = TelegramClient(
        os.path.join(DATA_DIR, "bot_session"),
        config_data["api_id"],
        config_data["api_hash"],
    )
    await bot_client.start(bot_token=bot_token)
    print("[+] Бот запущен.")

    await setup_bot_handlers(bot_client)

    session_string = read_session_string(SESSION_FILE)
    user_client = None
    if session_string:
        user_client = TelegramClient(
            StringSession(session_string),
            config_data["api_id"],
            config_data["api_hash"],
        )
        await user_client.connect()
        if not await user_client.is_user_authorized():
            await user_client.disconnect()
            user_client = None

    if user_client is None:
        user_client = await qr_auth(config_data, bot_client)

    asyncio.create_task(periodic_scanner(bot_client, user_client, config_data))
    asyncio.create_task(periodic_reporter(bot_client, config_data))

    await bot_client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
