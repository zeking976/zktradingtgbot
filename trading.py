import time
import aiohttp
import random
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from config import RPC_ENDPOINT, FEE_PERCENTAGES, DEXSCREENER_API, TRIGGER_API, ULTRA_API
from withdrawal_handler import handle_withdrawal

class TradingBot:
    def __init__(self, private_key):
        """
        Initialize TradingBot with Solana client and keypair.
        Args:
            private_key: Base58-encoded Solana private key.
        """
        self.client = AsyncClient(RPC_ENDPOINT)
        self.keypair = Keypair.from_base58_string(private_key) if private_key else None
        self.buy_records = []  # {token_address, amount, timestamp, tx_id, buy_mcap, sell_mcap, sell_time, manual, fee_percentage}
        self.limit_orders = []  # {token_address, amount, price, order_type, percentage, fee_percentage, timestamp, request_id}

    async def fetch_token_mcap(self, token_address):
        """Fetch current token market cap from DexScreener."""
        if token_address == "FakeToken123...XYZ":
            return 750000  # Mock MCap for testing
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{DEXSCREENER_API}{token_address}", timeout=5) as response:
                    if response.status != 200:
                        print(f"DexScreener API error: Status {response.status}")
                        return 0
                    data = await response.json()
                    pairs = data.get("pairs", [])
                    return float(pairs[0].get("marketCap", 0)) if pairs else 0
        except aiohttp.ClientError as e:
            print(f"Error fetching market cap: {e}")
            return 0

    async def fetch_token_price(self, token_address):
        """Fetch current token price in SOL from DexScreener."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}", timeout=5) as response:
                    if response.status != 200:
                        print(f"DexScreener API error: Status {response.status}")
                        return 0
                    data = await response.json()
                    pairs = data.get("pairs", [])
                    return float(pairs[0].get("priceNative", 0)) if pairs else 0
        except aiohttp.ClientError as e:
            print(f"Error fetching token price: {e}")
            return 0

    async def fetch_coin_name(self, token_address):
        """Fetch coin name from DexScreener."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}", timeout=5) as response:
                    if response.status != 200:
                        print(f"DexScreener API error: Status {response.status}")
                        return "Unknown"
                    data = await response.json()
                    pairs = data.get("pairs", [])
                    return pairs[0].get("baseToken", {}).get("name", "Unknown") if pairs else "Unknown"
        except aiohttp.ClientError as e:
            print(f"Error fetching coin name: {e}")
            return "Unknown"

    async def sign_transaction(self, data):
        """
        Sign a raw transaction from API response.
        Args:
            data: Transaction data from Trigger/Ultra Swap API.
        Returns:
            Base64-encoded signed transaction.
        """
        try:
            # Placeholder: Assumes data contains a raw transaction to sign
            # Replace with actual deserialization logic based on API response
            tx = Transaction.deserialize(data.get("transaction"))  # Adjust based on actual API response format
            tx.sign([self.keypair])
            return tx.serialize().decode("base64")
        except Exception as e:
            raise Exception(f"Error signing transaction: {e}")

    async def buy_token(self, token_address, amount, fee_percentage=None):
        """
        Execute a market buy using Ultra Swap API.
        Args:
            token_address: Token address to buy (outputMint).
            amount: SOL amount to spend.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else FEE_PERCENTAGES[0]
        try:
            amount = float(amount)
            total_cost = amount * (1 + fee_percentage / 100)
            balance = await self.client.get_balance(self.keypair.pubkey())
            if balance.value / 1e9 < total_cost:
                return False, f"Insufficient balance: {balance.value / 1e9:.4f} SOL available, {total_cost:.4f} SOL needed."

            # Validate token address
            try:
                Pubkey.from_string(token_address)
            except Exception:
                return False, "Invalid token address."

            # Get order from Ultra Swap API
            async with aiohttp.ClientSession() as session:
                params = {
                    "inputMint": "So11111111111111111111111111111111111111112",  # SOL
                    "outputMint": token_address,
                    "amount": int(amount * 1e9),  # Convert SOL to lamports
                    "taker": str(self.keypair.pubkey())
                }
                async with session.get(f"{ULTRA_API}/order", params=params) as response:
                    if response.status != 200:
                        return False, f"Ultra Swap API error: Status {response.status}"
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Ultra Swap API."

                # Sign and execute order
                signed_tx = await self.sign_transaction(data)
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{ULTRA_API}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Ultra Swap execution failed: Status {execute_response.status}"
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")

            # Update buy records
            mcap = await self.fetch_token_mcap(token_address)
            self.buy_records.append({
                "token_address": token_address,
                "amount": amount,
                "timestamp": time.time(),
                "tx_id": tx_hash,
                "buy_mcap": mcap,
                "sell_mcap": None,
                "sell_time": None,
                "manual": False,
                "fee_percentage": fee_percentage
            })

            return True, f"Buy executed for {amount:.4f} SOL of {token_address} (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}"
        except Exception as e:
            return False, f"Error executing buy: {e}"

    async def sell_token(self, token_address, amount, fee_percentage=None):
        """
        Execute a market sell using Ultra Swap API.
        Args:
            token_address: Token address to sell (inputMint).
            amount: Token amount to sell.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str, mcap: float or None)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else FEE_PERCENTAGES[0]
        try:
            amount = float(amount)
            holdings = next(
                (r["amount"] for r in self.buy_records if r["token_address"] == token_address and r["sell_mcap"] is None),
                0
            )
            if amount > holdings:
                return False, f"Insufficient holdings: {holdings:.4f} available, {amount:.4f} requested.", None

            # Validate token address
            try:
                Pubkey.from_string(token_address)
            except Exception:
                return False, "Invalid token address.", None

            # Get order from Ultra Swap API
            async with aiohttp.ClientSession() as session:
                params = {
                    "inputMint": token_address,
                    "outputMint": "So11111111111111111111111111111111111111112",  # SOL
                    "amount": int(amount * 1e9),  # Assumes token uses 9 decimals; adjust if needed
                    "taker": str(self.keypair.pubkey())
                }
                async with session.get(f"{ULTRA_API}/order", params=params) as response:
                    if response.status != 200:
                        return False, f"Ultra Swap API error: Status {response.status}", None
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Ultra Swap API.", None

                # Sign and execute order
                signed_tx = await self.sign_transaction(data)
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{ULTRA_API}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Ultra Swap execution failed: Status {execute_response.status}", None
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")

            # Update buy records
            mcap = await self.fetch_token_mcap(token_address)
            for record in self.buy_records:
                if record["token_address"] == token_address and record["sell_mcap"] is None:
                    record["sell_mcap"] = mcap
                    record["sell_time"] = time.time()
                    record["fee_percentage"] = fee_percentage
                    break

            return True, f"Sell executed for {amount:.4f} of {token_address} (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}", mcap
        except Exception as e:
            return False, f"Error executing sell: {e}", None

    async def set_limit_order(self, token_address, amount, price, order_type, percentage=None, fee_percentage=None):
        """
        Set a limit order using Trigger API.
        Args:
            token_address: Token address for the order.
            amount: Amount to buy/sell.
            price: Target price in SOL per token.
            order_type: 'buy' or 'sell'.
            percentage: Percentage of holdings (0-100).
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else FEE_PERCENTAGES[0]
        percentage = float(percentage) if percentage else 100.0
        try:
            if order_type not in ["buy", "sell"] or percentage <= 0 or percentage > 100:
                return False, "Invalid order type or percentage."
            if order_type == "sell":
                holdings = next(
                    (r["amount"] for r in self.buy_records if r["token_address"] == token_address and r["sell_mcap"] is None),
                    0
                )
                if amount * (percentage / 100) > holdings:
                    return False, f"Insufficient holdings for sell order: {holdings:.4f} available."

            # Validate token address
            try:
                Pubkey.from_string(token_address)
            except Exception:
                return False, "Invalid token address."

            # Create order using Trigger API
            async with aiohttp.ClientSession() as session:
                input_mint = "So11111111111111111111111111111111111111112" if order_type == "buy" else token_address
                output_mint = token_address if order_type == "buy" else "So11111111111111111111111111111111111111112"
                payload = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "maker": str(self.keypair.pubkey()),
                    "payer": str(self.keypair.pubkey()),
                    "params": {
                        "makingAmount": int(amount * 1e9),  # Adjust based on token decimals
                        "takingAmount": int(amount * price * 1e9),  # Price-based amount
                        "slippageBps": 50,  # 0.5% slippage
                        "expiredAt": int(time.time() + 7 * 24 * 3600)  # 7-day expiry
                    },
                    "computeUnitPrice": "auto"
                }
                async with session.post(f"{TRIGGER_API}/createOrder", json=payload) as response:
                    if response.status != 200:
                        return False, f"Trigger API error: Status {response.status}"
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Trigger API."

                # Sign and execute order
                signed_tx = await self.sign_transaction(data)
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{TRIGGER_API}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Trigger API execution failed: Status {execute_response.status}"
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")

            # Store limit order
            self.limit_orders.append({
                "token_address": token_address,
                "amount": float(amount),
                "price": float(price),
                "order_type": order_type.lower(),
                "percentage": percentage,
                "fee_percentage": fee_percentage,
                "timestamp": time.time(),
                "request_id": request_id,
                "tx_hash": tx_hash
            })

            return True, f"Limit {order_type} order set for {amount:.4f} of {token_address} at {price:.6f} SOL (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}"
        except Exception as e:
            return False, f"Error setting limit order: {e}"

    async def check_limit_orders(self):
        """
        Check and execute limit orders based on current market price.
        Returns:
            (success: bool, message: str, mcap: float or None)
        """
        try:
            current_prices = {}
            async with aiohttp.ClientSession() as session:
                for order in self.limit_orders[:]:
                    token = order["token_address"]
                    if token not in current_prices:
                        current_prices[token] = await self.fetch_token_price(token)
                    current_price = current_prices[token]
                    target_price = order["price"]

                    if order["order_type"] == "buy" and current_price <= target_price:
                        success, msg = await self.buy_token(token, order["amount"], order["fee_percentage"])
                        if success:
                            self.limit_orders.remove(order)
                            return True, f"Limit buy executed for {token}: {msg}", None
                    elif order["order_type"] == "sell" and current_price >= target_price:
                        total_amount = next(
                            (r["amount"] for r in self.buy_records if r["token_address"] == token and r["sell_mcap"] is None),
                            0
                        )
                        sell_amount = (order["percentage"] / 100) * total_amount
                        success, msg, mcap = await self.sell_token(token, sell_amount, order["fee_percentage"])
                        if success:
                            self.limit_orders.remove(order)
                            return True, f"Limit sell executed for {token} ({order['percentage']}%)", mcap
            return False, "No limit orders triggered", None
        except Exception as e:
            return False, f"Error checking limit orders: {e}", None

    async def check_manual_sells(self):
        """
        Check for manual buys/sells by monitoring token balances.
        Returns:
            (token_address: str or None, mcap: float or None)
        """
        try:
            for record in self.buy_records:
                if record["sell_mcap"] is None:
                    token_address = record["token_address"]
                    # Placeholder: Replace with actual token balance check
                    balance = await self.client.get_token_account_balance(token_address, commitment="confirmed")  # Adjust based on Solana API
                    if balance.value.ui_amount < record["amount"] * 0.9:
                        current_mcap = await self.fetch_token_mcap(token_address)
                        record["sell_mcap"] = current_mcap
                        record["sell_time"] = time.time()
                        return token_address, current_mcap
                    elif not record["manual"] and balance.value.ui_amount > 0:
                        record["manual"] = True
            return None, None
        except Exception as e:
            print(f"Error checking manual sells: {e}")
            return None, None

    async def transfer_sol(self, amount, destination, fee_percentage=None):
        """
        Transfer SOL to another wallet using handle_withdrawal.
        Args:
            amount: SOL amount to transfer.
            destination: Destination wallet address.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str, tx_hash: str or None)
        """
        return await handle_withdrawal(str(self.keypair.pubkey()), self, amount, destination, fee_percentage)