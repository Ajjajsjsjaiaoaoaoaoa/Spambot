import asyncio
import os
import random
import string
import json
import threading
import time
import zipfile
import sqlite3
from io import BytesIO
from flask import Flask
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import FloodWaitError, UserBannedInChannelError
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# --- CONFIGURACIÓN GLOBAL ---
api_id = 23720875
api_hash = 'a52aa051d3e737afb9e21fe6b80cc765'
bot_token = '8168761242:AAHTaHR_9UWsVYGBDzNruZ_ZgAd33gYr2-o'
chat_id_aviso = 7296719664
ADMIN_ID = 7296719664

users = {}  # user_id -> {client, mensajes_guardados, excluded_groups, spam_tasks, flood_count, semaphore}

# --- FUNCIONES DE SQLITE ---
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS blacklists (
                    user_id INTEGER PRIMARY KEY,
                    excluded_groups TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
                    user_id INTEGER PRIMARY KEY,
                    session_data TEXT
                )''')
    conn.commit()
    conn.close()

def cargar_datos_usuario(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT excluded_groups FROM blacklists WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        users[user_id]['excluded_groups'] = json.loads(row[0])
    else:
        users[user_id]['excluded_groups'] = []
    conn.close()

def guardar_datos_usuario(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    excluded_groups_json = json.dumps(users[user_id]['excluded_groups'])
    c.execute("INSERT OR REPLACE INTO blacklists (user_id, excluded_groups) VALUES (?, ?)", (user_id, excluded_groups_json))
    conn.commit()
    conn.close()

def guardar_session(user_id, session_data):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO sessions (user_id, session_data) VALUES (?, ?)", (user_id, session_data))
    conn.commit()
    conn.close()

def cargar_session(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT session_data FROM sessions WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

app = Flask(__name__)

@app.route('/')
def ping():
    return "Bot activo"

async def auto_backup(user_id):
    zip_buffer = BytesIO()
    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            if os.path.exists('bot.db'):
                zip_file.write('bot.db')
        zip_buffer.seek(0)
        return zip_buffer
    except:
        zip_buffer.close()
        return None

async def cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "<b>📋 Comandos:</b>\n\n/register - Login con teléfono y código\n/start - Ver mensajes y opciones\n/check_ban - Verificar ban\n/backup - Backup (admin)"
    await update.message.reply_text(msg, parse_mode="HTML")

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo admin.")
        return
    zip_buffer = await auto_backup(user_id)
    if zip_buffer:
        await update.message.reply_document(document=zip_buffer, filename="backup.zip", caption="Backup.")
        zip_buffer.close()

async def check_ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or users[user_id]['client'] is None:
        await update.message.reply_text("No registrado.")
        return
    client = users[user_id]['client']
    try:
        await client.get_entity('@telegram')
        await update.message.reply_text("✅ Cuenta OK.")
    except UserBannedInChannelError:
        await update.message.reply_text("🚨 Cuenta baneada en Telegram.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al chequear: {e}")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in users and users[user_id]['client'] is not None:
        await update.message.reply_text("Ya registrado.")
        return
    if user_id not in users:
        users[user_id] = {'client': None, 'mensajes_guardados': {}, 'excluded_groups': [], 'spam_tasks': {}, 'flood_count': 0, 'semaphore': asyncio.Semaphore(5)}
    await update.message.reply_text("Envíame teléfono (ej: +1234567890):")
    context.user_data["register_step"] = "phone"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or users[user_id]['client'] is None:
        await update.message.reply_text("Regístrate con /register.")
        return
    client = users[user_id]['client']
    mensajes_guardados = users[user_id]['mensajes_guardados']
    mensajes_guardados.clear()
    keyboard = []
    async for msg in client.iter_messages("me", limit=5):
        mid = str(msg.id)
        mensajes_guardados[mid] = msg
        if msg.media:
            if hasattr(msg.media, 'photo'):
                text = "📎 Imagen"
            elif hasattr(msg.media, 'document'):
                text = "📎 Archivo/Video"
            else:
                text = "📎 Medio"
        else:
            text = msg.text or "📎 Sin texto"
        if len(text) > 30:
            text = text[:27] + "..."
        keyboard.append([
            InlineKeyboardButton(f"{text}", callback_data=f"spam_{mid}"),
            InlineKeyboardButton("🕓", callback_data=f"programar_{mid}")
        ])
    keyboard.append([
        InlineKeyboardButton("⛔ Blacklist", callback_data="menu_blacklist"),
        InlineKeyboardButton("🛑 Detener Spam", callback_data="detener_spam")
    ])
    await update.message.reply_text("<b>🟢 Mensajes guardados:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    if user_id not in users or users[user_id]['client'] is None:
        await query.answer("No registrado.")
        return
    await query.answer()
    client = users[user_id]['client']
    mensajes_guardados = users[user_id]['mensajes_guardados']
    excluded_groups = users[user_id]['excluded_groups']
    spam_tasks = users[user_id]['spam_tasks']
    semaphore = users[user_id]['semaphore']

    if data.startswith("spam_"):
        msg_id = data.split("_")[1]
        msg = mensajes_guardados.get(msg_id)
        if not msg:
            await query.edit_message_text("❌ No encontrado.")
            return
        await query.edit_message_text("⏳ Enviando...")
        ok, fail = 0, 0
        start_time = time.time()
        async def send_to_group(dialog):
            nonlocal ok, fail
            async with semaphore:
                if dialog.is_group and dialog.id not in excluded_groups:
                    try:
                        await client.forward_messages(dialog.id, msg.id, "me")
                        ok += 1
                    except FloodWaitError as e:
                        users[user_id]['flood_count'] += 1
                        if users[user_id]['flood_count'] > 3:
                            await client.bot.send_message(chat_id=chat_id_aviso, text=f"🚨 Riesgo ban {user_id}.")
                        await asyncio.sleep(e.seconds + 1)
                        fail += 1
                    except:
                        fail += 1
                    await asyncio.sleep(random.uniform(0.5, 1))
        tasks = []
        async for dialog in client.iter_dialogs():
            if time.time() - start_time > 30:
                break
            tasks.append(send_to_group(dialog))
        await asyncio.gather(*tasks, return_exceptions=True)
        await query.edit_message_text(f"<b>✅ {ok} | ❌ {fail}</b>", parse_mode="HTML")

    elif data.startswith("programar_"):
        msg_id = data.split("_")[1]
        context.user_data["msg_id"] = msg_id
        context.user_data["action"] = "set_interval"
        await query.edit_message_text("<i>🕓 Segundos para reenviar:</i>", parse_mode="HTML")

    elif data == "detener_spam":
        for task in spam_tasks.values():
            task.cancel()
        spam_tasks.clear()
        await query.edit_message_text("<b>🛑 Spam detenido.</b>", parse_mode="HTML")

    elif data == "menu_blacklist":
        keyboard = [
            [InlineKeyboardButton("➕ Agregar", callback_data="bl_add")],
            [InlineKeyboardButton("➖ Quitar", callback_data="bl_remove")],
            [InlineKeyboardButton("📃 Ver", callback_data="bl_view")],
        ]
        await query.edit_message_text("<b>🚫 Blacklist:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data in ["bl_add", "bl_remove"]:
        context.user_data["action"] = data
        await query.edit_message_text("Envíame link del grupo (ej: https://t.me/grupo) o @username:", parse_mode="HTML")

    elif data == "bl_view":
        if not excluded_groups:
            await query.edit_message_text("✅ Vacía.", parse_mode="HTML")
        else:
            await query.edit_message_text("<b>📃 Blacklist:</b>\n" + "\n".join(str(g) for g in excluded_groups), parse_mode="HTML")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    action = context.user_data.get("action")
    register_step = context.user_data.get("register_step")

    if register_step == "phone":
        phone = update.message.text.strip()
        client = TelegramClient(f"{user_id}_session", api_id, api_hash)
        users[user_id]['client'] = client
        try:
            await client.start()  # Conectar primero
            await client.send_code_request(phone)  # Luego enviar código
            await update.message.reply_text("Código enviado. Envía el código de verificación:")
            context.user_data["register_step"] = "code"
            context.user_data["phone"] = phone
        except Exception as e:
            await update.message.reply_text(f"Error enviando código: {e}")
            users[user_id]['client'] = None
            context.user_data.clear()

    elif register_step == "code":
        code = update.message.text.strip()
        phone = context.user_data.get("phone")
        client = users[user_id]['client']
        try:
            await client.sign_in(phone, code)
            cargar_datos_usuario(user_id)
            session_data = client.session.save()
            guardar_session(user_id, session_data)
            await update.message.reply_text("✅ Registrado. Usa /start.")
            context.user_data.clear()
        except Exception as e:
            await update.message.reply_text(f"Error en código: {e}")
            users[user_id]['client'] = None
            context.user_data.clear()

    elif user_id in users and users[user_id]['client'] is not None:
        client = users[user_id]['client']
        mensajes_guardados = users[user_id]['mensajes_guardados']
        excluded_groups = users[user_id]['excluded_groups']
        spam_tasks = users[user_id]['spam_tasks']
        semaphore = users[user_id]['semaphore']

        if action == "set_interval":
            try:
                intervalo = int(update.message.text.strip())
            except:
                await update.message.reply_text("❌ Número inválido.")
                return
            msg_id = context.user_data.get("msg_id")
            msg = mensajes_guardados.get(msg_id)
            if len(spam_tasks) >= 10:
                await update.message.reply_text("❌ Demasiados spams activos.")
                return
            async def spam_loop():
                while True:
                    ok, fail = 0, 0
                    start_time = time.time()
                    async def send_to_group(dialog):
                        nonlocal ok, fail
                        async with semaphore:
                            if dialog.is_group and dialog.id not in excluded_groups:
                                try:
                                    await client.forward_messages(dialog.id, msg.id, "me")
                                    ok += 1
                                except FloodWaitError as e:
                                    users[user_id]['flood_count'] += 1
                                    if users[user_id]['flood_count'] > 3:
                                        await client.bot.send_message(chat_id=chat_id_aviso, text=f"🚨 Riesgo ban {user_id}.")
                                    await asyncio.sleep(e.seconds + 1)
                                    fail += 1
                                except:
                                    fail += 1
                                await asyncio.sleep(random.uniform(0.5, 1))
                    tasks = []
                    async for dialog in client.iter_dialogs():
                        if time.time() - start_time > 30:
                            break
                        tasks.append(send_to_group(dialog))
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await update.message.reply_text(f"<b>🔁 {ok} | {fail}</b>", parse_mode="HTML")
                    await asyncio.sleep(intervalo)
            task = asyncio.create_task(spam_loop())
            spam_tasks[update.message.chat.id] = task
            await update.message.reply_text(f"✅ Programado cada {intervalo}s.", parse_mode="HTML")
            context.user_data.clear()

        elif action in ["bl_add", "bl_remove"]:
            input_text = update.message.text.strip()
            if input_text.startswith("https://t.me/"):
                username = input_text.split("https://t.me/")[1]
            elif input_text.startswith("@"):
                username = input_text[1:]
            else:
                username = input_text
            try:
                entity = await client.get_entity(username)
                gid = entity.id
                if action == "bl_add":
                    if gid not in excluded_groups:
                        excluded_groups.append(gid)
                        guardar_datos_usuario(user_id)
                        await update.message.reply_text("✅ Grupo agregado a blacklist.", parse_mode="HTML")
                    else:
                        await update.message.reply_text("⚠️ Ya está en blacklist.", parse_mode="HTML")
                else:
                    if gid in excluded_groups:
                        excluded_groups.remove(gid)
                        guardar_datos_usuario(user_id)
                        await update.message.reply_text("✅ Grupo eliminado de blacklist.", parse_mode="HTML")
                    else:
                        await update.message.reply_text("⚠️ No está en blacklist.", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: Grupo no encontrado o no accesible. {e}", parse_mode="HTML")
            context.user_data.clear()

async def main():
    init_db()
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM blacklists")
    for row in c.fetchall():
        user_id = row[0]
        users[user_id] = {'client': None, 'mensajes_guardados': {}, 'excluded_groups': [], 'spam_tasks': {}, 'flood_count': 0, 'semaphore': asyncio.Semaphore(5)}
        cargar_datos_usuario(user_id)
    c.execute("SELECT user_id, session_data FROM sessions")
    for row in c.fetchall():
        user_id, session_data = row
        if user_id not in users:
            users[user_id] = {'client': None, 'mensajes_guardados': {}, 'excluded_groups': [], 'spam_tasks': {}, 'flood_count': 0, 'semaphore': asyncio.Semaphore(5)}
        client = TelegramClient(StringSession(session_data), api_id, api_hash)
        users[user_id]['client'] = client
        await client.start()
    conn.close()

    app_flask = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080))
    app_flask.start()

    async def auto_save():
        while True:
            await asyncio.sleep(60)
            for user_id in users:
                guardar_datos_usuario(user_id)
                if users[user_id]['client']:
                    session_data = users[user_id]['client'].session.save()
                    guardar_session(user_id, session_data)

    asyncio.create_task(auto_save())

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("cmds", cmds))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("check_ban", check_ban_command))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    if chat_id_aviso:
        try:
            await app.bot.send_message(chat_id=chat_id_aviso, text="<b>Bot activo ✅</b>", parse_mode="HTML")
        except:
            pass

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for user_id in users:
            guardar_datos_usuario(user_id)
            if users[user_id]['client']:
                session_data = users[user_id]['client'].session.save()
                guardar_session(user_id, session_data)
        if chat_id_aviso:
            try:
                await app.bot.send_message(chat_id=chat_id_aviso, text="<b>Bot inactivo ❌</b>", parse_mode="HTML")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())