import asyncio
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from cryptography.fernet import Fernet
from config import TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, NAME_UPDATE_COOLDOWN, FEE_PERCENTAGES
from trading import TradingBot
from reporting import send_token_notification, send_mcap_update, generate_pnl_card, generate_portfolio_chart, get_token_status
from solders.keypair import Keypair
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import matplotlib.pyplot as plt
from io import BytesIO
from dotenv import load_dotenv

load_dotenv('t.env')

class TelegramBot:
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.users = {}  # {chat_id: {"private_key": encrypted_key, "bot": TradingBot, "history": {}, "custom_name": str, "last_name_update": float, "portfolio_data": {}, "last_buy_amount": float, "last_token": str, "fee_percentage": float}}
        self.key = Fernet.generate_key()
        self.cipher = Fernet(self.key)
        self.pending_deletions = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        is_owner = chat_id == OWNER_TELEGRAM_ID
        suffix = "Dev⚡" if is_owner else ""
        keyboard = [
            [InlineKeyboardButton("Import Private Key🔐", callback_data="import_key")],
            [InlineKeyboardButton("View Private Key🔐", callback_data="view_key")],
            [InlineKeyboardButton("Delete Private Key🔐", callback_data="delete_key")],
            [InlineKeyboardButton("Buy Token", callback_data="buy")],
            [InlineKeyboardButton("Sell Token", callback_data="sell")],
            [InlineKeyboardButton("Order (Buy/Sell)", callback_data="order")],
            [InlineKeyboardButton("Transfer SOL", callback_data="transfer")],
            [InlineKeyboardButton("View Portfolio", callback_data="portfolio")],
            [InlineKeyboardButton("View Coin Profit", callback_data="coin_profit")],
            [InlineKeyboardButton("Positions", callback_data="positions")],
            [InlineKeyboardButton("Set Custom Name", callback_data="set_name")],
            [InlineKeyboardButton("Portfolio Growth", callback_data="portfolio_growth")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Welcome to Ze King👑 Trading Bot {suffix}!", reply_markup=reply_markup)

    async def buy(self, chat_id, token_address, amount, fee_percentage):
        """Execute a buy order for a token."""
        bot = self.users[chat_id]["bot"]
        fee_percentage = fee_percentage or FEE_PERCENTAGES[0]  # Default to first fee percentage
        success, msg = await bot.buy_token(token_address, amount, fee_percentage=fee_percentage)
        return success, msg

    async def sell(self, chat_id, token_address, amount, fee_percentage):
        """Execute a sell order for a token."""
        bot = self.users[chat_id]["bot"]
        fee_percentage = fee_percentage or FEE_PERCENTAGES[0]
        success, msg, mcap = await bot.sell_token(token_address, amount, fee_percentage=fee_percentage)
        if success:
            await generate_pnl_card(chat_id, token_address, mcap, bot.buy_records, self.app.bot, self.users[chat_id]["history"])
        return success, msg

    async def order(self, chat_id, token_address, amount, price, order_type, percentage, fee_percentage):
        """Set a limit order (buy or sell)."""
        bot = self.users[chat_id]["bot"]
        fee_percentage = fee_percentage or FEE_PERCENTAGES[0]
        success, msg = await bot.set_limit_order(token_address, amount, price, order_type, percentage, fee_percentage=fee_percentage)
        return success, msg

    async def transfer(self, chat_id, amount, destination, fee_percentage):
        """Transfer Solana to another wallet."""
        bot = self.users[chat_id]["bot"]
        fee_percentage = fee_percentage or FEE_PERCENTAGES[0]
        success, msg, tx_hash = await bot.transfer_sol(amount, destination, fee_percentage=fee_percentage)
        if success:
            return success, msg, tx_hash
        return success, msg, None

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        data = query.data

        if data == "import_key":
            await query.message.reply_text("Please send your Solana private key (base58 encoded).")
            context.user_data["state"] = "awaiting_key"
        elif data == "view_key":
            if chat_id in self.users:
                encrypted_key = self.users[chat_id]["private_key"]
                key = self.cipher.decrypt(encrypted_key).decode()
                masked_key = key[:4] + "****" + key[-4:]
                await query.message.reply_text(f"Your private key: {masked_key}")
            else:
                await query.message.reply_text("No private key imported.")
        elif data == "delete_key":
            if chat_id in self.users:
                keyboard = [
                    [InlineKeyboardButton("Yes", callback_data="confirm_delete_yes")],
                    [InlineKeyboardButton("No", callback_data="confirm_delete_no")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Are you sure you want to delete your private key?", reply_markup=reply_markup)
            else:
                await query.message.reply_text("No private key to delete.")
        elif data == "confirm_delete_yes":
            self.pending_deletions[chat_id] = True
            await query.message.reply_text("Type 'DELETE PRIVATE KEY🔐' to confirm deletion.")
        elif data == "confirm_delete_no":
            await query.message.reply_text("Deletion cancelled.")
        elif data in ["buy", "sell", "order", "transfer", "portfolio", "coin_profit", "positions", "set_name", "portfolio_growth"]:
            if chat_id not in self.users:
                await query.message.reply_text("Please import a private key first.")
                return
            context.user_data["state"] = data
            if data == "buy":
                await query.message.reply_text("Enter token address and amount (e.g., <address> <amount> [<fee_percentage>]).")
            elif data == "sell":
                await query.message.reply_text("Enter token address and amount (e.g., <address> <amount> [<fee_percentage>]).")
            elif data == "order":
                await query.message.reply_text("Enter token address, amount, price, type, percentage (e.g., <address> <amount> <price> <buy/sell> <100|50|25|<custom%>> [<fee_percentage>]).")
            elif data == "transfer":
                await query.message.reply_text("Enter amount and destination (e.g., <amount> <address> [<fee_percentage>]).")
            elif data == "portfolio":
                await self.show_portfolio(chat_id, query.message)
            elif data == "coin_profit":
                await query.message.reply_text("Enter token address to view profit.")
            elif data == "positions":
                await self.show_positions(chat_id, query.message)
            elif data == "set_name":
                await query.message.reply_text("Enter your custom name (with emojis, updatable every 14 days).")
            elif data == "portfolio_growth":
                keyboard = [
                    [InlineKeyboardButton("This Month", callback_data="growth_month")],
                    [InlineKeyboardButton("Last Month", callback_data="growth_last_month")],
                    [InlineKeyboardButton("Last 3 Months", callback_data="growth_3_months")],
                    [InlineKeyboardButton("Last 6 Months", callback_data="growth_6_months")],
                    [InlineKeyboardButton("1 Year", callback_data="growth_year")],
                    [InlineKeyboardButton("Custom Date", callback_data="growth_custom")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Select portfolio growth period:", reply_markup=reply_markup)
        elif data.startswith("refresh_buy_"):
            token = data.split("_")[2]
            status = await get_token_status(chat_id, token, self.users[chat_id]["bot"])
            if status:
                coin_name, mcap, _ = status
                keyboard = [
                    [InlineKeyboardButton("Refresh", callback_data=f"refresh_buy_{token}")],
                    [InlineKeyboardButton("Custom Amount", callback_data=f"custom_buy_{token}")],
                    [InlineKeyboardButton("Buy", callback_data=f"buy_now_{token}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nEnter SOL amount to buy:", reply_markup=reply_markup)
        elif data.startswith("refresh_sell_"):
            token = data.split("_")[2]
            status = await get_token_status(chat_id, token, self.users[chat_id]["bot"])
            if status:
                coin_name, mcap, profit = status
                emoji = "🟩" if profit > 0 else "🟥"
                keyboard = [
                    [InlineKeyboardButton("Refresh", callback_data=f"refresh_sell_{token}")],
                    [InlineKeyboardButton("25%", callback_data=f"sell_25_{token}"),
                     InlineKeyboardButton("50%", callback_data=f"sell_50_{token}"),
                     InlineKeyboardButton("100%", callback_data=f"sell_100_{token}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nProfit: {profit:.2f}% {emoji}", reply_markup=reply_markup)
        elif data.startswith("custom_buy_"):
            token = data.split("_")[2]
            last_amount = self.users[chat_id].get("last_buy_amount", 0.1)
            await query.message.reply_text(f"Enter custom SOL amount for {token} (default: {last_amount} ◎):")
            context.user_data["state"] = f"custom_buy_{token}"
        elif data.startswith("buy_now_"):
            token = data.split("_")[2]
            amount = self.users[chat_id].get("last_buy_amount", 0.1)
            fee_percentage = self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
            success, msg = await self.buy(chat_id, token, amount, fee_percentage)
            await query.message.reply_text(msg)
        elif data.startswith("sell_"):
            parts = data.split("_")
            percentage = float(parts[1])
            token = parts[2]
            status = await get_token_status(chat_id, token, self.users[chat_id]["bot"])
            if status:
                _, _, profit = status
                holdings = next((r["amount"] for r in self.users[chat_id]["bot"].buy_records if r["token_address"] == token and r["sell_mcap"] is None), 0)
                sell_amount = holdings * (percentage / 100) if percentage < 100 else holdings
                fee_percentage = self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
                success, msg = await self.sell(chat_id, token, sell_amount, fee_percentage)
                await query.message.reply_text(msg)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        text = update.message.text
        state = context.user_data.get("state")

        if state == "awaiting_key":
            try:
                Keypair.from_base58_string(text)
                encrypted_key = self.cipher.encrypt(text.encode())
                self.users[chat_id] = {
                    "private_key": encrypted_key,
                    "bot": TradingBot(text),
                    "history": {},
                    "custom_name": f"Ze King👑 {chat_id}",
                    "last_name_update": time.time(),
                    "portfolio_data": {"start_time": time.time(), "growth": [1.0], "timestamps": [time.time()]},
                    "last_buy_amount": 0.1,
                    "last_token": None,
                    "fee_percentage": FEE_PERCENTAGES[0]  # Default fee percentage
                }
                await update.message.reply_text("Private key imported successfully.")
            except Exception:
                await update.message.reply_text("Invalid private key.")
            context.user_data["state"] = None
        elif chat_id in self.pending_deletions and text == "DELETE PRIVATE KEY🔐":
            del self.users[chat_id]
            del self.pending_deletions[chat_id]
            await update.message.reply_text("Private key deleted permanently.")
        elif state in ["buy", "sell", "order", "transfer", "coin_profit", "positions", "set_name"]:
            bot = self.users[chat_id]["bot"]
            parts = text.split()
            try:
                if state == "buy" and len(parts) in [2, 3]:
                    token, amount = parts[0], float(parts[1])
                    fee_percentage = float(parts[2]) if len(parts) == 3 and float(parts[2]) in FEE_PERCENTAGES else self.users[chat_id]["fee_percentage"]
                    self.users[chat_id]["last_token"] = token
                    self.users[chat_id]["last_buy_amount"] = amount
                    status = await get_token_status(chat_id, token, bot)
                    if status:
                        coin_name, mcap, _ = status
                        keyboard = [
                            [InlineKeyboardButton("Refresh", callback_data=f"refresh_buy_{token}")],
                            [InlineKeyboardButton("Custom Amount", callback_data=f"custom_buy_{token}")],
                            [InlineKeyboardButton("Buy", callback_data=f"buy_now_{token}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nBuying {amount} ◎ (Fee: {fee_percentage}%)", reply_markup=reply_markup)
                        success, msg = await self.buy(chat_id, token, amount, fee_percentage)
                        await update.message.reply_text(msg)
                elif state.startswith("custom_buy_"):
                    token = state.split("_")[2]
                    amount = float(text) if text.strip() else self.users[chat_id]["last_buy_amount"]
                    fee_percentage = self.users[chat_id]["fee_percentage"]
                    self.users[chat_id]["last_buy_amount"] = amount
                    status = await get_token_status(chat_id, token, bot)
                    if status:
                        coin_name, mcap, _ = status
                        keyboard = [
                            [InlineKeyboardButton("Refresh", callback_data=f"refresh_buy_{token}")],
                            [InlineKeyboardButton("Buy", callback_data=f"buy_now_{token}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nBuying {amount} ◎ (Fee: {fee_percentage}%)", reply_markup=reply_markup)
                        success, msg = await self.buy(chat_id, token, amount, fee_percentage)
                        await update.message.reply_text(msg)
                elif state == "sell" and len(parts) in [2, 3]:
                    token, amount = parts[0], float(parts[1])
                    fee_percentage = float(parts[2]) if len(parts) == 3 and float(parts[2]) in FEE_PERCENTAGES else self.users[chat_id]["fee_percentage"]
                    self.users[chat_id]["last_token"] = token
                    status = await get_token_status(chat_id, token, bot)
                    if status:
                        coin_name, mcap, profit = status
                        emoji = "🟩" if profit > 0 else "🟥"
                        keyboard = [
                            [InlineKeyboardButton("Refresh", callback_data=f"refresh_sell_{token}")],
                            [InlineKeyboardButton("25%", callback_data=f"sell_25_{token}"),
                             InlineKeyboardButton("50%", callback_data=f"sell_50_{token}"),
                             InlineKeyboardButton("100%", callback_data=f"sell_100_{token}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        holdings = next((r["amount"] for r in bot.buy_records if r["token_address"] == token and r["sell_mcap"] is None), 0)
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nHoldings: {holdings} ◎\nProfit: {profit:.2f}% {emoji} (Fee: {fee_percentage}%)", reply_markup=reply_markup)
                        success, msg = await self.sell(chat_id, token, amount, fee_percentage)
                        await update.message.reply_text(msg)
                elif state == "order" and len(parts) in [5, 6]:
                    token, amount, price, order_type, percentage = parts[0], float(parts[1]), float(parts[2]), parts[3], float(parts[4])
                    fee_percentage = float(parts[5]) if len(parts) == 6 and float(parts[5]) in FEE_PERCENTAGES else self.users[chat_id]["fee_percentage"]
                    if order_type not in ["buy", "sell"] or percentage <= 0 or percentage > 100:
                        await update.message.reply_text("Invalid order type or percentage.")
                        return
                    success, msg = await self.order(chat_id, token, amount, price, order_type, percentage, fee_percentage)
                    await update.message.reply_text(msg)
                elif state == "transfer" and len(parts) in [2, 3]:
                    amount, destination = float(parts[0]), parts[1]
                    fee_percentage = float(parts[2]) if len(parts) == 3 and float(parts[2]) in FEE_PERCENTAGES else self.users[chat_id]["fee_percentage"]
                    success, msg, tx_hash = await self.transfer(chat_id, amount, destination, fee_percentage)
                    if success:
                        await update.message.reply_text(
                            f"{msg} (Fee: {fee_percentage}%)",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/tx/{tx_hash}")]])
                        )
                    else:
                        await update.message.reply_text(msg)
                elif state == "coin_profit" and len(parts) == 1:
                    token = parts[0]
                    await self.show_coin_profit(chat_id, token, update.message)
                elif state == "positions" and len(parts) == 0:
                    await self.show_positions(chat_id, update.message)
                elif state == "set_name" and len(parts) == 1:
                    last_update = self.users[chat_id].get("last_name_update", 0)
                    if time.time() - last_update >= NAME_UPDATE_COOLDOWN:
                        self.users[chat_id]["custom_name"] = text
                        self.users[chat_id]["last_name_update"] = time.time()
                        await update.message.reply_text(f"Custom name updated to: {text}")
                    else:
                        await update.message.reply_text("Name update available only every 14 days.")
                else:
                    await update.message.reply_text("Invalid input format.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            context.user_data["state"] = None

    async def show_