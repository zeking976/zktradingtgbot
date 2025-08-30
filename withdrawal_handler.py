import aiohttp
import time
from config import SOL_LOGO, RPC_ENDPOINT
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solders.keypair import Keypair

async def handle_withdrawal(chat_id, bot, amount, destination, fee_buffer=None, fee_congestion=None):
    """
    Handle SOL withdrawal with live USD conversion and Solscan link.
    Returns: success (bool), message (str), tx_hash (str or None)
    """
    try:
        amount = float(amount)
        fee_buffer = fee_buffer if fee_buffer else 0.001  # Default from config
        fee_congestion = fee_congestion if fee_congestion else 0.001  # Default from config
        total_cost = amount + fee_buffer + fee_congestion

        # Check balance
        client = AsyncClient(RPC_ENDPOINT)
        balance = await client.get_balance(bot.keypair.pubkey())
        if balance.value / 1e9 < total_cost:
            return False, "Insufficient balance", None

        # Fetch live SOL price in USD
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd") as response:
                data = await response.json()
                sol_price_usd = data["solana"]["usd"]

        # Execute withdrawal
        await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV
        tx = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=bot.keypair.pubkey(),
                    to_pubkey=destination,
                    lamports=int(amount * 1e9)
                )
            )
        )
        tx_resp = await client.send_transaction(tx, bot.keypair)
        tx_hash = tx_resp.value

        # Calculate live USD amount
        usd_amount = amount * sol_price_usd

        # Prepare message with Solscan link
        solscan_link = f"https://solscan.io/tx/{tx_hash}"
        message = f"Withdrawal of {amount} {SOL_LOGO} ~ ${usd_amount:.2f} completed✅\n\n" \
                  f"View on Solscan: [Click Here]({solscan_link})"
        keyboard = [
            [InlineKeyboardButton("View on Solscan", url=solscan_link)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        return True, message, tx_hash

    except Exception as e:
        return False, f"Error executing withdrawal: {e}", None