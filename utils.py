import asyncio
import aiohttp
import time
from config import DEXSCREENER_API

async def monitor_new_tokens(telegram_bot):
    """Monitor new tokens on DexScreener and notify users."""
    last_check = 0
    while True:
        if time.time() - last_check > 300:  # Check every 5 minutes
            async with aiohttp.ClientSession() as session:
                async with session.get(DEXSCREENER_API) as response:
                    data = await response.json()
                    for pair in data.get("pairs", []):
                        token_address = pair["baseToken"]["address"]
                        coin_name = pair["baseToken"]["name"]
                        mcap = pair["marketCap"]
                        image_url = pair["info"]["imageUrl"]
                        dex = pair["dex"]["name"]
                        dex_paid = pair.get("dexPaid", False)
                        for chat_id in telegram_bot.users:
                            text, image = await send_token_notification(chat_id, token_address, coin_name, mcap, image_url, dex, dex_paid)
                            if text:
                                await telegram_bot.app.bot.send_message(chat_id=chat_id, text=text)
                                if image:
                                    await telegram_bot.app.bot.send_photo(chat_id=chat_id, photo=image)
            last_check = time.time()
        await asyncio.sleep(60)