import os
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("relay-bot")

# === Variables de entorno requeridas ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHANNEL_ID = int(os.environ.get("ADMIN_CHANNEL_ID", "0"))  # ej. -1001234567890
# Foto para /start: puede ser un file_id de Telegram o una URL directa (http/https)
START_PHOTO = os.environ.get("START_PHOTO", "").strip()

if not BOT_TOKEN or not ADMIN_CHANNEL_ID:
    raise SystemExit("Faltan BOT_TOKEN y/o ADMIN_CHANNEL_ID.")

# Mapa: message_id_en_canal -> (user_id, user_message_id)
LINK_MAP: Dict[int, Tuple[int, int]] = {}


def identity_block(msg: Message) -> str:
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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    nombre = user.full_name or "amigo"
    caption = f"𝐃𝐈𝐌𝐄 {nombre} ¿𝐂𝐔𝐀𝐋 𝐄𝐒 𝐓𝐔 𝐐𝐔𝐄𝐉𝐀?"

    # Si definiste START_PHOTO (file_id o URL), enviamos foto con el caption.
    if START_PHOTO:
        try:
            await update.effective_message.reply_photo(
                photo=START_PHOTO,
                caption=caption,
            )
            return
        except Exception:
            log.exception("No se pudo enviar la foto de /start; envío texto como respaldo.")

    # Respaldo si no hay START_PHOTO o falló el envío de la imagen
    await update.effective_message.reply_text(caption)


async def relay_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    1) Publica bloque de identidad en el canal.
    2) Copia el mensaje del usuario al canal.
    3) Guarda el vínculo (mensaje en canal) -> (user_id, user_message_id).
    """
    msg = update.effective_message

    # 1) Identidad
    try:
        await context.bot.send_message(
            ADMIN_CHANNEL_ID,
            identity_block(msg),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Error enviando identidad al canal")

    # 2) Copiar contenido del usuario al canal
    try:
        copied: Message = await msg.copy(chat_id=ADMIN_CHANNEL_ID)
        # 3) Enlazar: el mensaje copiado en el canal apunta al autor original
        LINK_MAP[copied.message_id] = (msg.from_user.id, msg.message_id)
    except Exception:
        log.exception("No se pudo copiar el mensaje al canal")
        try:
            await context.bot.send_message(
                ADMIN_CHANNEL_ID,
                "(No se pudo copiar el contenido; arriba está la identidad).",
            )
        except Exception:
            pass


async def reply_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Si alguien responde en el canal (reply) a un mensaje copiado,
    reenviamos esa respuesta al chat del usuario correcto.
    """
    admin_msg = update.effective_message
    ref: Optional[Message] = admin_msg.reply_to_message

    if not ref:
        return  # sólo actuamos en respuestas

    link = LINK_MAP.get(ref.message_id)
    if not link:
        return  # no tenemos ese vínculo (pudo reiniciarse el bot)

    user_id, user_msg_id = link

    try:
        # Si el admin envía medios, copialos
        if admin_msg.effective_attachment or admin_msg.caption:
            await admin_msg.copy(
                chat_id=user_id,
                reply_to_message_id=user_msg_id,  # mantiene hilo en el chat del usuario
            )
        elif admin_msg.text:
            await context.bot.send_message(
                chat_id=user_id,
                text=admin_msg.text_html or admin_msg.text,
                parse_mode=ParseMode.HTML if admin_msg.text_html else None,
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

    # /start
    app.add_handler(CommandHandler("start", cmd_start))

    # Usuarios hablando al bot (privado o donde esté el bot)
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.StatusUpdate.ALL,
            relay_to_channel,
        )
    )

    # Respuestas en el canal de admin → al usuario correcto
    app.add_handler(
        MessageHandler(
            filters.Chat(chat_id=ADMIN_CHANNEL_ID)
            & filters.REPLY
            & ~filters.StatusUpdate.ALL,
            reply_from_channel,
        )
    )

    log.info("Bot listo.")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
