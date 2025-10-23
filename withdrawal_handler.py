import asyncio
import aiohttp
import random
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from config import SOL_LOGO, RPC_ENDPOINT, FEE_PERCENTAGES
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def handle_withdrawal(chat_id, bot, amount, destination, fee_percentage=None):
    """
    Handle SOL withdrawal with live USD conversion and Solscan link.
    Args:
        chat_id: Telegram chat ID for sending messages.
        bot: TradingBot instance with keypair and client.
        amount: Amount of SOL to withdraw.
        destination: Destination Solana address.
        fee_percentage: Percentage fee for the transaction (from FEE_PERCENTAGES).
    Returns:
        (success: bool, message: str, tx_hash: str or None)
    """
    try:
        amount = float(amount)
        # Default to first fee percentage if not provided or invalid
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else FEE_PERCENTAGES[0]
        total_cost = amount * (1 + fee_percentage / 100)  # Apply fee percentage

        # Validate destination address
        try:
            Pubkey.from_string(destination)
        except Exception:
            return False, "Invalid destination address.", None

        # Check balance
        client = AsyncClient(RPC_ENDPOINT)
        balance = await client.get_balance(bot.keypair.pubkey())
        if balance.value / 1e9 < total_cost:
            return False, f"Insufficient balance: {balance.value / 1e9:.4f} SOL available, {total_cost:.4f} SOL needed.", None

        # Fetch live SOL price in USD
        sol_price_usd = 150.0  # Fallback price
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                    timeout=5
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        sol_price_usd = data.get("solana", {}).get("usd", sol_price_usd)
                    else:
                        print(f"CoinGecko API error: Status {response.status}")
        except aiohttp.ClientError as e:
            print(f"CoinGecko API request failed: {e}")

        # Execute withdrawal
        await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV delay
        tx = Transaction().add(
            transfer(
                TransferParams(
                    from_pubkey=bot.keypair.pubkey(),
                    to_pubkey=Pubkey.from_string(destination),
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
        message = (
            f"Withdrawal of {amount:.4f} {SOL_LOGO} ~ ${usd_amount:.2f} completed✅\n"
            f"Fee: {fee_percentage}% (${amount * (fee_percentage / 100) * sol_price_usd:.2f})\n"
            f"View on Solscan: [Click Here]({solscan_link})"
        )

        return True, message, tx_hash

    except Exception as e:
        return False, f"Error executing withdrawal: {e}", None