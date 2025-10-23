import asyncio
import aiohttp
import time
from config import DEXSCREENER_API
from reporting import send_token_notification

async def monitor_new_tokens(telegram_bot):
    """Monitor new tokens on DexScreener and notify users of new token listings."""
    last_check = 0
    while True:
        if time.time() - last_check >= 300:  # Check every 5 minutes
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(DEXSCREENER_API, timeout=10) as response:
                        if response.status != 200:
                            print(f"DexScreener API error: Status {response.status}")
                            last_check = time.time()
                            continue
                        data = await response.json()
                        pairs = data.get("pairs", [])
                        if not pairs:
                            print("No new token pairs found.")
                            last_check = time.time()
                            continue
                        for pair in pairs:
                            token_address = pair.get("baseToken", {}).get("address")
                            coin_name = pair.get("baseToken", {}).get("name", "Unknown")
                            mcap = pair.get("marketCap", 0)
                            image_url = pair.get("info", {}).get("imageUrl", "")
                            dex = pair.get("dex", {}).get("name", "Unknown DEX")
                            dex_paid = pair.get("dexPaid", False)
                            if not token_address or not coin_name:
                                print(f"Skipping pair with missing data: {pair}")
                                continue
                            for chat_id in telegram_bot.users:
                                try:
                                    text, image = await send_token_notification(
                                        chat_id, token_address, coin_name, mcap, image_url, dex, dex_paid
                                    )
                                    if text:
                                        await telegram_bot.app.bot.send_message(
                                            chat_id=chat_id,
                                            text=text,
                                            parse_mode="HTML"
                                        )
                                        if image:
                                            await telegram_bot.app.bot.send_photo(
                                                chat_id=chat_id,
                                                photo=image
                                            )
                                except Exception as e:
                                    print(f"Error notifying user {chat_id}: {e}")
            except aiohttp.ClientError as e:
                print(f"DexScreener API request failed: {e}")
            except Exception as e:
                print(f"Unexpected error in monitor_new_tokens: {e}")
            last_check = time.time()
        await asyncio.sleep(60)  # Check every minute, but only fetch every 5 minutes