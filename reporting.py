import aiohttp
from PIL import Image, ImageDraw, ImageFont
import io
import time
import random
import requests
from config import SOL_LOGO, GEMINI_API_KEY
import matplotlib.pyplot as plt

async def send_token_notification(chat_id, token_address, coin_name, mcap, image_url, dex, dex_paid):
    """Send notification for new token in bonding phase."""
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            image = await response.read() if response.status == 200 else None

    text = f"New Token on {dex} {'(DEX Paid)' if dex_paid else ''}:\n" \
           f"Name: {coin_name}\n" \
           f"MCap: ${mcap:,.2f}\n" \
           f"CA: {token_address}"
    return text, image

async def send_mcap_update(chat_id, token_address, coin_name, current_mcap, buy_mcap, message_id, dex_paid, bonded):
    """Send MCap update as a reply to the original message."""
    multiple = current_mcap / buy_mcap if buy_mcap and current_mcap else 0
    multiples = [i / 100 for i in range(1, 10001)] + [10000]
    if any(abs(multiple - m) < 0.01 for m in multiples):
        text = f"Update for {coin_name} {'(Bonded)' if bonded else ''} {'(DEX Paid)' if dex_paid else ''}:\n" \
               f"MCap: ${current_mcap:,.2f} ({multiple:.2f}x)"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}") as response:
                data = await response.json()
                image = await session.get(data["pairs"][0]["info"]["imageUrl"]).read() if data["pairs"] else None
        return text, image, message_id
    return None, None, None

async def generate_pnl_card(chat_id, token_address, sell_mcap, buy_records, bot, history):
    """Generate a 'ZK Speed' PnL card with dynamic character and portfolio chart."""
    for record in buy_records:
        if record["token_address"] == token_address:
            buy_mcap = record["buy_mcap"]
            multiple = sell_mcap / buy_mcap if buy_mcap and sell_mcap else 0
            sol_invested = record["amount"]
            sol_profit = sol_invested * (multiple - 1) if multiple > 0 else -sol_invested
            capital = sol_invested + sol_profit
            hold_time = time.time() - record["timestamp"]
            years, remainder = divmod(hold_time, 31536000)
            weeks, remainder = divmod(remainder, 604800)
            days, remainder = divmod(remainder, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            hold_str = f"{int(years)}y {int(weeks)}w {int(days)}d {int(hours)}h {int(minutes)}m" if years else \
                       f"{int(days)}d {int(hours)}h {int(minutes)}m" if days else \
                       f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

            # Custom name
            custom_name = self.users[chat_id].get("custom_name", f"Ze King👑 {chat_id}")

            # Generate meme character via Gemini API
            profit_level = sol_profit / sol_invested if sol_invested else 0
            hold_level = hold_time / (30 * 24 * 3600)  # Normalize to months
            emotion = "happy" if profit_level > 0 else "sad" if profit_level < -0.5 else "neutral"
            meme_prompt = f"cartoon crypto meme character, {emotion}, profit {profit_level:.2%}, held {hold_level:.1f} months, trending crypto memes (Pepe, Doge, BTC)"
            response = requests.post(
                "https://api.gemini.com/v1/generate",
                json={"prompt": meme_prompt, "api_key": GEMINI_API_KEY}
            )
            character_img = BytesIO(response.content) if response.status_code == 200 else None

            # Create HD image (1920x1080)
            img = Image.new("RGB", (1920, 1080), color=(0, 0, 0))  # Black gradient space
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()
            cool_font = ImageFont.truetype("arial.ttf", 40)  # Placeholder for cool font
            draw.text((50, 50), custom_name, fill="#00BFFF", font=font)
            draw.text((50, 100), f"Coin: {await bot.fetch_coin_name(token_address)}", fill="white", font=font)
            draw.text((50, 150), f"Profit: {multiple:+.2f}x" if multiple >= 0 else f"Profit: -{-multiple:.2f}x",
                      fill="#00BFFF" if multiple >= 0 else "#FF0000", font=cool_font)
            draw.text((50, 200), f"{SOL_LOGO} Invested: {sol_invested:.4f}", fill="white", font=font)
            draw.text((50, 250), f"{SOL_LOGO} Profit: {sol_profit:.4f}",
                      fill="#00FF00" if sol_profit > 0 else "#FF0000", font=font)
            draw.text((50, 300), f"{SOL_LOGO} Capital: {capital:.4f}", fill="white", font=font)
            draw.text((50, 350), f"Hold Time: {hold_str}", fill="white", font=font)

            # Add neon lines
            for _ in range(5):
                x1, y1 = random.randint(0, 1920), random.randint(0, 1080)
                x2, y2 = random.randint(0, 1920), random.randint(0, 1080)
                draw.line((x1, y1, x2, y2), fill="#00BFFF", width=2)

            # Add character (random left or right)
            if character_img:
                char_img = Image.open(character_img)
                char_img = char_img.resize((300, 300), Image.Resampling.LANCZOS)
                position = (50, 450) if random.choice([True, False]) else (1570, 450)
                img.paste(char_img, position, char_img if char_img.mode == "RGBA" else None)

            # Add ZK Speed
            draw.text((850, 950), "ZK Speed", fill="#00BFFF", font=ImageFont.truetype("arial.ttf", 60))

            # Save as JPG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            buffer.seek(0)
            await bot.send_photo(chat_id=chat_id, photo=buffer)

            if record["sell_time"]:
                history[token_address] = {
                    "pnl_card": buffer,
                    "sell_time": record["sell_time"],
                    "expiration": record["sell_time"] + 90 * 24 * 3600  # 90 days (repeated)
                }
            return buffer
    return None

async def generate_portfolio_chart(chat_id, period):
    """Generate a portfolio growth chart."""
    bot = self.users[chat_id]["bot"]
    data = self.users[chat_id]["portfolio_data"]
    dates, growth = self._get_growth_data(data, period)

    plt.figure(figsize=(19.2, 10.8))  # HD resolution
    plt.plot(dates, growth, color="blue", linewidth=2)
    plt.title(f"Portfolio Growth - {period}", fontsize=20)
    plt.xlabel("Date", fontsize=14)
    plt.ylabel("Growth (x)", fontsize=14)
    plt.grid(True)
    plt.xticks(rotation=45)
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100)
    buffer.seek(0)
    return buffer

async def cleanup_history(chat_id, users):
    """Remove history entries older than 90 days (repeated cycle)."""
    if chat_id in users and "history" in users[chat_id]:
        current_time = time.time()
        history = users[chat_id]["history"]
        for token, data in list(history.items()):
            if current_time > data["expiration"]:
                del history[token]  # Remove from memory, not media