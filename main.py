import os
import asyncio
import logging
import random
from datetime import datetime, timezone
import asyncpg
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
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://username:password@host/dbname")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db_pool = None

# --- DATABASE SOZLAMALARI ---
async def init_db():
    global db_pool
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    db_pool = await asyncpg.create_pool(dsn=db_url)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                channel_id TEXT UNIQUE,
                title TEXT,
                url TEXT
            );
            CREATE TABLE IF NOT EXISTS movies (
                code TEXT PRIMARY KEY,
                name TEXT,
                genre TEXT,
                rating TEXT,
                duration TEXT,
                file_id TEXT,
                file_type TEXT
            );
            CREATE TABLE IF NOT EXISTS series (
                id SERIAL PRIMARY KEY,
                code TEXT,
                name TEXT,
                season INT,
                episode INT,
                file_id TEXT,
                file_type TEXT,
                UNIQUE(code, season, episode)
            );
            CREATE TABLE IF NOT EXISTS movie_ratings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                code TEXT,
                stars INT,
                UNIQUE(user_id, code)
            );
            CREATE TABLE IF NOT EXISTS suggestions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                full_name TEXT,
                message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

# --- FSM STATES ---
class AddMovieState(StatesGroup):
    code = State()
    name = State()
    genre = State()
    rating = State()
    duration = State()
    media = State()

class AddSeriesState(StatesGroup):
    code = State()
    name = State()
    season = State()
    episode = State()
    media = State()

class DeleteContentState(StatesGroup):
    code = State()

class AddChannelState(StatesGroup):
    channel_id = State()
    title = State()
    url = State()

class DeleteChannelState(StatesGroup):
    channel_id = State()

class SuggestionState(StatesGroup):
    text = State()

# --- KLAVIATURALAR ---
def get_user_keyboard():
    kb = [
        [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="📺 Seriallar")],
        [KeyboardButton(text="🎲 Tasodifiy kino"), KeyboardButton(text="🔥 TOP Kinolar")],
        [KeyboardButton(text="💡 Kino / Taklif yuborish"), KeyboardButton(text="ℹ️ Qo'llanma")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard():
    kb = [
        [KeyboardButton(text="🎬 Kinolar"), KeyboardButton(text="📺 Seriallar")],
        [KeyboardButton(text="➕ Qo'shish"), KeyboardButton(text="🗑 O'chirish")],
        [KeyboardButton(text="📢 Kanal qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="💡 Kelgan takliflar")],
        [KeyboardButton(text="📝 Kanallar ro'yxati")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )

def get_rating_inline_kb(code: str):
    kb = [
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate_{code}_1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate_{code}_2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate_{code}_3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate_{code}_4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate_{code}_5")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- MAJBURIY OBUNA TEKSHIRUVI ---
async def check_subscription(user_id: int) -> tuple[bool, list]:
    if user_id == ADMIN_ID:
        return True, []
    
    unsubscribed = []
    async with db_pool.acquire() as conn:
        channels = await conn.fetch("SELECT channel_id, title, url FROM channels")
        for row in channels:
            try:
                member = await bot.get_chat_member(chat_id=row['channel_id'], user_id=user_id)
                if not isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
                    unsubscribed.append((row['title'], row['url']))
            except Exception:
                unsubscribed.append((row['title'], row['url']))
    return len(unsubscribed) == 0, unsubscribed

def get_sub_inline_kb(channels: list):
    inline_kb = []
    for title, url in channels:
        inline_kb.append([InlineKeyboardButton(text=f"➕ {title}", url=url)])
    inline_kb.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=inline_kb)

# --- FOYDALANUVCHINI BAZAGA YOZISH / YANGILASH ---
async def track_user(user: types.User):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, last_active)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                last_active = CURRENT_TIMESTAMP
        """, user.id, user.username, user.full_name)

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
    await track_user(message.from_user)

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
            "👋 **CinemaNova botiga xush kelibsiz!**\n\n"
            "🔍 Tomosha qilmoqchi bo'lgan kino yoki serial kodini yuboring:",
            reply_markup=get_user_keyboard(),
            parse_mode="Markdown"
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    await track_user(callback.from_user)
    is_sub, unsub_channels = await check_subscription(callback.from_user.id)
    if is_sub:
        await callback.message.delete()
        if callback.from_user.id == ADMIN_ID:
            await callback.message.answer("✅ Obuna tasdiqlandi!", reply_markup=get_admin_keyboard())
        else:
            await callback.message.answer("✅ Obuna tasdiqlandi! Kino kodini yuborishingiz mumkin.", reply_markup=get_user_keyboard())
    else:
        await callback.answer("❌ Hamma kanallarga a'zo bo'lmadingiz!", show_alert=True)

# --- USER: TAKLIF VA BUYURTMA YUBORISH ---
@dp.message(F.text == "💡 Kino / Taklif yuborish")
async def suggest_start(message: types.Message, state: FSMContext):
    await state.set_state(SuggestionState.text)
    await message.answer(
        "✍️ Botga qaysi kino yoki serial qo'shilishini xohlaysiz? Yoki o'z taklifingizni yozib qoldiring:",
        reply_markup=get_cancel_kb()
    )

@dp.message(SuggestionState.text)
async def suggest_finish(message: types.Message, state: FSMContext):
    text = message.text.strip()
    u = message.from_user

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO suggestions (user_id, username, full_name, message)
            VALUES ($1, $2, $3, $4)
        """, u.id, u.username, u.full_name, text)

    # Adminga to'g'ridan-to'g'ri bildirishnoma yuborish
    admin_msg = (
        f"💡 **Yangi taklif / buyurtma keldi!**\n\n"
        f"👤 Kimdan: {u.full_name} (@{u.username if u.username else 'yoq'})\n"
        f"🆔 ID: `{u.id}`\n\n"
        f"📝 **Taklif matni:**\n{text}"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception:
        pass

    await state.clear()
    await message.answer("✅ Taklifingiz adminga yetkazildi. Rahmat!", reply_markup=get_user_keyboard())

# --- ADMIN: KELGAN TAKLIFLARNI KO'RISH ---
@dp.message(F.text == "💡 Kelgan takliflar", F.from_user.id == ADMIN_ID)
async def view_suggestions(message: types.Message):
    async with db_pool.acquire() as conn:
        suggestions = await conn.fetch("SELECT full_name, username, message, created_at FROM suggestions ORDER BY id DESC LIMIT 10")
        if not suggestions:
            await message.answer("Hozircha hech qanday taklif kelmagan.")
            return

        text = "💡 **Oxirgi kelgan 10 ta taklif va buyurtmalar:**\n\n"
        for s in suggestions:
            u_tag = f"@{s['username']}" if s['username'] else "username yo'q"
            t_str = s['created_at'].strftime("%d.%m %H:%M")
            text += f"👤 **{s['full_name']}** ({u_tag}) | 🕒 {t_str}\n💬 *{s['message']}*\n────────────────────\n"

        await message.answer(text, parse_mode="Markdown")

# --- ADMIN: KENGAYTIRILGAN STATISTIKA (KUNLIK, HAFTALIK, OYLIK) ---
@dp.message(F.text == "📊 Statistika", F.from_user.id == ADMIN_ID)
async def stats_handler(message: types.Message):
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        daily_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '1 day'")
        weekly_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '7 days'")
        monthly_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '30 days'")
        
        movies_count = await conn.fetchval("SELECT COUNT(*) FROM movies")
        series_count = await conn.fetchval("SELECT COUNT(DISTINCT code) FROM series")
        
        recent_users = await conn.fetch("SELECT full_name, username, last_active FROM users ORDER BY last_active DESC LIMIT 10")

    text = (
        f"📊 **CinemaNova Bot Statistikasi:**\n\n"
        f"👥 **Foydalanuvchilar:**\n"
        f"├ 🟢 Bugun faol: **{daily_users}** ta\n"
        f"├ 📅 Haftalik (7 kun): **{weekly_users}** ta\n"
        f"├ 🗓 Oylik (30 kun): **{monthly_users}** ta\n"
        f"└ 👥 Jami a'zolar: **{total_users}** ta\n\n"
        f"🎬 Kinolar soni: **{movies_count}** ta\n"
        f"📺 Seriallar soni: **{series_count}** ta\n\n"
        f"🕒 **Oxirgi faol bo'lgan 10 ta foydalanuvchi:**\n"
    )

    for u in recent_users:
        uname = f"@{u['username']}" if u['username'] else "username yo'q"
        time_str = u['last_active'].strftime("%d.%m %H:%M")
        text += f"🔹 {u['full_name']} ({uname}) — `{time_str}`\n"

    await message.answer(text, parse_mode="Markdown")

# --- USER TUGMALARI VA QO'LLANMA ---
@dp.message(F.text == "ℹ️ Qo'llanma")
async def info_handler(message: types.Message):
    text = (
        "📖 **CinemaNova Bot Qo'llanmasi:**\n\n"
        "1. **Kino qidirish:** Kinoning kodini (masalan: `1`) yuborsangiz, bot videoni chiqarib beradi.\n"
        "2. **Serial ko'rish:** Serial kodini yuborsangiz, barcha qismlari chiqadi.\n"
        "3. **Baholash:** Kinoni ko'rib bo'lgach, tagidagi ⭐ tugmalar orqali baho berishingiz mumkin.\n"
        "4. **Ro'yxatlar:** **🎬 Kinolar** yoki **📺 Seriallar** tugmasi orqali barcha bazadagi kontentlarni ko'rishingiz mumkin."
    )
    await message.answer(text, parse_mode="Markdown")

# --- KINOLAR RO'YXATI ---
@dp.message(F.text.contains("Kinolar"))
async def list_movies(message: types.Message):
    await track_user(message.from_user)
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with db_pool.acquire() as conn:
        movies = await conn.fetch("SELECT code, name, genre, rating, duration FROM movies ORDER BY code ASC")
        if not movies:
            await message.answer("Hozircha bazada kinolar mavjud emas.")
            return
        
        text = "🎬 **Mavjud kinolar ro'yxati:**\n\n"
        for row in movies:
            text += (
                f"🎬 **{row['name']}**\n"
                f"🎭 Janr: {row['genre']}\n"
                f"⭐ IMDb: {row['rating']}\n"
                f"⏳ Davomiyligi: {row['duration']}\n"
                f"🔑 Kodi: `{row['code']}`\n"
                f"────────────────────\n"
            )
        text += "\n*Tomosha qilish uchun kino kodini yozib yuboring!*"
        await message.answer(text, parse_mode="Markdown")

# --- SERIALLAR RO'YXATI ---
@dp.message(F.text.contains("Seriallar"))
async def list_series(message: types.Message):
    await track_user(message.from_user)
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with db_pool.acquire() as conn:
        query = """
            SELECT code, name, COUNT(id) as total_episodes, MAX(season) as total_seasons 
            FROM series 
            GROUP BY code, name 
            ORDER BY code ASC
        """
        series = await conn.fetch(query)
        if not series:
            await message.answer("Hozircha bazada seriallar mavjud emas.")
            return
        
        text = "📺 **Mavjud seriallar ro'yxati:**\n\n"
        for row in series:
            text += (
                f"📺 **{row['name']}**\n"
                f"📦 Mavsumlar: {row['total_seasons']}-fasl\n"
                f"🎞 Qismlar soni: {row['total_episodes']} ta qism\n"
                f"🔑 Kodi: `{row['code']}`\n"
                f"────────────────────\n"
            )
        text += "\n*Qismlarni tanlash uchun serial kodini chatga yuboring!*"
        await message.answer(text, parse_mode="Markdown")

# --- TASODIFIY KINO VA TOP KINOLAR ---
@dp.message(F.text == "🎲 Tasodifiy kino")
async def random_movie_handler(message: types.Message):
    await track_user(message.from_user)
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with db_pool.acquire() as conn:
        movies = await conn.fetch("SELECT code, name, genre, rating, duration, file_id, file_type FROM movies")
        if not movies:
            await message.answer("Bazada kinolar mavjud emas.")
            return
        
        movie = random.choice(movies)
        caption = (
            f"🎲 **Tasodifiy tanlangan kino:**\n\n"
            f"🎬 **{movie['name']}**\n"
            f"🎭 Janr: {movie['genre']}\n"
            f"⭐ IMDb: {movie['rating']}\n"
            f"⏳ Davomiyligi: {movie['duration']}\n"
            f"🔑 Kodi: `{movie['code']}`\n\n"
            f"👇 *Kinoni baholang:*"
        )
        if movie['file_type'] == "video":
            await message.answer_video(video=movie['file_id'], caption=caption, reply_markup=get_rating_inline_kb(movie['code']), parse_mode="Markdown")
        else:
            await message.answer_document(document=movie['file_id'], caption=caption, reply_markup=get_rating_inline_kb(movie['code']), parse_mode="Markdown")

@dp.message(F.text == "🔥 TOP Kinolar")
async def top_movies_handler(message: types.Message):
    await track_user(message.from_user)
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Avval kanallarga obuna bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    async with db_pool.acquire() as conn:
        query = """
            SELECT m.code, m.name, AVG(r.stars) as avg_rating, COUNT(r.id) as votes
            FROM movies m
            JOIN movie_ratings r ON m.code = r.code
            GROUP BY m.code, m.name
            ORDER BY avg_rating DESC, votes DESC
            LIMIT 10
        """
        top_list = await conn.fetch(query)
        if not top_list:
            await message.answer("🔥 Hozircha baholangan TOP kinolar mavjud emas.")
            return
        
        text = "🔥 **Foydalanuvchilar bahosi bo'yicha TOP kinolar:**\n\n"
        for idx, row in enumerate(top_list, 1):
            text += f"{idx}. **{row['name']}** — ⭐ {float(row['avg_rating']):.1f} ({row['votes']} ta baho) | Kodi: `{row['code']}`\n"
        
        await message.answer(text, parse_mode="Markdown")

# --- RATING CALLBACK ---
@dp.callback_query(F.data.startswith("rate_"))
async def handle_rating(callback: types.CallbackQuery):
    await track_user(callback.from_user)
    parts = callback.data.split("_")
    code = parts[1]
    stars = int(parts[2])
    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO movie_ratings (user_id, code, stars)
            VALUES ($1, $2, $3)
            ON CONFLICT(user_id, code) DO UPDATE SET stars = EXCLUDED.stars
        """, user_id, code, stars)
    
    await callback.answer(f"Rahmat! Ushbu kinoga {stars} ⭐ baho berdingiz.", show_alert=True)

# --- ADMIN: KANALLAR ---
@dp.message(F.text == "📝 Kanallar ro'yxati", F.from_user.id == ADMIN_ID)
async def list_channels(message: types.Message):
    async with db_pool.acquire() as conn:
        channels = await conn.fetch("SELECT channel_id, title, url FROM channels")
        if not channels:
            await message.answer("Majburiy obuna kanallari yo'q.")
            return
        text = "📢 **Ulangan kanallar:**\n\n"
        for row in channels:
            text += f"🔹 {row['title']} (ID: `{row['channel_id']}`)\n🔗 {row['url']}\n\n"
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
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO channels (channel_id, title, url) VALUES ($1, $2, $3)",
                data['channel_id'], data['title'], url
            )
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
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM channels WHERE channel_id = $1", message.text.strip())
    await state.clear()
    await message.answer("✅ Kanal o'chirildi!", reply_markup=get_admin_keyboard())

# --- ADMIN: KONTENT QO'SHISH ---
@dp.message(F.text == "➕ Qo'shish", F.from_user.id == ADMIN_ID)
async def add_choice(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino qo'shish", callback_data="add_type_movie")],
        [InlineKeyboardButton(text="📺 Serial qismi qo'shish", callback_data="add_type_series")]
    ])
    await message.answer("Qaysi birini qo'shmoqchisiz?", reply_markup=kb)

# 1. KINO QO'SHISH
@dp.callback_query(F.data == "add_type_movie")
async def start_add_movie(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddMovieState.code)
    await callback.message.answer("Kino uchun kod kiriting (masalan: `1` yoki `10`):", reply_markup=get_cancel_kb())

@dp.message(AddMovieState.code)
async def step_m_code_check(message: types.Message, state: FSMContext):
    code = message.text.strip().lower()
    
    async with db_pool.acquire() as conn:
        existing_movie = await conn.fetchrow("SELECT name FROM movies WHERE LOWER(code) = $1", code)
        existing_series = await conn.fetchrow("SELECT name FROM series WHERE LOWER(code) = $1", code)

    if existing_movie:
        await message.answer(
            f"⚠️ **Diqqat!** Ushbu `{code}` kodi allaqachon **\"{existing_movie['name']}\"** kinosiga berilgan!\n\n"
            f"Eski kino o'chib ketmasligi uchun boshqa kod kiriting:",
            parse_mode="Markdown"
        )
        return
    
    if existing_series:
        await message.answer(
            f"⚠️ **Diqqat!** Ushbu `{code}` kodi allaqachon **\"{existing_series['name']}\"** serialiga berilgan!\n\n"
            f"Iltimos, boshqa kod kiriting:",
            parse_mode="Markdown"
        )
        return

    await state.update_data(code=code)
    await state.set_state(AddMovieState.name)
    await message.answer("Kino nomini kiriting:")

@dp.message(AddMovieState.name)
async def step_m_genre(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddMovieState.genre)
    await message.answer("Kino janrini kiriting (masalan: `Superhero, Jangari`):")

@dp.message(AddMovieState.genre)
async def step_m_rating(message: types.Message, state: FSMContext):
    await state.update_data(genre=message.text.strip())
    await state.set_state(AddMovieState.rating)
    await message.answer("IMDb reytingini kiriting (masalan: `9.3`):")

@dp.message(AddMovieState.rating)
async def step_m_dur(message: types.Message, state: FSMContext):
    await state.update_data(rating=message.text.strip())
    await state.set_state(AddMovieState.duration)
    await message.answer("Davomiyligini kiriting (masalan: `2 soat 5 minut`):")

@dp.message(AddMovieState.duration)
async def step_m_file(message: types.Message, state: FSMContext):
    await state.update_data(duration=message.text.strip())
    await state.set_state(AddMovieState.media)
    await message.answer("Kino videosi yoki faylini yuboring:")

@dp.message(AddMovieState.media, F.video | F.document)
async def finish_add_movie(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if message.video:
        file_id = message.video.file_id
        file_type = "video"
    else:
        file_id = message.document.file_id
        file_type = "document"

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO movies (code, name, genre, rating, duration, file_id, file_type) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            data['code'], data['name'], data['genre'], data['rating'], data['duration'], file_id, file_type
        )
    
    await state.clear()
    await message.answer(f"✅ **\"{data['name']}\"** kinosi `{data['code']}` kodi bilan saqlandi!", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# 2. SERIAL QISMINI QO'SHISH
@dp.callback_query(F.data == "add_type_series")
async def start_add_series(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddSeriesState.code)
    await callback.message.answer("Serial kodini kiriting (masalan: `mrrobot` yoki `20`):", reply_markup=get_cancel_kb())

@dp.message(AddSeriesState.code)
async def step_s_code_check(message: types.Message, state: FSMContext):
    code = message.text.strip().lower()
    
    async with db_pool.acquire() as conn:
        existing_movie = await conn.fetchrow("SELECT name FROM movies WHERE LOWER(code) = $1", code)
        existing_series = await conn.fetchrow("SELECT name FROM series WHERE LOWER(code) = $1 LIMIT 1", code)

    if existing_movie:
        await message.answer(
            f"⚠️ **Diqqat!** Ushbu `{code}` kodi allaqachon **\"{existing_movie['name']}\"** kinosiga berilgan!\n\n"
            f"Iltimos, serial uchun boshqa kod kiriting:",
            parse_mode="Markdown"
        )
        return

    await state.update_data(code=code)
    
    if existing_series:
        await state.update_data(name=existing_series['name'])
        await state.set_state(AddSeriesState.season)
        await message.answer(f"Ushbu kod **\"{existing_series['name']}\"** serialiga tegishli.\n\nFasl (Season) raqamini kiriting (masalan: `1`):")
    else:
        await state.set_state(AddSeriesState.name)
        await message.answer("Yangi serial nomini kiriting:")

@dp.message(AddSeriesState.name)
async def step_s_season(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddSeriesState.season)
    await message.answer("Fasl (Season) raqamini kiriting (masalan: `1`):")

@dp.message(AddSeriesState.season)
async def step_s_ep(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Iltimos, fasl raqamini faqat son shaklida kiriting (masalan: `1`):")
        return
    
    await state.update_data(season=int(message.text.strip()))
    await state.set_state(AddSeriesState.episode)
    await message.answer("Qism (Episode) raqamini kiriting (masalan: `1`):")

@dp.message(AddSeriesState.episode)
async def step_s_file(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Iltimos, qism raqamini faqat son shaklida kiriting (masalan: `1`):")
        return
    
    episode = int(message.text.strip())
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        exists = await conn.fetchrow(
            "SELECT id FROM series WHERE LOWER(code) = $1 AND season = $2 AND episode = $3",
            data['code'], data['season'], episode
        )
    
    if exists:
        await message.answer(
            f"⚠️ **Diqqat!** Ushbu serialning **{data['season']}-fasl {episode}-qismi** allaqachon mavjud!\n\n"
            f"Boshqa qism raqamini kiriting:",
            parse_mode="Markdown"
        )
        return

    await state.update_data(episode=episode)
    await state.set_state(AddSeriesState.media)
    await message.answer(f"\"{data['name']}\" ({data['season']}-fasl, {episode}-qism) videosi yoki faylini yuboring:")

@dp.message(AddSeriesState.media, F.video | F.document)
async def finish_add_series(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if message.video:
        file_id = message.video.file_id
        file_type = "video"
    else:
        file_id = message.document.file_id
        file_type = "document"

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO series (code, name, season, episode, file_id, file_type) VALUES ($1, $2, $3, $4, $5, $6)",
            data['code'], data['name'], data['season'], data['episode'], file_id, file_type
        )
    
    await state.clear()
    await message.answer(f"✅ **\"{data['name']}\"** ({data['season']}-fasl, {data['episode']}-qism) saqlandi!", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# --- O'CHIRISH ---
@dp.message(F.text == "🗑 O'chirish", F.from_user.id == ADMIN_ID)
async def delete_content_start(message: types.Message, state: FSMContext):
    await state.set_state(DeleteContentState.code)
    await message.answer("O'chirmoqchi bo'lgan kino yoki serial kodini kiriting:", reply_markup=get_cancel_kb())

@dp.message(DeleteContentState.code)
async def delete_content_finish(message: types.Message, state: FSMContext):
    code = message.text.strip().lower()
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM movies WHERE LOWER(code) = $1", code)
        await conn.execute("DELETE FROM series WHERE LOWER(code) = $1", code)
    await state.clear()
    await message.answer(f"✅ `{code}` kodiga tegishli barcha ma'lumotlar o'chirildi.", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

# --- QIDIRUV (KOD BO'YICHA) ---
@dp.message(F.text)
async def search_handler(message: types.Message):
    await track_user(message.from_user)
    is_sub, unsub_channels = await check_subscription(message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Botdan foydalanish uchun kanallarga a'zo bo'ling:", reply_markup=get_sub_inline_kb(unsub_channels))
        return

    code = message.text.strip().lower()
    
    async with db_pool.acquire() as conn:
        # 1. KINOLARDAN IZLASH
        movie = await conn.fetchrow("SELECT name, genre, rating, duration, file_id, file_type FROM movies WHERE LOWER(code) = $1", code)
        if movie:
            r_data = await conn.fetchrow("SELECT AVG(stars) as avg_s, COUNT(id) as cnt FROM movie_ratings WHERE LOWER(code) = $1", code)
            avg_stars = f"{float(r_data['avg_s']):.1f} ⭐ ({r_data['cnt']} ta baho)" if r_data and r_data['avg_s'] else "Hali baholanmagan"

            caption = (
                f"🎬 **{movie['name']}**\n\n"
                f"🎭 Janr: {movie['genre']}\n"
                f"⭐ IMDb: {movie['rating']}\n"
                f"👥 Foydalanuvchilar bahosi: {avg_stars}\n"
                f"⏳ Davomiyligi: {movie['duration']}\n"
                f"🔑 Kodi: `{code}`\n\n"
                f"👇 *Kinoga baho bering:*"
            )
            
            if movie['file_type'] == "video":
                await message.answer_video(video=movie['file_id'], caption=caption, reply_markup=get_rating_inline_kb(code), parse_mode="Markdown")
            else:
                await message.answer_document(document=movie['file_id'], caption=caption, reply_markup=get_rating_inline_kb(code), parse_mode="Markdown")
            return

        # 2. SERIALLARDAN IZLASH
        episodes = await conn.fetch("SELECT id, name, season, episode FROM series WHERE LOWER(code) = $1 ORDER BY season ASC, episode ASC", code)
        if episodes:
            s_name = episodes[0]['name']
            buttons = []
            for row in episodes:
                buttons.append(InlineKeyboardButton(text=f"S{row['season']} E{row['episode']}", callback_data=f"ep_{row['id']}"))
            
            chunked = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
            inline_kb = InlineKeyboardMarkup(inline_keyboard=chunked)
            
            await message.answer(f"📺 **{s_name}** seriali qismlari:\n\nTomosha qilish uchun kerakli qismni tanlang 👇", reply_markup=inline_kb, parse_mode="Markdown")
            return

    await message.answer("❌ Bu kod bo'yicha hech narsa topilmadi.\n\nMavjud filmlarni ko'rish uchun **🎬 Kinolar** yoki **📺 Seriallar** tugmasini bosing.")

@dp.callback_query(F.data.startswith("ep_"))
async def send_episode(callback: types.CallbackQuery):
    await track_user(callback.from_user)
    ep_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ep = await conn.fetchrow("SELECT name, season, episode, file_id, file_type FROM series WHERE id = $1", ep_id)
        if ep:
            caption = f"📺 **{ep['name']}**\n🔹 {ep['season']}-fasl, {ep['episode']}-qism"
            if ep['file_type'] == "video":
                await callback.message.answer_video(video=ep['file_id'], caption=caption, parse_mode="Markdown")
            else:
                await callback.message.answer_document(document=ep['file_id'], caption=caption, parse_mode="Markdown")
            await callback.answer()
        else:
            await callback.answer("Qism topilmadi!", show_alert=True)

# --- WEB SERVER (UPTIMEROBOT UCHUN) ---
async def handle_ping(request):
    return web.Response(text="Bot 24/7 faol ishlamoqda!")

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