from telethon.sync import TelegramClient, events
import asyncio
import datetime
from flask import Flask
from threading import Thread

# 📦 CONFIGURACIÓN
api_id = 12345678  # Tu API ID
api_hash = 'tu_api_hash_aquí'  # Tu API HASH
session_name = 'mi_sesion'
ARCHIVO_GRUPOS = 'grupos.txt'
grupo_logs = '@logsdelbotspammm'  # username o ID del grupo log
inicio = datetime.datetime.now()

client = TelegramClient(session_name, api_id, api_hash)

# 🧠 FUNCIONES
def cargar_grupos():
    with open(ARCHIVO_GRUPOS, 'r') as f:
        return [line.strip() for line in f if line.strip()]

@client.on(events.NewMessage(from_users='me', pattern='/estado'))
async def estado(event):
    grupos = cargar_grupos()
    await event.reply(f"📦 {len(grupos)} grupos en grupos.txt\n🤖 Bot activo y esperando órdenes.")

@client.on(events.NewMessage(from_users='me', pattern='/spam'))
async def activar_spam(event):
    async for msg in client.iter_messages('me', limit=5):
        if msg.fwd_from:
            mensaje_origen = msg
            break
    else:
        await event.reply("⚠️ No encontré mensaje reenviado tuyo.")
        return

    grupos = cargar_grupos()
    if not grupos:
        await event.reply("⚠️ No hay grupos en grupos.txt.")
        return

    await event.reply(f"🚀 Enviando mensaje a {len(grupos)} grupos...")
    enviados_ok, enviados_fail = [], []

    for grupo in grupos:
        try:
            await client.send_message(grupo, mensaje_origen)
            enviados_ok.append(grupo)
            await asyncio.sleep(0.5)
        except Exception as e:
            enviados_fail.append(f"{grupo} → {str(e)}")

    await event.reply(f"✅ Enviado a {len(enviados_ok)} grupos.\n❌ Fallaron {len(enviados_fail)}.")
    log_text = f"📤 LOG SPAM:\n\n✅ Correctos ({len(enviados_ok)}):\n" + \
               "\n".join(enviados_ok) + \
               f"\n\n❌ Fallidos ({len(enviados_fail)}):\n" + \
               "\n".join(enviados_fail) if enviados_fail else "\n(ninguno)"

    try:
        await client.send_message(grupo_logs, log_text)
    except Exception as e:
        print(f"❌ No se pudo enviar log al grupo: {e}")

@client.on(events.NewMessage(from_users='me', pattern=r'/test (.+)'))
async def test_grupo(event):
    grupo = event.pattern_match.group(1)
    try:
        await client.send_message(grupo, "🧪 Test de mensaje desde el bot.")
        await event.reply(f"✅ El mensaje se envió correctamente a {grupo}.")
    except Exception as e:
        await event.reply(f"❌ Falló el envío a {grupo}:\n{e}")

@client.on(events.NewMessage(from_users='me', pattern='/botinfo'))
async def bot_info(event):
    grupos = cargar_grupos()
    uptime = datetime.datetime.now() - inicio
    h, rem = divmod(uptime.seconds, 3600)
    m, s = divmod(rem, 60)
    await event.reply(f"🤖 Bot Info:\n🗂 Grupos: {len(grupos)}\n⏱ Uptime: {h}h {m}m {s}s\n📡 Online")

@client.on(events.NewMessage(from_users='me', pattern='/comandos'))
async def mostrar_comandos(event):
    await event.reply(
        "📜 *Comandos disponibles:*\n\n"
        "🔹 /spam → Reenvía tu último mensaje reenviado a todos los grupos\n"
        "🔹 /estado → Muestra estado del bot y cantidad de grupos\n"
        "🔹 /botinfo → Info técnica del bot\n"
        "🔹 /test @grupo → Prueba si puede enviar a ese grupo\n"
        "🔹 /comandos → Muestra esta lista\n",
        parse_mode='Markdown'
    )

# 🌐 FLASK PARA CRON-JOB / UPTIME ROBOT
app = Flask('')

@app.route('/')
def home():
    return "✅ El bot está activo."

def iniciar_web():
    app.run(host='0.0.0.0', port=8080)

# 🚀 ARRANQUE DEL TELEGRAM CON LOG DE ENCENDIDO
def iniciar_telegram():
    async def run():
        try:
            await client.start()
            fecha = datetime.datetime.now().strftime("%d/%b/%Y - %I:%M %p")
            await client.send_message(grupo_logs, f"✅ *Bot encendido*\n🕒 *Inicio:* {fecha}", parse_mode='Markdown')
            print("✅ Bot encendido correctamente")
            await client.run_until_disconnected()
        except Exception as e:
            print(f"❌ Error al iniciar el bot: {e}")

    asyncio.run(run())

# 🧠 EJECUCIÓN
Thread(target=iniciar_web).start()
Thread(target=iniciar_telegram).start()
