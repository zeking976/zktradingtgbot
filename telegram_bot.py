import asyncio
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ContextTypes
from cryptography.fernet import Fernet
from config import TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, NAME_UPDATE_COOLDOWN
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
        self.users = {}  # {chat_id: {"private_key": encrypted_key, "bot": TradingBot, "history": {}, "custom_name": str, "last_name_update": float, "portfolio_data": {}, "last_buy_amount": float, "last_token": str}}
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
            [InlineKeyboardButton("Swap Token", callback_data="swap")],
            [InlineKeyboardButton("Set Limit Order", callback_data="limit_order")],
            [InlineKeyboardButton("Withdraw", callback_data="withdraw")],
            [InlineKeyboardButton("View Portfolio", callback_data="portfolio")],
            [InlineKeyboardButton("View Coin Profit", callback_data="coin_profit")],
            [InlineKeyboardButton("Positions", callback_data="positions")],
            [InlineKeyboardButton("Set Custom Name", callback_data="set_name")],
            [InlineKeyboardButton("Portfolio Growth", callback_data="portfolio_growth")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Welcome to Ze King👑 Trading Bot {suffix}!", reply_markup=reply_markup)

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
        elif data in ["buy", "sell", "swap", "limit_order", "withdraw", "portfolio", "coin_profit", "positions", "set_name", "portfolio_growth"]:
            if chat_id not in self.users:
                await query.message.reply_text("Please import a private key first.")
                return
            context.user_data["state"] = data
            if data == "buy":
                await query.message.reply_text("Enter token address (e.g., <address>).")
            elif data == "sell":
                await query.message.reply_text("Enter token address to sell (e.g., <address>).")
            elif data == "swap":
                await query.message.reply_text("Enter from_token, to_token, amount (e.g., <from> <to> <amount> [buffer] [congestion]).")
            elif data == "limit_order":
                await query.message.reply_text("Enter token address, amount, price, type, percentage (e.g., <address> <amount> <price> <buy/sell> <100|50|25|<custom%>> [buffer] [congestion]).")
            elif data == "withdraw":
                await query.message.reply_text("Enter amount and destination (e.g., <amount> <address> [buffer] [congestion]).")
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
            last_amount = self.users[chat_id].get("last_buy_amount", 0.1)  # Default to 0.1 SOL if none
            await query.message.reply_text(f"Enter custom SOL amount for {token} (default: {last_amount} ◎):")
            context.user_data["state"] = f"custom_buy_{token}"
        elif data.startswith("buy_now_"):
            token = data.split("_")[2]
            amount = self.users[chat_id].get("last_buy_amount", 0.1)
            fee_buffer = None
            fee_congestion = None
            success, msg = await self.users[chat_id]["bot"].buy_token(token, amount, fee_buffer, fee_congestion, False)
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
                fee_buffer = None
                fee_congestion = None
                success, msg, mcap = await self.users[chat_id]["bot"].sell_token(token, sell_amount, fee_buffer, fee_congestion)
                if success and percentage == 100:
                    await generate_pnl_card(chat_id, token, mcap, self.users[chat_id]["bot"].buy_records, self.app.bot, self.users[chat_id]["history"])
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
                    "last_buy_amount": 0.1,  # Default buy amount
                    "last_token": None
                }
                await update.message.reply_text("Private key imported successfully.")
            except Exception:
                await update.message.reply_text("Invalid private key.")
            context.user_data["state"] = None
        elif chat_id in self.pending_deletions and text == "DELETE PRIVATE KEY🔐":
            del self.users[chat_id]
            del self.pending_deletions[chat_id]
            await update.message.reply_text("Private key deleted permanently.")
        elif state in ["buy", "sell", "swap", "limit_order", "withdraw", "coin_profit", "positions", "set_name"]:
            bot = self.users[chat_id]["bot"]
            parts = text.split()
            try:
                if state == "buy" and len(parts) == 1:
                    token = parts[0]
                    self.users[chat_id]["last_token"] = token
                    status = await get_token_status(chat_id, token, bot)
                    if status:
                        coin_name, mcap, _ = status
                        keyboard = [
                            [InlineKeyboardButton("Refresh", callback_data=f"refresh_buy_{token}")],
                            [InlineKeyboardButton("Custom Amount", callback_data=f"custom_buy_{token}")],
                            [InlineKeyboardButton("Buy", callback_data=f"buy_now_{token}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nEnter SOL amount to buy (default: {self.users[chat_id]['last_buy_amount']} ◎):", reply_markup=reply_markup)
                elif state.startswith("custom_buy_"):
                    token = state.split("_")[2]
                    amount = float(text) if text.strip() else self.users[chat_id]["last_buy_amount"]
                    self.users[chat_id]["last_buy_amount"] = amount
                    status = await get_token_status(chat_id, token, bot)
                    if status:
                        coin_name, mcap, _ = status
                        keyboard = [
                            [InlineKeyboardButton("Refresh", callback_data=f"refresh_buy_{token}")],
                            [InlineKeyboardButton("Buy", callback_data=f"buy_now_{token}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nBuying {amount} ◎", reply_markup=reply_markup)
                        success, msg = await bot.buy_token(token, amount, None, None, False)
                        await update.message.reply_text(msg)
                    context.user_data["state"] = None
                elif state == "sell" and len(parts) == 1:
                    token = parts[0]
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
                        await update.message.reply_text(f"Token: {coin_name}\nMCap: ${mcap:,.2f}\nHoldings: {holdings} ◎\nProfit: {profit:.2f}% {emoji}", reply_markup=reply_markup)
                elif state == "swap" and len(parts) in [3, 5]:
                    from_token, to_token, amount = parts[0], parts[1], parts[2]
                    fee_buffer = float(parts[3]) if len(parts) >= 4 else None
                    fee_congestion = float(parts[4]) if len(parts) == 5 else None
                    success, msg = await bot.swap_token(from_token, to_token, amount, fee_buffer, fee_congestion)
                    await update.message.reply_text(msg)
                elif state == "limit_order" and len(parts) in [4, 6]:
                    token, amount, price, order_type = parts[0], parts[1], parts[2], parts[3]
                    percentage = parts[4] if len(parts) >= 5 else "100"
                    percentage = float(percentage) if percentage in ["100", "50", "25"] or (0 < float(percentage) <= 100) else 100.0
                    fee_buffer = float(parts[5]) if len(parts) == 6 else None
                    fee_congestion = float(parts[6]) if len(parts) == 7 else None
                    success, msg = await bot.set_limit_order(token, amount, price, order_type, percentage, fee_buffer, fee_congestion)
                    await update.message.reply_text(msg)
                elif state == "withdraw" and len(parts) in [2, 4]:
                    amount, destination = parts[0], parts[1]
                    fee_buffer = float(parts[2]) if len(parts) >= 3 else None
                    fee_congestion = float(parts[3]) if len(parts) == 4 else None
                    success, msg, tx_hash = await bot.withdraw(amount, destination, fee_buffer, fee_congestion)
                    if success:
                        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/tx/{tx_hash}")]]))
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

    async def show_portfolio(self, chat_id, message):
        """Show portfolio with MCap multiples."""
        bot = self.users[chat_id]["bot"]
        text = "Portfolio:\n\n"
        for record in bot.buy_records:
            token = record["token_address"]
            buy_mcap = record["buy_mcap"]
            current_mcap = await bot.fetch_token_mcap(token)
            multiple = current_mcap / buy_mcap if buy_mcap and current_mcap else 0
            text += f"Token: {await bot.fetch_coin_name(token)}\nMCap Multiple: {multiple:.2f}x\n\n"
        await message.reply_text(text or "No holdings.")

    async def show_coin_profit(self, chat_id, token_address, message):
        """Show profit for a specific coin."""
        bot = self.users[chat_id]["bot"]
        for record in bot.buy_records:
            if record["token_address"] == token_address:
                buy_mcap = record["buy_mcap"]
                current_mcap = await bot.fetch_token_mcap(token_address)
                multiple = current_mcap / buy_mcap if buy_mcap and current_mcap else 0
                await message.reply_text(f"Token: {await bot.fetch_coin_name(token_address)}\nMCap Multiple: {multiple:.2f}x")
                return
        await message.reply_text("Token not found in portfolio.")

    async def show_positions(self, chat_id, message):
        """Show positions with detailed token info."""
        bot = self.users[chat_id]["bot"]
        balance = await bot.client.get_balance(bot.keypair.pubkey())
        sol_balance = balance.value / 1e9
        total_positions = sum(record["amount"] for record in bot.buy_records if record["sell_mcap"] is None)
        positions_usd = total_positions * 150

        text = f"Manage your tokens 1/1⠀— BOT ADDRESS\n"
        text += f"Wallet: {bot.keypair.pubkey()} — BOT ADDRESS ✏️\n"
        text += f"Balance: {sol_balance:.3f} ◎ (${sol_balance * 150:.2f})\n"
        text += f"Positions: {total_positions:.3f} ◎ (${positions_usd:.2f})\n\n"

        for record in bot.buy_records:
            if record["sell_mcap"] is None:
                token = record["token_address"]
                amount = record["amount"]
                buy_mcap = record["buy_mcap"]
                current_mcap = await bot.fetch_token_mcap(token)
                multiple = current_mcap / buy_mcap if buy_mcap and current_mcap else 0
                price = current_mcap / 1e6 if current_mcap else 0
                avg_entry = buy_mcap / 1e6 if buy_mcap else 0
                balance_percent = (amount / sol_balance) * 100 if sol_balance else 0
                usd_value = amount * 150
                pnl_usd = ((current_mcap - buy_mcap) / buy_mcap) * 100 if buy_mcap and current_mcap else 0
                pnl_sol = ((current_mcap - buy_mcap) / 1e9) if buy_mcap and current_mcap else 0

                emoji = "🟩" if pnl_usd > 0 else "🟥"
                text += f"{(await bot.fetch_coin_name(token))[:4]}... - 📈 - {amount:.4f} ◎ (${usd_value:.2f}) [Hide]\n"
                text += f"{await bot.fetch_coin_name(token)}\n"
                text += f"• Price & MC: ${price:.6f} — ${current_mcap:,.2f}\n"
                text += f"• Avg Entry: ${avg_entry:.6f} — ${buy_mcap:,.2f}\n"
                text += f"• Balance: {balance_percent:.3f}% ({amount:.4f})\n"
                text += f"• Buys: {amount:.4f} ◎ (${usd_value:.2f}) • (1 buys)\n"
                text += f"• Sells: N/A • (0 sells)\n"
                text += f"• PNL USD: {pnl_usd:.2f}% ({emoji})\n"
                text += f"• PNL SOL: {pnl_sol:.2f} ◎ ({emoji})\n"
                text += f"PNL Card 🖼️\n\n"
                text += f"💡 Click a token symbol to access the token's sell menu.\n"

        await message.reply_text(text or "No active positions.")

class TelegramBot:
    # ... (other methods like start, button, handle_message, etc.)

    async def test_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test PNL generation by simulating a buy-sell cycle."""
        chat_id = update.effective_chat.id
        if chat_id not in self.users:
            await update.message.reply_text("Please import a private key first.")
            return
        bot = self.users[chat_id]["bot"]
        # Simulate a buy
        token_address = "FakeToken123...XYZ"
        amount = 1.0  # 1 SOL
        success, msg = await bot.buy_token(token_address, amount, manual=True)
        if success:
            await update.message.reply_text(f"Test buy: {msg}")
            # Simulate a sell after a delay
            await asyncio.sleep(2)  # Mimic time passing
            success, msg, mcap = await bot.sell_token(token_address, amount)
            if success:
                await update.message.reply_text(f"Test sell: {msg}")
                # Generate and send PNL card with Gemini API
                from reporting import generate_pnl_card
                buffer = await generate_pnl_card(chat_id, token_address, mcap, bot.buy_records, bot, self.users[chat_id]["history"], self.users)
                if buffer:
                    await self.app.bot.send_photo(chat_id=chat_id, photo=buffer)
            else:
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)

    def run(self):
        """Start the Telegram bot with periodic checks."""
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.button))
        self.app.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_message))
        self.app.add_handler(CommandHandler("testpnl", self.test_pnl))
        asyncio.create_task(self.check_manual_sells_periodically())
        asyncio.create_task(self.check_limit_orders_periodically())
        self.app.run_polling()

    async def check_manual_sells_periodically(self):
        """Periodically check for manual sells."""
        while True:
            for chat_id in self.users:
                bot = self.users[chat_id]["bot"]
                token_address, sell_mcap = await bot.check_manual_sells()
                if token_address and sell_mcap:
                    await generate_pnl_card(chat_id, token_address, sell_mcap, bot.buy_records, self.app.bot, self.users[chat_id]["history"])
            await asyncio.sleep(300)

    async def check_limit_orders_periodically(self):
        """Periodically check and execute limit orders."""
        while True:
            for chat_id in self.users:
                bot = self.users[chat_id]["bot"]
                success, msg, mcap = await bot.check_limit_orders()
                if success and mcap:
                    await generate_pnl_card(chat_id, bot.limit_orders[0]["token_address"], mcap, bot.buy_records, self.app.bot, self.users[chat_id]["history"])
            await asyncio.sleep(60)

    async def download_portfolio_growth(self, chat_id, period):
        """Download portfolio growth history in various formats."""
        bot = self.users[chat_id]["bot"]
        data = self.users[chat_id]["portfolio_data"]
        dates, growth = self._get_growth_data(data, period)

        # PNG
        plt.figure(figsize=(19.2, 10.8))  # HD resolution
        plt.plot(dates, growth, color="blue")
        plt.title(f"Portfolio Growth - {period}")
        plt.xlabel("Date")
        plt.ylabel("Growth (x)")
        plt.grid(True)
        png_buffer = BytesIO()
        plt.savefig(png_buffer, format="png", dpi=100)
        png_buffer.seek(0)

        # JPEG
        jpeg_buffer = BytesIO()
        plt.savefig(jpeg_buffer, format="jpeg", dpi=100)
        jpeg_buffer.seek(0)

        # CSV
        csv_buffer = BytesIO()
        csv_buffer.write(b"Date,Growth(x)\n")
        for d, g in zip(dates, growth):
            csv_buffer.write(f"{d},{g}\n".encode())
        csv_buffer.seek(0)

        # PDF
        pdf_buffer = BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=letter)
        c.drawString(100, 750, f"Portfolio Growth - {period}")
        c.drawImage(png_buffer, 100, 400, 400, 200)
        c.showPage()
        c.save()
        pdf_buffer.seek(0)

        await self.app.bot.send_photo(chat_id, photo=png_buffer, caption="Portfolio Growth (PNG)")
        await self.app.bot.send_photo(chat_id, photo=jpeg_buffer, caption="Portfolio Growth (JPEG)")
        await self.app.bot.send_document(chat_id, document=csv_buffer, filename=f"portfolio_growth_{period}.csv")
        await self.app.bot.send_document(chat_id, document=pdf_buffer, filename=f"portfolio_growth_{period}.pdf")

    def _get_growth_data(self, data, period):
        """Helper to get growth data based on period."""
        start_time = data["start_time"]
        current_time = time.time()
        dates = []
        growth = []
        if period == "this_month":
            start = current_time - 30 * 24 * 3600
        elif period == "last_month":
            start = current_time - 60 * 24 * 3600
            end = current_time - 30 * 24 * 3600
        elif period == "last_3_months":
            start = current_time - 90 * 24 * 3600
        elif period == "last_6_months":
            start = current_time - 180 * 24 * 3600
        elif period == "1_year":
            start = current_time - 365 * 24 * 3600
        else:  # Custom
            start = current_time - 365 * 24 * 3600  # Default to 1 year if custom not implemented
        for t, g in zip(data["timestamps"], data["growth"]):
            if t >= start and (period != "last_month" or t <= end):
                dates.append(time.strftime("%Y-%m-%d", time.localtime(t)))
                growth.append(g)
        if current_time - start_time > 365 * 24 * 3600:
            data.clear()  # Delete after 1 year
        return dates, growth