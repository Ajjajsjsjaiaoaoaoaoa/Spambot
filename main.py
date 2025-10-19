import asyncio
import os
import random
import string
import json
import threading
from flask import Flask
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# --- CONFIGURACIÓN GLOBAL ---
api_id = 23720875  # Usado para todos los usuarios
api_hash = 'a52aa051d3e737afb9e21fe6b80cc765'
bot_token = '7362158157:AAG_s5xYCzYtWpc8WjLMlEef38gqnOqaLXk'
chat_id_aviso = 7296719664  # pon tu ID de Telegram si quieres aviso al iniciar/apagar
ADMIN_ID = 7296719664  # Reemplaza con TU user_id (obténlo de @userinfobot)

# Diccionario para usuarios: user_id -> {key, client, mensajes_guardados, excluded_groups, spam_tasks}
users = {}
# Diccionario para keys disponibles: key -> disponible (True/False)
keys = {}

# Flask app para pings
app = Flask(__name__)

@app.route('/')
def ping():
    return "Bot activo"

# --- FUNCIONES DE CARGA/GUARDADO ---
def cargar_datos():
    global keys
    if os.path.exists("keys.json"):
        with open("keys.json", "r") as f:
            keys = json.load(f)

def guardar_datos():
    with open("keys.json", "w") as f:
        json.dump(keys, f)

def cargar_datos_usuario(user_id):
    key = users[user_id]['key']
    blacklist_file = f"{key}_blacklist.json"
    if os.path.exists(blacklist_file):
        with open(blacklist_file, "r") as f:
            users[user_id]['excluded_groups'] = json.load(f)
    else:
        users[user_id]['excluded_groups'] = []

def guardar_datos_usuario(user_id):
    key = users[user_id]['key']
    blacklist_file = f"{key}_blacklist.json"
    with open(blacklist_file, "w") as f:
        json.dump(users[user_id]['excluded_groups'], f)

# --- COMANDO /create_key (Solo Admin) ---
async def create_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo el admin puede crear keys.")
        return
    key = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    keys[key] = True  # Disponible
    guardar_datos()
    await update.message.reply_text(f"Key generada: <code>{key}</code>\nComparte con usuarios para que la reclamen.", parse_mode="HTML")

# --- COMANDO /claim (key) ---
async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in users:
        await update.message.reply_text("Ya tienes una key reclamada.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /claim <key>")
        return
    key = context.args[0]
    if key not in keys or not keys[key]:
        await update.message.reply_text("❌ Key inválida o ya reclamada.")
        return
    users[user_id] = {
        'key': key,
        'client': None,
        'mensajes_guardados': {},
        'excluded_groups': [],
        'spam_tasks': {}
    }
    keys[key] = False  # Reclamada
    guardar_datos()
    await update.message.reply_text("✅ Key reclamada. Ahora usa /register para loguearte.")

# --- COMANDO /register ---
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        await update.message.reply_text("Primero reclama una key con /claim <key>.")
        return
    if users[user_id]['client'] is not None:
        await update.message.reply_text("Ya estás registrado y logueado.")
        return
    await update.message.reply_text("Envíame tu número de teléfono (con código, ej: +1234567890):")
    context.user_data["register_step"] = "phone"

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users or users[user_id]['client'] is None:
        await update.message.reply_text("Primero reclama key con /claim <key> y regístrate con /register.")
        return
    keyboard = [
        [InlineKeyboardButton("📋 𝙑𝙚𝙧 𝙢𝙚𝙣𝙨𝙖𝙟𝙚𝙨 𝙜𝙪𝙖𝙧𝙙𝙖𝙙𝙤𝙨", callback_data="ver_guardados")],
        [InlineKeyboardButton("⛔ 𝘽𝙡𝙖𝙘𝙠𝙡𝙞𝙨𝙩", callback_data="menu_blacklist")],
        [InlineKeyboardButton("🛑 𝘿𝙚𝙩𝙚𝙣𝙚𝙧 𝙨𝙥𝙖𝙢", callback_data="detener_spam")]
    ]
    await update.message.reply_text(
        "<b>🟢 Bienvenido</b>\n<i>Elige una opción:</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- LISTAR MENSAJES GUARDADOS ---
async def mostrar_guardados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        return
    client = users[user_id]['client']
    mensajes_guardados = users[user_id]['mensajes_guardados']
    mensajes_guardados.clear()
    keyboard = []
    async for msg in client.iter_messages("me", limit=10):
        mid = str(msg.id)
        mensajes_guardados[mid] = msg
        text = msg.text or "📎 Sin texto"
        if len(text) > 30:
            text = text[:27] + "..."
        keyboard.append([
            InlineKeyboardButton(f"{text}", callback_data=f"spam_{mid}"),
            InlineKeyboardButton("🕓", callback_data=f"programar_{mid}")
        ])
    await update.callback_query.message.edit_text(
        "<b>📌 Mensajes disponibles:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- CALLBACK ---
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    if user_id not in users or users[user_id]['client'] is None:
        await query.answer("No registrado o no logueado.")
        return
    await query.answer()

    client = users[user_id]['client']
    mensajes_guardados = users[user_id]['mensajes_guardados']
    excluded_groups = users[user_id]['excluded_groups']
    spam_tasks = users[user_id]['spam_tasks']

    if data == "ver_guardados":
        await mostrar_guardados(update, context)

    elif data.startswith("spam_"):
        msg_id = data.split("_")[1]
        msg = mensajes_guardados.get(msg_id)
        if not msg:
            await query.edit_message_text("❌ Mensaje no encontrado.")
            return
        await query.edit_message_text("⏳ Enviando...")
        ok, fail = 0, 0
        async for dialog in client.iter_dialogs():
            if dialog.is_group and dialog.id not in excluded_groups:
                try:
                    await client.forward_messages(dialog.id, msg.id, "me")
                    ok += 1
                    await asyncio.sleep(0.5)
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 1)
                    fail += 1
                except:
                    fail += 1
        await query.edit_message_text(f"<b>✅ Enviados:</b> {ok} | <b>❌ Fallos:</b> {fail}", parse_mode="HTML")

    elif data.startswith("programar_"):
        msg_id = data.split("_")[1]
        context.user_data["msg_id"] = msg_id
        context.user_data["action"] = "set_interval"
        await query.edit_message_text("<i>🕓 ¿Cada cuántos segundos quieres reenviar este mensaje?</i>", parse_mode="HTML")

    elif data == "detener_spam":
        for task in spam_tasks.values():
            task.cancel()
        spam_tasks.clear()
        await query.edit_message_text("<b>🛑 Spam detenido.</b>", parse_mode="HTML")

    elif data == "menu_blacklist":
        keyboard = [
            [InlineKeyboardButton("➕ Agregar grupo", callback_data="bl_add")],
            [InlineKeyboardButton("➖ Quitar grupo", callback_data="bl_remove")],
            [InlineKeyboardButton("📃 Ver blacklist", callback_data="bl_view")],
        ]
        await query.edit_message_text("<b>🚫 Administra la Blacklist:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data in ["bl_add", "bl_remove"]:
        context.user_data["action"] = data
        await query.edit_message_text("✏️ <i>Envíame el @grupo o ID para modificar.</i>", parse_mode="HTML")

    elif data == "bl_view":
        if not excluded_groups:
            await query.edit_message_text("✅ <i>No hay grupos en la blacklist.</i>", parse_mode="HTML")
        else:
            await query.edit_message_text("<b>📃 Blacklist:</b>\n" + "\n".join(str(g) for g in excluded_groups), parse_mode="HTML")

# --- TEXTO DEL USUARIO ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    action = context.user_data.get("action")
    register_step = context.user_data.get("register_step")

    if register_step == "phone":
        phone = update.message.text.strip()
        key = users[user_id]['key']
        client = TelegramClient(f"{key}_session", api_id, api_hash)
        users[user_id]['client'] = client
        try:
            await client.start(phone=phone)
            await update.message.reply_text("Envíame el código de verificación que llegó a Telegram:")
            context.user_data["register_step"] = "code"
        except Exception as e:
            await update.message.reply_text(f"Error al iniciar sesión: {e}")
            users[user_id]['client'] = None
            context.user_data.clear()

    elif register_step == "code":
        code = update.message.text.strip()
        client = users[user_id]['client']
        try:
            await client.sign_in(code=code)
            cargar_datos_usuario(user_id)
            await update.message.reply_text("✅ Registrado y logueado exitosamente. Usa /start.")
            context.user_data.clear()
        except Exception as e:
            await update.message.reply_text(f"Error en el código: {e}")
            users[user_id]['client'] = None
            context.user_data.clear()

    elif user_id in users and users[user_id]['client'] is not None:
        client = users[user_id]['client']
        mensajes_guardados = users[user_id]['mensajes_guardados']
        excluded_groups = users[user_id]['excluded_groups']
        spam_tasks = users[user_id]['spam_tasks']

        if action == "set_interval":
            try:
                intervalo = int(update.message.text.strip())
            except:
                await update.message.reply_text("❌ Número inválido.")
                return

            msg_id = context.user_data.get("msg_id")
            msg = mensajes_guardados.get(msg_id)

            async def spam_loop():
                while True:
                    ok, fail = 0, 0
                    async for dialog in client.iter_dialogs():
                        if dialog.is_group and dialog.id not in excluded_groups:
                            try:
                                await client.forward_messages(dialog.id, msg.id, "me")
                                ok += 1
                                await asyncio.sleep(0.5)
                            except FloodWaitError as e:
                                await asyncio.sleep(e.seconds + 1)
                                fail += 1
                            except:
                                fail += 1
                    await update.message.reply_text(f"<b>🔁 Enviado:</b> {ok} | <b>Fallos:</b> {fail}", parse_mode="HTML")
                    await asyncio.sleep(intervalo)

            task = asyncio.create_task(spam_loop())
            spam_tasks[update.message.chat.id] = task
            await update.message.reply_text(f"✅ Reenvío programado cada {intervalo} segundos.", parse_mode="HTML")
            context.user_data.clear()

        elif action in ["bl_add", "bl_remove"]:
            try:
                entity = await client.get_entity(update.message.text.strip())
                gid = entity.id
                if action == "bl_add":
                    if gid not in excluded_groups:
                        excluded_groups.append(gid)
                        guardar_datos_usuario(user_id)
                        await update.message.reply_text("✅ Grupo agregado.", parse_mode="HTML")
                    else:
                        await update.message.reply_text("⚠️ Ya estaba.", parse_mode="HTML")
                else:
                    if gid in excluded_groups:
                        excluded_groups.remove(gid)
                        guardar_datos_usuario(user_id)
                        await update.message.reply_text("✅ Grupo eliminado.", parse_mode="HTML")
                    else:
                        await update.message.reply_text("⚠️ No estaba.", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}", parse_mode="HTML")
            context.user_data.clear()

# --- MAIN ---
async def main():
    cargar_datos()
    app_flask = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080))
    app_flask.start()

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("create_key", create_key))
    app.add_handler(CommandHandler("claim", claim))
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

    # Mantener el bot corriendo
    try:
        await asyncio.Event().wait()  # Espera infinita para mantener el loop
    except KeyboardInterrupt:
        pass
    finally:
        # Guardar datos de todos los usuarios al salir
        for user_id in users:
            guardar_datos_usuario(user_id)
        guardar_datos()
        if chat_id_aviso:
            try:
                await app.bot.send_message(chat_id=chat_id_aviso, text="<b>Bot inactivo ❌</b>", parse_mode="HTML")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
