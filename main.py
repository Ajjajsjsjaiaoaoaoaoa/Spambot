from telethon.sync import TelegramClient, events
import asyncio
import datetime
from flask import Flask
from threading import Thread

# CONFIG
api_id = 23720875  # Tu API ID
api_hash = 'a52aa051d3e737afb9e21fe6b80cc765'  # Tu API HASH
session_name = 'mi_sesion'
grupo_logs = '@logsdelbotspammm'
ARCHIVO_GRUPOS = 'grupos.txt'
inicio = datetime.datetime.now()

client = TelegramClient(session_name, api_id, api_hash)

# FUNCIONES
def cargar_grupos():
    with open(ARCHIVO_GRUPOS, 'r') as f:
        return [line.strip() for line in f if line.strip()]

# COMANDOS
@client.on(events.NewMessage(from_users='me', pattern='/estado'))
async def estado(event):
    grupos = cargar_grupos()
    uptime = str(datetime.datetime.now() - inicio).split('.')[0]
    await event.reply(f"🤖 Bot activo.
⏱ Uptime: {uptime}
📦 {len(grupos)} grupos en grupos.txt")

@client.on(events.NewMessage(from_users='me', pattern='/spam'))
async def spam(event):
    async for msg in client.iter_messages('me', limit=5):
        if msg.fwd_from:
            mensaje = msg
            break
    else:
        await event.reply("⚠️ No encontré mensaje reenviado tuyo.")
        return

    grupos = cargar_grupos()
    enviados_ok = []
    for grupo in grupos:
        try:
            await client.send_message(grupo, mensaje)
            enviados_ok.append(grupo)
            await asyncio.sleep(0.5)
        except:
            pass
    await event.reply(f"✅ Mensaje enviado a {len(enviados_ok)} grupos.")
    log_text = f"📤 Enviado a {len(enviados_ok)} grupos:
" + "\n".join(enviados_ok)
    try:
        await client.send_message(grupo_logs, log_text)
    except:
        pass

@client.on(events.NewMessage(from_users='me', pattern='/botinfo'))
async def botinfo(event):
    uptime = str(datetime.datetime.now() - inicio).split('.')[0]
    await event.reply(f"🤖 *BotInfo:*

"
                      f"📶 Online desde: {uptime}
"
                      f"📝 Sesión: `{session_name}`
"
                      f"🧠 Telethon v{client.__version__}",
                      parse_mode='Markdown')

@client.on(events.NewMessage(from_users='me', pattern='/test'))
async def test_grupo(event):
    partes = event.raw_text.split()
    if len(partes) < 2:
        await event.reply("❌ Usa el comando así: `/test @grupo`", parse_mode='Markdown')
        return
    grupo = partes[1]
    try:
        await client.send_message(grupo, "✅ El bot puede enviar mensajes aquí.")
        await event.reply(f"✅ Mensaje enviado correctamente a {grupo}")
    except:
        await event.reply(f"❌ No se pudo enviar mensaje a {grupo}")

@client.on(events.NewMessage(from_users='me', pattern='/comandos'))
async def comandos(event):
    await event.reply(
        "📜 *Comandos disponibles:*

"
        "🔹 /spam → Reenvía tu último mensaje reenviado a todos los grupos
"
        "🔹 /estado → Muestra estado del bot y cantidad de grupos
"
        "🔹 /botinfo → Info técnica del bot
"
        "🔹 /test @grupo → Prueba si puede enviar a ese grupo
"
        "🔹 /comandos → Muestra esta lista",
        parse_mode='Markdown'
    )

# FLASK
app = Flask('')
@app.route('/')
def home():
    return "✅ Bot activo"

def iniciar_web():
    app.run(host='0.0.0.0', port=8080)

def iniciar_telegram():
    with client:
        client.run_until_disconnected()

if __name__ == '__main__':
    Thread(target=iniciar_web).start()
    Thread(target=iniciar_telegram).start()
