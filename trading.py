import time
import aiohttp
import random
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solders.keypair import Keypair
from config import RPC_ENDPOINT, GAS_BUFFER_DEFAULT, CONGESTION_FEE_DEFAULT, FEE_PERCENTAGES

class TradingBot:
    def __init__(self, private_key):
        self.client = AsyncClient(RPC_ENDPOINT)
        self.keypair = Keypair.from_base58_string(private_key) if private_key else None
        self.buy_records = []  # {token_address, amount, timestamp, tx_id, buy_mcap, sell_mcap, sell_time, manual}
        self.limit_orders = []  # {token_address, amount, price, order_type, percentage, fee_buffer, fee_congestion, timestamp}

    async def buy_token(self, token_address, amount, fee_buffer=None, fee_congestion=None, manual=False):
        """Execute a market buy with GAS BUFFER and congestion fee."""
        try:
            amount = float(amount)
            fee_buffer = fee_buffer if fee_buffer else GAS_BUFFER_DEFAULT
            fee_congestion = fee_congestion if fee_congestion else CONGESTION_FEE_DEFAULT
            total_cost = amount + fee_buffer + fee_congestion

            balance = await self.client.get_balance(self.keypair.pubkey())
            if balance.value / 1e9 < total_cost:
                return False, "Insufficient balance"

            await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV
            tx = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=self.keypair.pubkey(),
                        to_pubkey=self.keypair.pubkey(),  # Replace with DEX account
                        lamports=int(amount * 1e9)
                    )
                )
            )
            tx_resp = await self.client.send_transaction(tx, self.keypair)
            mcap = await self.fetch_token_mcap(token_address)
            self.buy_records.append({
                "token_address": token_address,
                "amount": amount,
                "timestamp": time.time(),
                "tx_id": tx_resp.value,
                "buy_mcap": mcap,
                "sell_mcap": None,
                "sell_time": None,
                "manual": manual
            })
            return True, f"Buy executed for {token_address}: {tx_resp.value}"

        except Exception as e:
            return False, f"Error executing buy: {e}"

    async def sell_token(self, token_address, amount, fee_buffer=None, fee_congestion=None):
        """Execute a market sell with GAS BUFFER and congestion fee."""
        try:
            amount = float(amount)
            fee_buffer = fee_buffer if fee_buffer else GAS_BUFFER_DEFAULT
            fee_congestion = fee_congestion if fee_congestion else CONGESTION_FEE_DEFAULT

            await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV
            tx = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=self.keypair.pubkey(),
                        to_pubkey=self.keypair.pubkey(),  # Replace with DEX account
                        lamports=int(amount * 1e9)
                    )
                )
            )
            tx_resp = await self.client.send_transaction(tx, self.keypair)
            mcap = await self.fetch_token_mcap(token_address)
            for record in self.buy_records:
                if record["token_address"] == token_address and record["sell_mcap"] is None:
                    record["sell_mcap"] = mcap
                    record["sell_time"] = time.time()
                    break
            return True, f"Sell executed for {token_address}: {tx_resp.value}", mcap

        except Exception as e:
            return False, f"Error executing sell: {e}", None

    async def check_manual_sells(self):
        """Check for manual buys/sells by monitoring token balances."""
        try:
            for record in self.buy_records:
                if record["sell_mcap"] is None:
                    token_address = record["token_address"]
                    balance = await self.client.get_token_account_balance(token_address)  # Placeholder
                    if balance.value.ui_amount < record["amount"] * 0.9:
                        current_mcap = await self.fetch_token_mcap(token_address)
                        record["sell_mcap"] = current_mcap
                        record["sell_time"] = time.time()
                        return token_address, current_mcap
                    elif not record["manual"] and balance.value.ui_amount > 0:
                        record["manual"] = True  # Mark as manually bought if balance detected
            return None, None
        except Exception as e:
            print(f"Error checking manual sells: {e}")
            return None, None

    async def swap_token(self, from_token, to_token, amount, fee_buffer=None, fee_congestion=None):
        """Execute a token swap."""
        try:
            amount = float(amount)
            fee_buffer = fee_buffer if fee_buffer else GAS_BUFFER_DEFAULT
            fee_congestion = fee_congestion if fee_congestion else CONGESTION_FEE_DEFAULT

            await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV
            tx = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=self.keypair.pubkey(),
                        to_pubkey=self.keypair.pubkey(),  # Replace with swap program
                        lamports=int(amount * 1e9)
                    )
                )
            )
            tx_resp = await self.client.send_transaction(tx, self.keypair)
            return True, f"Swap executed from {from_token} to {to_token}: {tx_resp.value}"

        except Exception as e:
            return False, f"Error executing swap: {e}"

    async def set_limit_order(self, token_address, amount, price, order_type, percentage=None, fee_buffer=None, fee_congestion=None):
        """Set a limit order for buy or sell with percentage options."""
        self.limit_orders.append({
            "token_address": token_address,
            "amount": float(amount),  # SOL for buy, token amount for sell
            "price": float(price),   # Target price in SOL per token
            "order_type": order_type.lower(),  # "buy" or "sell"
            "percentage": float(percentage) if percentage else 100.0,  # Sell percentage
            "fee_buffer": fee_buffer if fee_buffer else GAS_BUFFER_DEFAULT,
            "fee_congestion": fee_congestion if fee_congestion else CONGESTION_FEE_DEFAULT,
            "timestamp": time.time()
        })
        return True, f"Limit {order_type} order set for {token_address} at {price} SOL for {amount} {order_type}"

    async def check_limit_orders(self):
        """Check and execute limit orders based on current market price."""
        current_prices = {}
        async with aiohttp.ClientSession() as session:
            for order in self.limit_orders[:]:
                token = order["token_address"]
                if token not in current_prices:
                    current_prices[token] = await self.fetch_token_price(token)
                current_price = current_prices[token]
                target_price = order["price"]

                if order["order_type"] == "buy" and current_price <= target_price:
                    success, msg = await self.buy_token(token, order["amount"], order["fee_buffer"], order["fee_congestion"])
                    if success:
                        self.limit_orders.remove(order)
                        return True, f"Limit buy executed for {token}: {msg}"
                elif order["order_type"] == "sell" and current_price >= target_price:
                    total_amount = next((r["amount"] for r in self.buy_records if r["token_address"] == token and r["sell_mcap"] is None), 0)
                    sell_amount = (order["percentage"] / 100) * total_amount
                    success, msg, mcap = await self.sell_token(token, sell_amount, order["fee_buffer"], order["fee_congestion"])
                    if success:
                        self.limit_orders.remove(order)
                        return True, f"Limit sell executed for {token} ({order['percentage']}%)", mcap
        return False, "No limit orders triggered"

    async def fetch_token_price(self, token_address):
        """Fetch current token price in SOL."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}") as response:
                data = await response.json()
                pairs = data.get("pairs", [])
                return float(pairs[0].get("priceNative", 0)) if pairs else 0

    async def fetch_token_mcap(self, token_address):
        """Fetch current token market cap from DexScreener."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}") as response:
                data = await response.json()
                pairs = data.get("pairs", [])
                return float(pairs[0].get("marketCap", 0)) if pairs else 0

    async def fetch_coin_name(self, token_address):
        """Fetch coin name from DexScreener."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}") as response:
                data = await response.json()
                pairs = data.get("pairs", [])
                return pairs[0].get("baseToken", {}).get("name", "Unknown") if pairs else "Unknown"

    async def withdraw(self, amount, destination, fee_buffer=None, fee_congestion=None):
        """Withdraw SOL to another address."""
        try:
            amount = float(amount)
            fee_buffer = fee_buffer if fee_buffer else GAS_BUFFER_DEFAULT
            fee_congestion = fee_congestion if fee_congestion else CONGESTION_FEE_DEFAULT

            await asyncio.sleep(random.uniform(0.01, 0.1))  # Anti-MEV
            tx = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=self.keypair.pubkey(),
                        to_pubkey=destination,
                        lamports=int(amount * 1e9)
                    )
                )
            )
            tx_resp = await self.client.send_transaction(tx, self.keypair)
            return True, f"Withdrawal of {amount} ◎ to {destination}: {tx_resp.value}"

        except Exception as e:
            return False, f"Error executing withdrawal: {e}"