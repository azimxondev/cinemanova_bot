import os
import asyncio
import logging
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8899711923:AAFrimd3MF8WWN9R5WalkGeVHrBuBSmfq-M"
ADMIN_ID = 5361309526
DB_NAME = "cinemanova.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- DATABASE SOZLAMALARI ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                title TEXT,
                url TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                code TEXT PRIMARY KEY,
                name TEXT,
                genre TEXT,
                rating TEXT,
                duration TEXT,
                file_id TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                name TEXT,
                season INTEGER,
                episode INTEGER,
                file_id TEXT
            )
        """)
        await db.commit()

# --- FSM STATES ---
class AddMovieState(StatesGroup):
    code = State()
    name = State()
    genre = State()
    rating = State()
    duration = State()
    video = State()

class AddSeriesState(StatesGroup):
    code = State()
    name = State()
    season = State()
    episode = State()
    video = State()

class DeleteContentState(StatesGroup):
    code = State()

class AddChannelState(StatesGroup):
    channel_id = State()
    title = State()
    url = State()

class DeleteChannelState(StatesGroup):
    channel_id = State()

# --- KLAVIATURALAR ---
def get_user_keyboard():
    kb = [
        [KeyboardButton(text="🎬 Barcha Kinolar"), KeyboardButton(text="📺 Barcha Seriallar")],
        [KeyboardButton(text="ℹ️ Qanday qidiriladi?")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard():
    kb = [
        [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="📺 Seriallar")],
        [KeyboardButton(text="➕ Qo'shish"), KeyboardButton(text="🗑 O'chirish")],
        [KeyboardButton(text="📢 Kanal qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📝 Kanallar ro'yxati")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )

# --- MAJBURIY OBUNA TEKSHIRUVI ---
async def check_subscription(user_id: int) -> tuple[bool, list]:
    if user_id == ADMIN_ID:
        return True, []
    
    unsubscribed = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, title, url FROM channels") as cursor:
            channels = await cursor.fetchall()
            for ch_id, title, url in channels:
                try:
                    member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                    if not isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
                        unsubscribed.append((title, url))
                except Exception:
                    unsubscribed.append((title, url))
    return len(unsubscribed) == 0, unsubscribed

def get_sub_inline_kb(channels: list):
    inline_kb = []
    for title, url in channels:
        inline_kb.append([InlineKeyboardButton(text=f"➕ {title}", url=url)])
    inline_kb.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=inline_kb)

# --- START VA ASOSIY MENYU ---
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id == ADMIN_ID:
        await message.answer("Amal bekor qilindi.", reply_markup=get_admin_keyboard())
    else:
        await message.answer("Amal bekor qilindi.", reply_markup=get_user_keyboard())

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer(
            "⚠️ Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
            reply_markup=get_sub_inline_kb(unsub_channels)
        )
        return

    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Assalomu alaykum, Admin! Boshqaruv paneli:", reply_markup=get_admin_keyboard())
    else:
        await message.answer(
            "👋 **CinemaNova botiga xush kelibsiz!**\n\nKino yoki serial kodini yuboring yoki quyidagi tugmalardan birini tanlang.",
            reply_markup=get_user_keyboard(),
            parse_mode="Markdown"
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    is_sub, unsub_channels = await check_subscription(callback.from_user.id)
    if is_sub:
        await callback.message.delete()
        if callback.from_user.id == ADMIN_ID:
            await callback.message.answer("✅ Obuna tasdiqlandi!", reply_markup=get_admin_keyboard())
        else:
            await callback.message.answer("✅ Obuna tasdiqlandi! Kino kodini yuborishingiz mumkin.", reply_markup=get_user_keyboard())
    else:
        await callback.answer("❌ Hamma kanallarga a'zo bo'lmadingiz!", show_alert=True)

# --- USER TUGMALARI ---
@dp.message(F.text == "ℹ️ Qanday qidiriladi?")
async def help_handler(message: types.Message):
    await message.answer(
        "🔎 **Kino qidirish tartibi:**\n\n"
        "1. Shunchaki kino yoki serial kodini (masalan: `10`) botga yuboring.\n"
        "2. Agar kod topilsa, bot sizga kinoni yoki serial qismlari ro'yxatini chiqaradi.\n"
        "3. Kodlarni bilish uchun **🎬 Barcha Kinolar** yoki **📺 Barcha Seriallar** tugmasini bosing.",
        parse_mode="Markdown"
    )

# --- KINOLAR RO'YXATI (HAMMA UCHUN) ---
@dp.message(F.text.in_(["🎬 Kinolar", "🎬 Barcha Kinolar"]))
async def list_movies(message: types.Message):
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT code, name, genre, rating, duration FROM movies") as cursor:
            movies = await cursor.fetchall()
            if not movies:
                await message.answer("Hozircha bazada kinolar mavjud emas.")
                return
            
            text = "🎬 **Mavjud kinolar ro'yxati:**\n\n"
            for code, name, genre, rating, duration in movies:
                text += f"🍿 **{name}**\n├ Janr: {genre}\n├ Reyting: ⭐ {rating}\n├ Vaqti: ⏳ {duration}\n└ Kodi: 🔑 `{code}`\n\n"
            await message.answer(text, parse_mode="Markdown")

# --- SERIALLAR RO'YXATI (HAMMA UCHUN) ---
@dp.message(F.text.in_(["📺 Seriallar", "📺 Barcha Seriallar"]))
async def list_series(message: types.Message):
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT DISTINCT code, name FROM series") as cursor:
            series = await cursor.fetchall()
            if not series:
                await message.answer("Hozircha bazada seriallar mavjud emas.")
                return
            
            text = "📺 **Mavjud seriallar ro'yxati:**\n\n"
            for code, name in series:
                text += f"🔹 **{name}** — Kodi: 🔑 `{code}`\n"
            text += "\n*Qismlarni ko'rish uchun serial kodini chatga yuboring.*"
            await message.answer(text, parse_mode="Markdown")

# --- ADMIN: STATISTIKA ---
@dp.message(F.text == "📊 Statistika", F.from_user.id == ADMIN_ID)
async def stats_handler(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1:
            users_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM movies") as c2:
            movies_count = (await c2.fetchone())[0]
        async with db.execute("SELECT COUNT(DISTINCT code) FROM series") as c3:
            series_count = (await c3.fetchone())[0]
            
    await message.answer(
        f"📊 **Bot statistikasi:**\n\n"
        f"👤 Foydalanuvchilar: {users_count}\n"
        f"🎬 Kinolar soni: {movies_count}\n"
        f"📺 Seriallar soni: {series_count}"
    )

# --- ADMIN: KANALLARNI BOSHQARISH ---
@dp.message(F.text == "📝 Kanallar ro'yxati", F.from_user.id == ADMIN_ID)
async def list_channels(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, title, url FROM channels") as cursor:
            channels = await cursor.fetchall()
            if not channels:
                await message.answer("Majburiy obuna kanallari yo'q.")
                return
            text = "📢 **Ulangan kanallar:**\n\n"
            for ch_id, title, url in channels:
                text += f"🔹 {title} (ID: `{ch_id}`)\n🔗 {url}\n\n"
            await message.answer(text)

@dp.message(F.text == "📢 Kanal qo'shish", F.from_user.id == ADMIN_ID)
async def add_channel_start(message: types.Message, state: FSMContext):
    await state.set_state(AddChannelState.channel_id)
    await message.answer("Kanal ID sini kiriting (masalan: `-100123456789`):\n*Bot kanalda admin bo'lishi shart!*", reply_markup=get_cancel_kb())

@dp.message(AddChannelState.channel_id)
async def add_channel_id(message: types.Message, state: FSMContext):
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AddChannelState.title)
    await message.answer("Kanal nomini kiriting:")

@dp.message(AddChannelState.title)
async def add_channel_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddChannelState.url)
    await message.answer("Kanal havolasini kiriting (masalan: `https://t.me/kanal`):")

@dp.message(AddChannelState.url)
async def add_channel_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    url = message.text.strip()
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO channels (channel_id, title, url) VALUES (?, ?, ?)",
                (data['channel_id'], data['title'], url)
            )
            await db.commit()
        await message.answer("✅ Kanal muvaffaqiyatli qo'shildi!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"Xatolik: {e}", reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "🗑 Kanal o'chirish", F.from_user.id == ADMIN_ID)
async def del_channel_start(message: types.Message, state: FSMContext):
    await state.set_state(DeleteChannelState.channel_id)
    await message.answer("O'chirmoqchi bo'lgan kanal ID sini kiriting:", reply_markup=get_cancel_kb())

@dp.message(DeleteChannelState.channel_id)
async def del_channel_finish(message: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM channels WHERE channel_id = ?", (message.text.strip(),))
        await db.commit()
    await state.clear()
    await message.answer("✅ Kanal o'chirildi!", reply_markup=get_admin_keyboard())

# --- ADMIN: KONTENT QO'SHISH VA O'CHIRISH ---
@dp.message(F.text == "➕ Qo'shish", F.from_user.id == ADMIN_ID)
async def add_choice(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino qo'shish", callback_data="add_type_movie")],
        [InlineKeyboardButton(text="📺 Serial qismi qo'shish", callback_data="add_type_series")]
    ])
    await message.answer("Qaysi birini qo'shmoqchisiz?", reply_markup=kb)

@dp.callback_query(F.data == "add_type_movie")
async def start_add_movie(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddMovieState.code)
    await callback.message.answer("Kino uchun kod kiriting (masalan: `10`):", reply_markup=get_cancel_kb())

@dp.message(AddMovieState.code)
async def step_m_name(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await state.set_state(AddMovieState.name)
    await message.answer("Kino nomini kiriting:")

@dp.message(AddMovieState.name)
async def step_m_genre(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddMovieState.genre)
    await message.answer("Kino janrini kiriting:")

@dp.message(AddMovieState.genre)
async def step_m_rating(message: types.Message, state: FSMContext):
    await state.update_data(genre=message.text.strip())
    await state.set_state(AddMovieState.rating)
    await message.answer("Reytingni kiriting (masalan: `8.6/10`):")

@dp.message(AddMovieState.rating)
async def step_m_dur(message: types.Message, state: FSMContext):
    await state.update_data(rating=message.text.strip())
    await state.set_state(AddMovieState.duration)
    await message.answer("Davomiyligini kiriting:")

@dp.message(AddMovieState.duration)
async def step_m_file(message: types.Message, state: FSMContext):
    await state.update_data(duration=message.text.strip())
    await state.set_state(AddMovieState.video)
    await message.answer("Kino videosini yuboring:")

@dp.message(AddMovieState.video, F.video)
async def finish_add_movie(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO movies (code, name, genre, rating, duration, file_id) VALUES (?, ?, ?, ?, ?, ?)",
            (data['code'], data['name'], data['genre'], data['rating'], data['duration'], message.video.file_id)
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Kino muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == "add_type_series")
async def start_add_series(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddSeriesState.code)
    await callback.message.answer("Serial kodini kiriting (masalan: `mrrobot` yoki `20`):", reply_markup=get_cancel_kb())

@dp.message(AddSeriesState.code)
async def step_s_name(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await state.set_state(AddSeriesState.name)
    await message.answer("Serial nomini kiriting:")

@dp.message(AddSeriesState.name)
async def step_s_season(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddSeriesState.season)
    await message.answer("Fasl (Season) raqamini kiriting:")

@dp.message(AddSeriesState.season)
async def step_s_ep(message: types.Message, state: FSMContext):
    await state.update_data(season=int(message.text.strip()))
    await state.set_state(AddSeriesState.episode)
    await message.answer("Qism (Episode) raqamini kiriting:")

@dp.message(AddSeriesState.episode)
async def step_s_file(message: types.Message, state: FSMContext):
    await state.update_data(episode=int(message.text.strip()))
    await state.set_state(AddSeriesState.video)
    await message.answer("Qism videosini yuboring:")

@dp.message(AddSeriesState.video, F.video)
async def finish_add_series(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO series (code, name, season, episode, file_id) VALUES (?, ?, ?, ?, ?)",
            (data['code'], data['name'], data['season'], data['episode'], message.video.file_id)
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Serial qismi muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🗑 O'chirish", F.from_user.id == ADMIN_ID)
async def delete_content_start(message: types.Message, state: FSMContext):
    await state.set_state(DeleteContentState.code)
    await message.answer("O'chirmoqchi bo'lgan kino yoki serial kodini kiriting:", reply_markup=get_cancel_kb())

@dp.message(DeleteContentState.code)
async def delete_content_finish(message: types.Message, state: FSMContext):
    code = message.text.strip()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM movies WHERE code = ?", (code,))
        await db.execute("DELETE FROM series WHERE code = ?", (code,))
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Kod `{code}` o'chirildi.", reply_markup=get_admin_keyboard())

# --- QIDIRUV (KOD BO'YICHA) ---
@dp.message(F.text)
async def search_handler(message: types.Message):
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Botdan foydalanish uchun kanallarga a'zo bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    code = message.text.strip()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT name, genre, rating, duration, file_id FROM movies WHERE code = ?", (code,)) as cursor:
            movie = await cursor.fetchone()
            if movie:
                name, genre, rating, duration, file_id = movie
                caption = (
                    f"🎬 **{name}**\n\n"
                    f"🎭 Janr: {genre}\n"
                    f"⭐ Reyting: {rating}\n"
                    f"⏳ Davomiyligi: {duration}\n"
                    f"🔑 Kodi: `{code}`"
                )
                await message.answer_video(video=file_id, caption=caption, parse_mode="Markdown")
                return

        async with db.execute("SELECT id, name, season, episode FROM series WHERE code = ? ORDER BY season ASC, episode ASC", (code,)) as cursor:
            episodes = await cursor.fetchall()
            if episodes:
                s_name = episodes[0][1]
                buttons = []
                for ep_id, _, season, ep_num in episodes:
                    buttons.append(InlineKeyboardButton(text=f"S{season} E{ep_num}", callback_data=f"ep_{ep_id}"))
                
                chunked = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
                inline_kb = InlineKeyboardMarkup(inline_keyboard=chunked)
                
                await message.answer(f"📺 **{s_name}** seriali qismlari:\nKerakli qismni tanlang 👇", reply_markup=inline_kb)
                return

    await message.answer("❌ Bu kod bo'yicha hech narsa topilmadi.")

@dp.callback_query(F.data.startswith("ep_"))
async def send_episode(callback: types.CallbackQuery):
    ep_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT name, season, episode, file_id FROM series WHERE id = ?", (ep_id,)) as cursor:
            ep = await cursor.fetchone()
            if ep:
                name, season, episode, file_id = ep
                caption = f"📺 **{name}**\n🔹 {season}-fasl, {episode}-qism"
                await callback.message.answer_video(video=file_id, caption=caption)
                await callback.answer()
            else:
                await callback.answer("Qism topilmadi!", show_alert=True)

# --- WEB SERVER (UPTIMEROBOT UCHUN) ---
async def handle_ping(request):
    return web.Response(text="Bot 24/7 ishlamoqda!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ISHGA TUSHIRISH ---
async def main():
    await init_db()
    await start_web_server()
    print("Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())