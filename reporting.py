import aiohttp
from PIL import Image, ImageDraw, ImageFont
import io
import time
import random
import requests
import os
import matplotlib.pyplot as plt
from config import SOL_LOGO, FEE_PERCENTAGES

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
                data = await response.json() if response.status == 200 else {}
                image = None
                if data.get("pairs") and data["pairs"]:
                    async with session.get(data["pairs"][0]["info"]["imageUrl"]) as img_response:
                        image = await img_response.read() if img_response.status == 200 else None
        return text, image, message_id
    return None, None, None

async def generate_pnl_card(chat_id, token_address, sell_mcap, buy_records, bot, history, users):
    """Generate a 'ZK Speed' PnL card with dynamic character and portfolio chart."""
    for record in buy_records:
        if record["token_address"] == token_address:
            buy_mcap = record["buy_mcap"]
            multiple = sell_mcap / buy_mcap if buy_mcap and sell_mcap else 0
            sol_invested = record["amount"]
            # Apply transaction fee from FEE_PERCENTAGES (default to first percentage if not specified)
            fee_percentage = record.get("fee_percentage", FEE_PERCENTAGES[0]) / 100
            sol_profit = sol_invested * (multiple - 1) * (1 - fee_percentage) if multiple > 0 else -sol_invested
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

            # Custom name from users dict
            custom_name = users.get(chat_id, {}).get("custom_name", f"Ze King👑 {chat_id}")

            # Generate meme character (skipping Gemini API since GEMINI_API_KEY is not in config)
            character_img = None  # Placeholder if you want to re-enable image generation later

            # Create HD image (1920x1080)
            img = Image.new("RGB", (1920, 1080), color=(0, 0, 0))
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default(size=40)  # Default font with larger size
            try:
                cool_font = ImageFont.truetype("arial.ttf", 40)
            except:
                cool_font = font  # Fallback to default

            # Draw text with fee information
            draw.text((50, 50), custom_name, fill="#00BFFF", font=font)
            draw.text((50, 100), f"Coin: {await bot.fetch_coin_name(token_address) or 'Unknown'}", fill="white", font=font)
            draw.text((50, 150), f"Profit: {multiple:+.2f}x" if multiple >= 0 else f"Profit: -{-multiple:.2f}x",
                      fill="#00BFFF" if multiple >= 0 else "#FF0000", font=cool_font)
            draw.text((50, 200), f"{SOL_LOGO} Invested: {sol_invested:.4f}", fill="white", font=font)
            draw.text((50, 250), f"{SOL_LOGO} Profit: {sol_profit:.4f} (Fee: {fee_percentage*100:.1f}%)",
                      fill="#00FF00" if sol_profit > 0 else "#FF0000", font=font)
            draw.text((50, 300), f"{SOL_LOGO} Capital: {capital:.4f}", fill="white", font=font)
            draw.text((50, 350), f"Hold Time: {hold_str}", fill="white", font=font)

            # Add neon lines for visual flair
            for _ in range(5):
                x1, y1 = random.randint(0, 1920), random.randint(0, 1080)
                x2, y2 = random.randint(0, 1920), random.randint(0, 1080)
                draw.line((x1, y1, x2, y2), fill="#00BFFF", width=2)

            # Add character (if available, skipped for now due to missing API key)
            if character_img:
                try:
                    char_img = Image.open(character_img)
                    char_img = char_img.resize((300, 300), Image.Resampling.LANCZOS)
                    position = (50, 450) if random.choice([True, False]) else (1570, 450)
                    img.paste(char_img, position, char_img if char_img.mode == "RGBA" else None)
                except Exception:
                    pass

            # Add ZK Speed branding
            try:
                draw.text((850, 950), "ZK Speed", fill="#00BFFF", font=ImageFont.truetype("arial.ttf", 60))
            except:
                draw.text((850, 950), "ZK Speed", fill="#00BFFF", font=font)

            # Save as JPG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            buffer.seek(0)
            await bot.send_photo(chat_id=chat_id, photo=buffer)

            if record.get("sell_time"):
                history[token_address] = {
                    "pnl_card": buffer,
                    "sell_time": record["sell_time"],
                    "expiration": record["sell_time"] + 90 * 24 * 3600
                }
            return buffer
    return None

async def generate_portfolio_chart(chat_id, period, users):
    """Generate a portfolio growth chart."""
    bot = users.get(chat_id, {}).get("bot")
    data = users.get(chat_id, {}).get("portfolio_data", {})
    if not bot or not data:
        return None
    dates, growth = _get_growth_data(data, period)

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
    plt.close()  # Close plot to free memory
    return buffer

def _get_growth_data(data, period):
    """Helper to get growth data based on period."""
    start_time = data.get("start_time", time.time())
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
        start = current_time - 365 * 24 * 3600  # Default to 1 year
    for t, g in zip(data.get("timestamps", []), data.get("growth", [])):
        if t >= start and (period != "last_month" or t <= end):
            dates.append(time.strftime("%Y-%m-%d", time.localtime(t)))
            growth.append(g)
    if current_time - start_time > 365 * 24 * 3600:
        data.clear()  # Clear data after 1 year
    return dates, growth

async def get_token_status(chat_id, token_address, bot, users):
    """Fetch token status including coin name, MCap, and profit percentage."""
    coin_name = await bot.fetch_coin_name(token_address) or "Unknown"
    current_mcap = await bot.fetch_token_mcap(token_address) or 0
    holdings = next((r["amount"] for r in bot.buy_records if r["token_address"] == token_address and r.get("sell_mcap") is None), 0)
    buy_mcap = next((r["buy_mcap"] for r in bot.buy_records if r["token_address"] == token_address and r.get("sell_mcap") is None), 0)
    # Apply fee percentage to profit calculation
    fee_percentage = next((r.get("fee_percentage", FEE_PERCENTAGES[0]) for r in bot.buy_records if r["token_address"] == token_address), FEE_PERCENTAGES[0]) / 100
    profit = ((current_mcap - buy_mcap) / buy_mcap * (1 - fee_percentage) * 100) if buy_mcap and current_mcap else 0
    return coin_name, current_mcap, profit if holdings > 0 else (coin_name, current_mcap, 0)

async def cleanup_history(chat_id, users):
    """Remove history entries older than 90 days."""
    if chat_id in users and "history" in users.get(chat_id, {}):
        current_time = time.time()
        history = users[chat_id]["history"]
        for token, data in list(history.items()):
            if current_time > data["expiration"]:
                del history[token]