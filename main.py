import json
import asyncio
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.errors import ChatAdminRequired

from config import BOT_TOKEN, API_ID, API_HASH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("elite_tratos")

ADMINS_FILE = "admins.json"
TRADE_TTL_MINUTES = 60  # minutos de vida de un trato

# --- Cargar y guardar admins dinámicamente ---
def load_admins():
    try:
        with open(ADMINS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_admins(admins):
    with open(ADMINS_FILE, "w") as f:
        json.dump(admins, f, indent=2)

ADMINS = load_admins()

# --- Iniciar clientes ---
bot = Client("elite_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("elite_user", api_id=API_ID, api_hash=API_HASH)

# Estado de tratos
active_trades = {}  # chat_id -> info

# --- Comando /addadmin ---
@bot.on_message(filters.command("addadmin"))
async def add_admin(client, message: Message):
    if message.chat.type != "private":
        return await message.reply("Este comando solo funciona en privado.")
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply("Uso: /addadmin <nombre> <user_id>")
    name = parts[1]
    try:
        uid = int(parts[2])
    except ValueError:
        return await message.reply("ID inválido.")
    ADMINS[name] = uid
    save_admins(ADMINS)
    await message.reply(f"✅ Admin '{name}' agregado.")

# --- /listadmins ---
@bot.on_message(filters.command("listadmins"))
async def list_admins(client, message: Message):
    if not ADMINS:
        return await message.reply("No hay admins registrados.")
    text = "📋 *Admins registrados:*\n"
    for name, uid in ADMINS.items():
        text += f"• {name} — `{uid}`\n"
    await message.reply(text, parse_mode="markdown")

# --- /start ---
@bot.on_message(filters.command(["start", "menu"]))
async def menu(client, message: Message):
    if not ADMINS:
        return await message.reply("⚠️ No hay admins disponibles.")
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"admin:{uid}")]
        for name, uid in ADMINS.items()
    ]
    await message.reply("👮‍♂️ Elige un admin para tu trato:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Callback al elegir admin ---
@bot.on_callback_query()
async def callback(client, cq):
    data = cq.data
    if data.startswith("admin:"):
        admin_id = int(data.split(":")[1])
        user_id = cq.from_user.id
        await cq.answer("Creando trato...")
        await cq.edit_message_text("🛠️ Preparando grupo del trato...")
        try:
            info = await crear_trato(admin_id, user_id)
            await bot.send_message(user_id, f"✅ Trato creado. Únete aquí: {info['invite_link']}")
            await bot.send_message(admin_id, f"📩 Nuevo trato con [{cq.from_user.first_name}](tg://user?id={user_id}): {info['invite_link']}", parse_mode="markdown")
        except Exception as e:
            await cq.edit_message_text(f"❌ Error: {e}")
            logger.error(e)

# --- Crear grupo de trato ---
async def crear_trato(admin_id: int, user_id: int):
    timestamp = datetime.utcnow().strftime("%H%M%S")
    title = f"Trato-{user_id}-{timestamp}"
    chat = await user.create_group(title, [admin_id, user_id])
    chat_id = chat.id

    # Añadir bot al grupo
    try:
        await user.add_chat_members(chat_id, [ (await bot.get_me()).id ])
    except Exception as e:
        logger.warning(f"No se pudo añadir el bot: {e}")

    link = await user.export_chat_invite_link(chat_id)

    # Guardar trato activo
    active_trades[chat_id] = {
        "creator": user_id,
        "admin": admin_id,
        "created_at": datetime.utcnow(),
        "invite_link": link,
    }

    # Destruir automáticamente después de tiempo
    asyncio.create_task(autodestruir_trato(chat_id))

    return {"chat_id": chat_id, "invite_link": link}

# --- Autodestruir grupo luego de X minutos ---
async def autodestruir_trato(chat_id: int):
    await asyncio.sleep(TRADE_TTL_MINUTES * 60)
    if chat_id in active_trades:
        try:
            await user.delete_chat(chat_id)
            logger.info(f"🗑️ Grupo {chat_id} eliminado automáticamente.")
        except Exception as e:
            logger.warning(f"No se pudo eliminar el grupo {chat_id}: {e}")
        del active_trades[chat_id]

# --- /endtrade ---
@bot.on_message(filters.command("endtrade"))
async def end_trade(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply("Uso: /endtrade <chat_id>")
    chat_id = int(parts[1])
    if chat_id not in active_trades:
        return await message.reply("Ese trato no está activo.")
    try:
        await user.delete_chat(chat_id)
        del active_trades[chat_id]
        await message.reply("🗑️ Trato finalizado y grupo eliminado.")
    except Exception as e:
        await message.reply(f"Error al eliminar: {e}")

# --- Detectar clones por nombre, username o foto (básico) ---
@user.on_chat_member_updated()
async def detecta_clones(client, update):
    chat_id = update.chat.id
    if chat_id not in active_trades:
        return
    user_new = update.new_chat_member.user
    joined = update.new_chat_member.status == "member"
    if joined:
        # Comparar con otros miembros
        chat = await user.get_chat_members(chat_id)
        for m in chat:
            if m.user.id == user_new.id:
                continue
            if m.user.username == user_new.username and user_new.username:
                await client.send_message(chat_id, f"⚠️ Posible clone detectado: {user_new.mention}")
            elif m.user.first_name == user_new.first_name:
                await client.send_message(chat_id, f"⚠️ Nombre idéntico: {user_new.mention}")

# --- Iniciar ambos clientes ---
async def main():
    await user.start()
    await bot.start()
    print("🤖 Bot y 👤 UserBot activos. Esperando comandos...")
    await asyncio.gather(bot.idle(), user.idle())

if __name__ == "__main__":
    asyncio.run(main())