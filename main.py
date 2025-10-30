import logging
from datetime import datetime
import pytz  # Agregado para zonas horarias
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Configura logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Reemplaza con tu token
TOKEN = '8344368928:AAHWVGBOPAu7Q4N5gqphy6FBCl0pmV1wmvU'

# Username del canal (ej. '@jss')
CANAL_ID = '@pzreferencias'

# Lista para almacenar ventas (en memoria)
ventas = []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('¡Hola! Usa /venta <tipo> <cantidad> (ej. /venta diamantes 1166 o /venta pase 1) para registrar. /reenviar para reenviar mensajes, /pedidos para ver ventas. Envía fotos para reenviarlas.')

async def venta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if len(args) < 1 or not args[-1].isdigit():
        await update.message.reply_text('Uso: /venta <tipo> <cantidad> (ej. /venta diamantes 1166 o /venta pase 1). Si no pones tipo, asume diamantes.')
        return
    
    if len(args) == 1:
        # Asume diamantes si solo cantidad
        tipo = 'diamantes'
        cantidad = int(args[0])
    else:
        tipo_input = args[0].lower()
        if tipo_input in ['diamantes', 'diamante']:
            tipo = 'diamantes'
        elif tipo_input in ['pase', 'booyah']:
            tipo = 'pase_booyah'
        else:
            await update.message.reply_text('Tipo inválido. Usa "diamantes" o "pase".')
            return
        cantidad = int(args[1])
    
    # Timestamp con zona horaria de Guadalajara (México Central)
    tz = pytz.timezone('America/Mexico_City')
    timestamp = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
    
    # Guarda la venta
    ventas.append({
        'usuario': user.first_name,
        'tipo': tipo,
        'cantidad': cantidad,
        'fecha_hora': timestamp
    })
    
    await update.message.reply_text(f'Venta realizada: {cantidad} {tipo} por {user.first_name}. Fecha/Hora: {timestamp}')

async def reenviar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Espera el siguiente mensaje para reenviar
    await update.message.reply_text('Envía el mensaje que quieres reenviar al canal.')
    context.user_data['esperando_reenvio'] = True

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('esperando_reenvio'):
        # Reenvía el mensaje al canal
        await context.bot.send_message(chat_id=CANAL_ID, text=update.message.text)
        await update.message.reply_text('Mensaje reenviado al canal.')
        context.user_data['esperando_reenvio'] = False

async def pedidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ventas:
        await update.message.reply_text('No hay ventas registradas.')
        return
    
    registro = 'Registro de ventas:\n'
    for i, v in enumerate(ventas, 1):
        registro += f"{i}. {v['usuario']} - {v['cantidad']} {v['tipo']} - {v['fecha_hora']}\n"
    await update.message.reply_text(registro)

async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        foto = update.message.photo[-1]
        # Usa el caption original del mensaje (puede ser None si no hay)
        caption = update.message.caption
        await context.bot.send_photo(chat_id=CANAL_ID, photo=foto.file_id, caption=caption)
        await update.message.reply_text('Foto reenviada al canal.')
    else:
        await update.message.reply_text('Envía una foto.')

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("venta", venta))
    application.add_handler(CommandHandler("reenviar", reenviar))
    application.add_handler(CommandHandler("pedidos", pedidos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    application.add_handler(MessageHandler(filters.PHOTO, manejar_foto))

    application.run_polling()

if __name__ == '__main__':
    main()