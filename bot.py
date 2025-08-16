import os
import logging
import telegram
from html import escape
from typing import Dict, Tuple, Optional

from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ====== LOGGING & VERSION ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("relay-bot")
print("PTB version:", telegram.__version__)  # Debe mostrar 20.3

# ====== ENV VARS ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "0"))   # ej. -1001234567890

if not BOT_TOKEN or not ADMIN_CHANNEL_ID:
    raise SystemExit("Faltan variables de entorno: BOT_TOKEN y/o ADMIN_CHANNEL_ID.")

# Mapa EN MEMORIA: message_id (en el canal) -> (user_id, user_message_id)
LINK_MAP: Dict[int, Tuple[int, int]] = {}


# ====== HELPERS ======
def identity_block(msg: Message) -> str:
    """Bloque con identidad del remitente para publicar en el canal."""
    u = msg.from_user
    mention = f'<a href="tg://user?id={u.id}">{escape(u.full_name or "Usuario")}</a>'
    username = f"@{escape(u.username)}" if u.username else "—"

    lines = [
        "📥 <b>NUEVO MENSAJE</b>",
        f"👤 <b>Nombre:</b> {mention}",
        f"🔖 <b>Usuario:</b> {username}",
        f"🆔 <b>ID:</b> <code>{u.id}</code>",
    ]
    if msg.text and msg.text != "/start":
        lines.append(f"📝 <b>Texto:</b> {escape(msg.text)}")
    if msg.caption:
        lines.append(f"📝 <b>Caption:</b> {escape(msg.caption)}")
    return "\n".join(lines)


# ====== HANDLERS ======
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde a /start con un mensaje personalizado."""
    user = update.effective_user
    nombre = user.full_name or "amigo"
    caption = f"𝐃𝐈𝐌𝐄 {nombre} ¿𝐂𝐔𝐀𝐋 𝐄𝐒 𝐓𝐔 𝐐𝐔𝐄𝐉𝐀?"
    await update.effective_message.reply_text(caption)


async def relay_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    1) Publica bloque de identidad en el canal.
    2) Copia el contenido del usuario al canal.
    3) Guarda el vínculo: mensaje_en_canal -> (user_id, user_message_id).
    """
    msg = update.effective_message

    # 1) Identidad
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text=identity_block(msg),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Error enviando identidad al canal")

    # 2) Copiar el mensaje al canal
    try:
        copied: Message = await msg.copy(chat_id=ADMIN_CHANNEL_ID)
        # 3) Enlazar el message_id en el canal con el usuario original
        LINK_MAP[copied.message_id] = (msg.from_user.id, msg.message_id)
    except Exception:
        log.exception("No se pudo copiar el mensaje al canal")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHANNEL_ID,
                text="(No se pudo copiar el contenido; arriba está la identidad).",
            )
        except Exception:
            pass


async def reply_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Si alguien responde (reply) en el canal a un mensaje copiado,
    reenviamos esa respuesta al chat del usuario correcto.
    """
    admin_msg = update.effective_message
    ref: Optional[Message] = admin_msg.reply_to_message
    if not ref:
        return  # sólo actuamos en respuestas

    link = LINK_MAP.get(ref.message_id)
    if not link:
        return  # el bot se reinició o no hay registro para ese mensaje

    user_id, user_msg_id = link

    try:
        # Si el admin envía medios o caption, copiamos directamente
        if admin_msg.effective_attachment or admin_msg.caption:
            await admin_msg.copy(
                chat_id=user_id,
                reply_to_message_id=user_msg_id,  # mantiene el hilo en el chat del usuario
            )
        elif admin_msg.text:
            # Reenviar texto tal cual (sin modificar formato)
            await context.bot.send_message(
                chat_id=user_id,
                text=admin_msg.text,
                reply_to_message_id=user_msg_id,
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="(Te enviaron un tipo de mensaje que no puedo reenviar aquí.)",
                reply_to_message_id=user_msg_id,
            )
    except Exception:
        log.exception("Error reenviando respuesta al usuario")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /start (privado con usuarios)
    app.add_handler(CommandHandler("start", cmd_start))

    # Respuestas en el CANAL de admin -> al usuario correcto
    app.add_handler(
        MessageHandler(
            filters.Chat(chat_id=ADMIN_CHANNEL_ID) & filters.REPLY & ~filters.StatusUpdate.ALL,
            reply_from_channel,
        ),
        group=0,
    )

    # Cualquier mensaje que reciba el bot (de usuarios) -> al canal
    app.add_handler(
        MessageHandler(
            ~filters.Chat(chat_id=ADMIN_CHANNEL_ID) & filters.ALL & ~filters.StatusUpdate.ALL,
            relay_to_channel,
        ),
        group=1,
    )

    log.info("Bot listo. Escuchando…")
    app.run_polling(allowed_updates=["message", "channel_post"])


if __name__ == "__main__":
    main()
