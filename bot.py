import asyncio
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "11111"

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_FILE = BASE_DIR / "schedule.json"
SUBSCRIBERS_FILE = BASE_DIR / "subscribers.json"

authenticated_admins = set()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Asia/Irkutsk")

DAYS_MAP = {
    "mon": ("Понедельник", 0),
    "tue": ("Вторник", 1),
    "wed": ("Среда", 2),
    "thu": ("Четверг", 3),
    "fri": ("Пятница", 4),
    "sat": ("Суббота", 5),
}

RU_DAY_NAMES = {
    "mon": "ПН",
    "tue": "ВТ",
    "wed": "СР",
    "thu": "ЧТ",
    "fri": "ПТ",
    "sat": "СБ",
}

WEEKDAY_TO_CODE = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
}

MONTHS_RU = {
    1: "янв.", 2: "февр.", 3: "марта", 4: "апр.",
    5: "мая", 6: "июня", 7: "июля", 8: "авг.",
    9: "сент.", 10: "окт.", 11: "нояб.", 12: "дек.",
}

TIME_SLOTS = {
    1: "08:00 - 09:20",
    2: "09:30 - 10:50",
    3: "11:00 - 12:20",
    4: "12:50 - 14:10",
    5: "14:20 - 15:40",
}

PRESET_SUBJECTS = [
    "ЕГРН",
    "Кадастр. стоим.",
    "Мониторинг земель",
    "Здания и соор.",
    "Регулир. отнош.",
    "Охрана окруж. среды",
    "Ин. яз. в проф. деят.",
]

PRESET_TEACHERS = [
    "Козулина Л.М.",
    "Клюева Е.И.",
    "Седельникова Л.В.",
    "Отмахова С.В.",
]

DEFAULT_SCHEDULE = {
    "mon": [],
    "tue": [
        {"num": 1, "time": "08:00 - 09:20", "subject": "Ин. яз. в проф. деят.", "teacher": "Отмахова С.В.", "room": "Дистанционно"},
        {"num": 2, "time": "09:30 - 10:50", "subject": "Мониторинг земель", "teacher": "Козулина Л.М.", "room": "Дистанционно"},
        {"num": 3, "time": "11:00 - 12:20", "subject": "ЕГРН", "teacher": "Козулина Л.М.", "room": "Дистанционно"},
        {"num": 4, "time": "12:50 - 14:10", "subject": "ЕГРН", "teacher": "Козулина Л.М.", "room": "Дистанционно"}
    ],
    "wed": [
        {"num": 1, "time": "08:00 - 09:20", "subject": "ЕГРН", "teacher": "Козулина Л.М.", "room": "Дистанционно"},
        {"num": 2, "time": "09:30 - 10:50", "subject": "Кадастр. стоим.", "teacher": "Козулина Л.М.", "room": "Дистанционно"},
        {"num": 3, "time": "11:00 - 12:20", "subject": "Кадастр. стоим.", "teacher": "Козулина Л.М.", "room": "Дистанционно"}
    ],
    "thu": [
        {"num": 1, "time": "08:00 - 09:20", "subject": "Здания и соор.", "teacher": "Седельникова Л.В.", "room": "Дистанционно"},
        {"num": 2, "time": "09:30 - 10:50", "subject": "Регулир. отнош.", "teacher": "Клюева Е.И.", "room": "Дистанционно"},
        {"num": 3, "time": "11:00 - 12:20", "subject": "Охрана окруж. среды", "teacher": "Клюева Е.И.", "room": "Дистанционно"},
        {"num": 4, "time": "12:50 - 14:10", "subject": "Кадастр. стоим.", "teacher": "Козулина Л.М.", "room": "Дистанционно"}
    ],
    "fri": [
        {"num": 1, "time": "08:00 - 09:20", "subject": "Здания и соор.", "teacher": "Седельникова Л.В.", "room": "Дистанционно"},
        {"num": 2, "time": "09:30 - 10:50", "subject": "Регулир. отнош.", "teacher": "Клюева Е.И.", "room": "Дистанционно"},
        {"num": 3, "time": "11:00 - 12:20", "subject": "Регулир. отнош.", "teacher": "Клюева Е.И.", "room": "Дистанционно"}
    ],
    "sat": []
}

class AdminAuth(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()

class AdminInteractiveEdit(StatesGroup):
    waiting_custom_subject = State()
    waiting_custom_teacher = State()
    waiting_room = State()
    waiting_quick_room = State()

# ================= ХРАНИЛИЩЕ ДАННЫХ =================

def load_subscribers() -> set:
    if not SUBSCRIBERS_FILE.exists():
        return set()
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()

def register_chat_for_broadcast(chat_id: int):
    subs = load_subscribers()
    if chat_id not in subs:
        subs.add(chat_id)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subs), f)

def get_target_date_for_day(day_code: str) -> datetime.date:
    today = datetime.now().date()
    if today.weekday() == 6:
        monday = today + timedelta(days=1)
    else:
        monday = today - timedelta(days=today.weekday())
    day_offset = DAYS_MAP[day_code][1]
    return monday + timedelta(days=day_offset)

def format_date_str(date_obj: datetime.date) -> str:
    month_name = MONTHS_RU[date_obj.month]
    return f"{date_obj.day} {month_name}"

def load_schedule():
    if not SCHEDULE_FILE.exists():
        save_schedule(DEFAULT_SCHEDULE)
        return DEFAULT_SCHEDULE
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not any(data.get(k) for k in ["tue", "wed", "thu", "fri"]):
                save_schedule(DEFAULT_SCHEDULE)
                return DEFAULT_SCHEDULE
            return data
    except Exception:
        save_schedule(DEFAULT_SCHEDULE)
        return DEFAULT_SCHEDULE

def save_schedule(data):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_schedule_keyboard():
    buttons = []
    row1 = []
    for code in ["mon", "tue", "wed"]:
        d = get_target_date_for_day(code)
        label = f"{RU_DAY_NAMES[code]} ({d.day})"
        row1.append(InlineKeyboardButton(text=label, callback_data=f"day_{code}"))

    row2 = []
    for code in ["thu", "fri", "sat"]:
        d = get_target_date_for_day(code)
        label = f"{RU_DAY_NAMES[code]} ({d.day})"
        row2.append(InlineKeyboardButton(text=label, callback_data=f"day_{code}"))

    buttons.append(row1)
    buttons.append(row2)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_schedule_text(day_code: str) -> str:
    schedule = load_schedule()
    lessons = sorted(schedule.get(day_code, []), key=lambda x: x["num"])
    day_name, _ = DAYS_MAP[day_code]
    date_str = format_date_str(get_target_date_for_day(day_code))

    if not lessons:
        return f"📅 <b>{day_name}, {date_str}</b>\n\n🎉 В этот день пар нет, выходной!"

    text = f"📅 <b>Расписание на {day_name} ({date_str}):</b>\n\n"
    for l in lessons:
        room_info = l.get("room", "Дистанционно")
        text += (
            f"<b>Пара {l['num']}: {l['subject']}</b>\n"
            f"⏰ Время: {l['time']}\n"
            f"👤 Преподаватель: {l['teacher']}\n"
            f"📍 Кабинет: <b>{room_info}</b>\n\n"
        )
    return text

# ================= АВТО-РАССЫЛКА (С ЗАЩИТОЙ ОТ ОШИБОК) =================

async def daily_morning_broadcast():
    now_irk = datetime.now()
    weekday = now_irk.weekday()

    if weekday not in WEEKDAY_TO_CODE:
        return

    day_code = WEEKDAY_TO_CODE[weekday]
    text = f"🌅 <b>Доброе утро! Расписание на сегодня:</b>\n\n" + format_schedule_text(day_code)
    
    subs = load_subscribers()
    dead_subs = set()

    for chat_id in list(subs):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_schedule_keyboard()
            )
            await asyncio.sleep(0.05)
        except (TelegramForbiddenError, TelegramBadRequest):
            dead_subs.add(chat_id)
        except Exception:
            pass

    if dead_subs:
        subs.difference_update(dead_subs)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subs), f)

# ================= ОБЩИЙ ДОСТУП =================

@dp.message(CommandStart())
@dp.message(Command("rasp"))
async def cmd_schedule(message: Message):
    register_chat_for_broadcast(message.chat.id)
    await message.answer(
        "📅 Выберите день недели для просмотра расписания:",
        reply_markup=get_schedule_keyboard(),
    )

@dp.callback_query(F.data.startswith("day_"))
async def cb_show_day(call: CallbackQuery):
    day_code = call.data.replace("day_", "")
    text = format_schedule_text(day_code)
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_schedule_keyboard(),
        )
    except Exception:
        pass
    await call.answer()

# ================= АДМИН-ПАНЕЛЬ =================

@dp.message(Command("admin"), F.chat.type != ChatType.PRIVATE)
async def admin_in_group(message: Message):
    await message.reply("⚠️ Доступ в админ-панель возможен только в личных сообщениях с ботом.")

@dp.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def admin_entry(message: Message, state: FSMContext):
    if message.from_user.id in authenticated_admins:
        await show_admin_main(message)
        return
    await state.set_state(AdminAuth.waiting_for_login)
    await message.answer("🔒 <b>Вход в панель администратора</b>\nВведите логин:", parse_mode="HTML")

@dp.message(AdminAuth.waiting_for_login)
async def process_admin_login(message: Message, state: FSMContext):
    if message.text.strip() == ADMIN_LOGIN:
        await state.set_state(AdminAuth.waiting_for_password)
        await message.answer("🔑 Введите пароль:")
    else:
        await message.answer("❌ Неверный логин. Попробуйте еще раз:")

@dp.message(AdminAuth.waiting_for_password)
async def process_admin_password(message: Message, state: FSMContext):
    if message.text.strip() == ADMIN_PASSWORD:
        authenticated_admins.add(message.from_user.id)
        await state.clear()
        await message.answer("✅ Авторизация успешна!")
        await show_admin_main(message)
    else:
        await message.answer("❌ Неверный пароль. Попробуйте еще раз:")

async def show_admin_main(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Управление расписанием и кабинетами", callback_data="adm_pick_day")],
            [InlineKeyboardButton(text="📢 Разослать расписание на день", callback_data="adm_broadcast_menu")],
            [InlineKeyboardButton(text="🚪 Выйти из сессии", callback_data="adm_logout")],
        ]
    )
    await message.answer("🛠 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "adm_logout")
async def cb_admin_logout(call: CallbackQuery):
    authenticated_admins.discard(call.from_user.id)
    await call.message.edit_text("🚪 Вы успешно вышли из админки.")
    await call.answer()

@dp.callback_query(F.data == "adm_broadcast_menu")
async def cb_broadcast_menu(call: CallbackQuery):
    if call.from_user.id not in authenticated_admins:
        return await call.answer("Нет доступа", show_alert=True)

    buttons = [
        [
            InlineKeyboardButton(text="ПН", callback_data="admbroad_mon"),
            InlineKeyboardButton(text="ВТ", callback_data="admbroad_tue"),
            InlineKeyboardButton(text="СР", callback_data="admbroad_wed"),
        ],
        [
            InlineKeyboardButton(text="ЧТ", callback_data="admbroad_thu"),
            InlineKeyboardButton(text="ПТ", callback_data="admbroad_fri"),
            InlineKeyboardButton(text="СБ", callback_data="admbroad_sat"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back_main")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("📢 Выберите день для принудительной рассылки:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("admbroad_"))
async def cb_do_broadcast(call: CallbackQuery):
    if call.from_user.id not in authenticated_admins:
        return await call.answer("Нет доступа", show_alert=True)

    day_code = call.data.replace("admbroad_", "")
    text = "📢 <b>Внимание! Расписание от администратора:</b>\n\n" + format_schedule_text(day_code)

    subs = load_subscribers()
    sent_count = 0
    fail_count = 0
    dead_subs = set()

    await call.message.edit_text("⏳ Идет рассылка сообщений...")

    for chat_id in list(subs):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_schedule_keyboard(),
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except (TelegramForbiddenError, TelegramBadRequest):
            fail_count += 1
            dead_subs.add(chat_id)
        except Exception:
            fail_count += 1

    if dead_subs:
        subs.difference_update(dead_subs)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subs), f)

    await call.message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Успешно отправлено: <b>{sent_count}</b>\n"
        f"⚠️ Ошибок (заблокировали/удалили бота): <b>{fail_count}</b>",
        parse_mode="HTML",
    )
    await show_admin_main(call.message)
    await call.answer()

@dp.callback_query(F.data == "adm_pick_day")
async def cb_adm_pick_day(call: CallbackQuery):
    if call.from_user.id not in authenticated_admins:
        return await call.answer("Нет доступа", show_alert=True)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="ПН", callback_data="admday_mon"),
                InlineKeyboardButton(text="ВТ", callback_data="admday_tue"),
                InlineKeyboardButton(text="СР", callback_data="admday_wed"),
            ],
            [
                InlineKeyboardButton(text="ЧТ", callback_data="admday_thu"),
                InlineKeyboardButton(text="ПТ", callback_data="admday_fri"),
                InlineKeyboardButton(text="СБ", callback_data="admday_sat"),
            ],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="adm_back_main")],
        ]
    )
    await call.message.edit_text("Выберите день недели для редактирования:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "adm_back_main")
async def cb_back_main(call: CallbackQuery):
    await show_admin_main(call.message)
    await call.answer()

@dp.callback_query(F.data.startswith("admday_"))
async def cb_adm_day_chosen(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in authenticated_admins:
        return await call.answer("Нет доступа", show_alert=True)

    day_code = call.data.replace("admday_", "")
    await state.update_data(target_day=day_code)

    current_text = format_schedule_text(day_code)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 пара", callback_data="admnum_1"),
                InlineKeyboardButton(text="2 пара", callback_data="admnum_2"),
                InlineKeyboardButton(text="3 пара", callback_data="admnum_3"),
            ],
            [
                InlineKeyboardButton(text="4 пара", callback_data="admnum_4"),
                InlineKeyboardButton(text="5 пара", callback_data="admnum_5"),
            ],
            [InlineKeyboardButton(text="🗑 Очистить весь день", callback_data="adm_clearday")],
            [InlineKeyboardButton(text="⬅️ Назад к выбору дня", callback_data="adm_pick_day")],
        ]
    )
    await call.message.edit_text(
        f"{current_text}\nВыберите пару для изменения предмета или кабинета:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await call.answer()

@dp.callback_query(F.data == "adm_clearday")
async def cb_adm_clear_day(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    day_code = data.get("target_day")
    schedule = load_schedule()
    schedule[day_code] = []
    save_schedule(schedule)
    await call.answer("Расписание дня очищено!", show_alert=True)
    await cb_adm_pick_day(call)

@dp.callback_query(F.data.startswith("admnum_"))
async def cb_adm_num_chosen(call: CallbackQuery, state: FSMContext):
    num = int(call.data.replace("admnum_", ""))
    await state.update_data(lesson_num=num)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Изменить только кабинет", callback_data="adm_set_room_only")],
            [InlineKeyboardButton(text="🔄 Пересобрать пару полностью", callback_data="adm_rebuild_lesson")],
            [InlineKeyboardButton(text="❌ Удалить эту пару", callback_data="adm_remove_lesson")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back_to_day")],
        ]
    )
    await call.message.edit_text(f"Выбрана <b>пара №{num}</b>. Что сделать?", parse_mode="HTML", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "adm_back_to_day")
async def cb_adm_back_to_day(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    call.data = f"admday_{data['target_day']}"
    await cb_adm_day_chosen(call, state)

@dp.callback_query(F.data == "adm_set_room_only")
async def cb_set_room_only(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminInteractiveEdit.waiting_quick_room)
    await call.message.edit_text(
        "Отправьте в чат новый номер кабинета (например, <code>305</code> или <code>Дистанционно</code>):",
        parse_mode="HTML",
    )
    await call.answer()

@dp.message(AdminInteractiveEdit.waiting_quick_room)
async def process_quick_room(message: Message, state: FSMContext):
    new_room = message.text.strip()
    data = await state.get_data()
    day_code = data["target_day"]
    num = data["lesson_num"]

    schedule = load_schedule()
    lessons = schedule.get(day_code, [])

    found = False
    for l in lessons:
        if l["num"] == num:
            l["room"] = new_room
            found = True
            break

    if not found:
        time_slot = TIME_SLOTS.get(num, "08:00 - 09:20")
        lessons.append({
            "num": num,
            "time": time_slot,
            "subject": "Новый предмет",
            "teacher": "Не указан",
            "room": new_room,
        })

    schedule[day_code] = lessons
    save_schedule(schedule)
    await state.set_state(None)

    await message.answer(f"✅ Для пары №{num} установлен кабинет: <b>{new_room}</b>", parse_mode="HTML")
    await show_admin_main(message)

@dp.callback_query(F.data == "adm_remove_lesson")
async def cb_adm_remove_lesson(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    day_code = data["target_day"]
    num = data["lesson_num"]

    schedule = load_schedule()
    schedule[day_code] = [l for l in schedule.get(day_code, []) if l["num"] != num]
    save_schedule(schedule)

    await call.answer(f"Пара №{num} удалена!", show_alert=True)
    call.data = f"admday_{day_code}"
    await cb_adm_day_chosen(call, state)

@dp.callback_query(F.data == "adm_rebuild_lesson")
async def cb_adm_rebuild(call: CallbackQuery):
    buttons = []
    for subj in PRESET_SUBJECTS:
        buttons.append([InlineKeyboardButton(text=subj, callback_data=f"admsub_{subj}")])
    buttons.append([InlineKeyboardButton(text="✍️ Ввести предмет вручную", callback_data="adm_custom_subject")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Выберите предмет:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "adm_custom_subject")
async def cb_adm_custom_subject(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminInteractiveEdit.waiting_custom_subject)
    await call.message.edit_text("Отправьте название предмета сообщением в чат:")
    await call.answer()

@dp.message(AdminInteractiveEdit.waiting_custom_subject)
async def msg_custom_subject(message: Message, state: FSMContext):
    await state.update_data(lesson_subject=message.text.strip())
    await state.set_state(None)
    await ask_teacher(message, state)

@dp.callback_query(F.data.startswith("admsub_"))
async def cb_adm_preset_subject(call: CallbackQuery, state: FSMContext):
    subj = call.data.replace("admsub_", "")
    await state.update_data(lesson_subject=subj)
    await ask_teacher(call.message, state, edit=True)
    await call.answer()

async def ask_teacher(message: Message, state: FSMContext, edit: bool = False):
    buttons = []
    for teach in PRESET_TEACHERS:
        buttons.append([InlineKeyboardButton(text=teach, callback_data=f"admtea_{teach}")])
    buttons.append([InlineKeyboardButton(text="✍️ Ввести преподавателя вручную", callback_data="adm_custom_teacher")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "Выберите преподавателя:"
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "adm_custom_teacher")
async def cb_adm_custom_teacher(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminInteractiveEdit.waiting_custom_teacher)
    await call.message.edit_text("Отправьте ФИО преподавателя сообщением:")
    await call.answer()

@dp.message(AdminInteractiveEdit.waiting_custom_teacher)
async def msg_custom_teacher(message: Message, state: FSMContext):
    await state.update_data(lesson_teacher=message.text.strip())
    await state.set_state(None)
    await ask_room_choice(message, state)

@dp.callback_query(F.data.startswith("admtea_"))
async def cb_adm_preset_teacher(call: CallbackQuery, state: FSMContext):
    teach = call.data.replace("admtea_", "")
    await state.update_data(lesson_teacher=teach)
    await ask_room_choice(call.message, state, edit=True)
    await call.answer()

async def ask_room_choice(message: Message, state: FSMContext, edit: bool = False):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Дистанционно", callback_data="admroom_Дистанционно")],
            [InlineKeyboardButton(text="✍️ Ввести номер кабинета", callback_data="adm_enter_room_manual")],
        ]
    )
    text = "Где проходит пара?"
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "adm_enter_room_manual")
async def cb_manual_room(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminInteractiveEdit.waiting_room)
    await call.message.edit_text("Отправьте номер кабинета в чат (например: <code>214</code>):", parse_mode="HTML")
    await call.answer()

@dp.message(AdminInteractiveEdit.waiting_room)
async def msg_manual_room(message: Message, state: FSMContext):
    room_name = message.text.strip()
    await state.set_state(None)
    await finalize_lesson(message, state, room_name, is_message=True)

@dp.callback_query(F.data == "admroom_Дистанционно")
async def cb_dist_room(call: CallbackQuery, state: FSMContext):
    await finalize_lesson(call.message, state, "Дистанционно", is_message=False)
    await call.answer("Сохранено!")

async def finalize_lesson(event_target: Message, state: FSMContext, room_name: str, is_message: bool):
    data = await state.get_data()
    day_code = data["target_day"]
    num = data["lesson_num"]
    subj = data["lesson_subject"]
    teach = data["lesson_teacher"]
    time_slot = TIME_SLOTS.get(num, "08:00 - 09:20")

    new_lesson = {
        "num": num,
        "time": time_slot,
        "subject": subj,
        "teacher": teach,
        "room": room_name,
    }

    schedule = load_schedule()
    current_list = [l for l in schedule.get(day_code, []) if l["num"] != num]
    current_list.append(new_lesson)
    schedule[day_code] = current_list
    save_schedule(schedule)

    text = f"✅ Пара №{num} сохранена!\nПредмет: {subj}\nКабинет: {room_name}"
    if is_message:
        await event_target.answer(text)
        await show_admin_main(event_target)
    else:
        await event_target.edit_text(text)
        await show_admin_main(event_target)

# ================= ВЕБ-СЕРВЕР ДЛЯ RENDER И UPTIMEROBOT =================

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/ping", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= ЗАПУСК =================

async def main():
    scheduler.add_job(
        daily_morning_broadcast,
        trigger="cron",
        day_of_week="mon-sat",
        hour=6,
        minute=30,
    )
    scheduler.start()

    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
