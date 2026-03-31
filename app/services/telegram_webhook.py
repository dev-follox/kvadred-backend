import os
import logging

from fastapi import APIRouter, Request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


class TelegramWebhookService:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.router = APIRouter()
        self.setup_routes()

        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set. Telegram notifications will be disabled.")
            self.bot = None
            self.application = None
        else:
            self.bot = Bot(token=self.bot_token)
            self.application = Application.builder().token(self.bot_token).build()
            self.application.add_handler(CommandHandler("start", self.handle_start))
            logger.info("Telegram webhook service initialized")

    async def init_application(self):
        if self.application:
            await self.application.initialize()

    def setup_routes(self):
        @self.router.post("/webhook")
        async def webhook(request: Request):
            if not self.application:
                return {"status": "bot not initialized"}
            try:
                json_data = await request.json()
                update = Update.de_json(json_data, self.application.bot)
                await self.application.process_update(update)
                return {"status": "ok"}
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return {"status": "error", "detail": str(e)}

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = update.effective_user
        welcome_message = (
            "👋 Welcome to Kvadred!\n\n"
            f"Your Chat ID: `{chat_id}`\n\n"
            "To link this bot to your store:\n"
            "1. Copy your Chat ID above\n"
            "2. Go to your store settings in the Kvadred app\n"
            "3. Click 'Link Telegram' and paste your Chat ID\n\n"
            "Once linked, you'll receive notifications for:\n"
            "✅ New orders\n"
            "🔄 Order status updates\n\n"
            "Keep your Chat ID safe!"
        )
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        logger.info(f"Sent welcome to chat_id: {chat_id}, user: {user.first_name}")

    async def set_webhook(self, webhook_url: str) -> bool:
        if not self.bot:
            return False
        try:
            await self.bot.set_webhook(webhook_url)
            logger.info(f"Webhook set to: {webhook_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            return False

    async def send_message(self, chat_id: str, message: str) -> bool:
        if not self.bot:
            logger.warning("Telegram bot not initialized. Message not sent.")
            return False
        try:
            await self.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            logger.info(f"Telegram message sent to chat_id: {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
            return False


telegram_service = TelegramWebhookService()
