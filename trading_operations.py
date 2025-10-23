# trading_operations.py
import aiohttp
import time
from config import FEE_PERCENTAGES, SOL_LOGO
from reporting import generate_pnl_card
from solders.pubkey import Pubkey
from solders.keypair import Keypair

class TradingOperations:
    def __init__(self, trading_bot, telegram_bot, users):
        """
        Initialize trading operations.
        Args:
            trading_bot: TradingBot instance for blockchain interactions.
            telegram_bot: TelegramBot instance for sending messages.
            users: Dictionary of user data.
        """
        self.trading_bot = trading_bot
        self.telegram_bot = telegram_bot
        self.users = users
        self.trigger_api = "https://api.example.com/trigger/v1"  # Replace with actual Trigger API base URL
        self.ultra_api = "https://api.example.com/ultra/v1"  # Replace with actual Ultra Swap API base URL

    async def buy(self, chat_id, token_address, amount, fee_percentage=None):
        """
        Execute an instant buy order using Ultra Swap API.
        Args:
            chat_id: Telegram chat ID.
            token_address: Token address to buy (outputMint).
            amount: SOL amount to spend.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
        if fee_percentage not in FEE_PERCENTAGES:
            return False, f"Invalid fee percentage. Choose from {FEE_PERCENTAGES}."
        try:
            total_cost = amount * (1 + fee_percentage / 100)
            balance = await self.trading_bot.client.get_balance(self.trading_bot.keypair.pubkey())
            if balance.value / 1e9 < total_cost:
                return False, f"Insufficient balance: {balance.value / 1e9:.4f} {SOL_LOGO} available, {total_cost:.4f} {SOL_LOGO} needed."

            # Get order from Ultra Swap API
            async with aiohttp.ClientSession() as session:
                params = {
                    "inputMint": "So11111111111111111111111111111111111111112",  # SOL
                    "outputMint": token_address,
                    "amount": int(amount * 1e9),  # Convert SOL to lamports
                    "taker": str(self.trading_bot.keypair.pubkey())
                }
                async with session.get(f"{self.ultra_api}/order", params=params) as response:
                    if response.status != 200:
                        return False, f"Ultra Swap API error: Status {response.status}"
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Ultra Swap API."

                # Sign and execute order
                signed_tx = await self.trading_bot.sign_transaction(data)  # Assumes TradingBot can sign raw transaction data
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{self.ultra_api}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Ultra Swap execution failed: Status {execute_response.status}"
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")

            # Update user data
            self.users[chat_id]["last_buy_amount"] = amount
            self.users[chat_id]["last_token"] = token_address
            self.users[chat_id]["fee_percentage"] = fee_percentage
            self.users[chat_id]["portfolio_data"]["growth"].append(
                self.users[chat_id]["portfolio_data"]["growth"][-1] * (1 + 0.01)  # Placeholder growth
            )
            self.users[chat_id]["portfolio_data"]["timestamps"].append(time.time())

            return True, f"Bought {amount:.4f} {SOL_LOGO} worth of token {token_address} (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}"
        except Exception as e:
            return False, f"Error executing buy: {e}"

    async def sell(self, chat_id, token_address, amount, fee_percentage=None):
        """
        Execute an instant sell order using Ultra Swap API.
        Args:
            chat_id: Telegram chat ID.
            token_address: Token address to sell (inputMint).
            amount: Token amount to sell.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
        if fee_percentage not in FEE_PERCENTAGES:
            return False, f"Invalid fee percentage. Choose from {FEE_PERCENTAGES}."
        try:
            holdings = next(
                (r["amount"] for r in self.trading_bot.buy_records if r["token_address"] == token_address and r["sell_mcap"] is None),
                0
            )
            if amount > holdings:
                return False, f"Insufficient holdings: {holdings:.4f} available, {amount:.4f} requested."

            # Get order from Ultra Swap API
            async with aiohttp.ClientSession() as session:
                params = {
                    "inputMint": token_address,
                    "outputMint": "So11111111111111111111111111111111111111112",  # SOL
                    "amount": int(amount * 1e9),  # Assumes token uses 9 decimals; adjust if needed
                    "taker": str(self.trading_bot.keypair.pubkey())
                }
                async with session.get(f"{self.ultra_api}/order", params=params) as response:
                    if response.status != 200:
                        return False, f"Ultra Swap API error: Status {response.status}"
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Ultra Swap API."

                # Sign and execute order
                signed_tx = await self.trading_bot.sign_transaction(data)
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{self.ultra_api}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Ultra Swap execution failed: Status {execute_response.status}"
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")
                    mcap = await self.trading_bot.fetch_token_mcap(token_address) or 0

            # Generate PnL card for full sale
            if amount == holdings:
                await generate_pnl_card(
                    chat_id, token_address, mcap, self.trading_bot.buy_records,
                    self.telegram_bot.app.bot, self.users[chat_id]["history"]
                )

            return True, f"Sold {amount:.4f} of token {token_address} for {SOL_LOGO} (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}"
        except Exception as e:
            return False, f"Error executing sell: {e}"

    async def order(self, chat_id, token_address, amount, price, order_type, percentage, fee_percentage=None):
        """
        Set a limit order (buy or sell) using Trigger API.
        Args:
            chat_id: Telegram chat ID.
            token_address: Token address for the order.
            amount: Amount to buy/sell.
            price: Target price for the order.
            order_type: 'buy' or 'sell'.
            percentage: Percentage of holdings (0-100).
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
        if fee_percentage not in FEE_PERCENTAGES:
            return False, f"Invalid fee percentage. Choose from {FEE_PERCENTAGES}."
        if order_type not in ["buy", "sell"] or percentage <= 0 or percentage > 100:
            return False, "Invalid order type or percentage."
        try:
            if order_type == "sell":
                holdings = next(
                    (r["amount"] for r in self.trading_bot.buy_records if r["token_address"] == token_address and r["sell_mcap"] is None),
                    0
                )
                if amount * (percentage / 100) > holdings:
                    return False, f"Insufficient holdings for sell order: {holdings:.4f} available."

            # Create order using Trigger API
            async with aiohttp.ClientSession() as session:
                input_mint = "So11111111111111111111111111111111111111112" if order_type == "buy" else token_address
                output_mint = token_address if order_type == "buy" else "So11111111111111111111111111111111111111112"
                payload = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "maker": str(self.trading_bot.keypair.pubkey()),
                    "payer": str(self.trading_bot.keypair.pubkey()),
                    "params": {
                        "makingAmount": int(amount * 1e9),  # Adjust based on token decimals
                        "takingAmount": int(amount * price * 1e9),  # Price-based amount
                        "slippageBps": 50,  # 0.5% slippage; adjust as needed
                        "expiredAt": int(time.time() + 7 * 24 * 3600)  # 7-day expiry
                    },
                    "computeUnitPrice": "auto"
                }
                async with session.post(f"{self.trigger_api}/createOrder", json=payload) as response:
                    if response.status != 200:
                        return False, f"Trigger API error: Status {response.status}"
                    data = await response.json()
                    request_id = data.get("requestId")
                    if not request_id:
                        return False, "Failed to retrieve requestId from Trigger API."

                # Sign and execute order
                signed_tx = await self.trading_bot.sign_transaction(data)
                execute_payload = {
                    "signedTransaction": signed_tx,
                    "requestId": request_id
                }
                async with session.post(f"{self.trigger_api}/execute", json=execute_payload) as execute_response:
                    if execute_response.status != 200:
                        return False, f"Trigger API execution failed: Status {execute_response.status}"
                    result = await execute_response.json()
                    tx_hash = result.get("txHash")

            self.users[chat_id]["fee_percentage"] = fee_percentage
            return True, f"{order_type.capitalize()} limit order set for {amount:.4f} of {token_address} at price {price:.6f} (Fee: {fee_percentage}%). Tx: https://solscan.io/tx/{tx_hash}"
        except Exception as e:
            return False, f"Error setting limit order: {e}"

    async def transfer(self, chat_id, amount, destination, fee_percentage=None):
        """
        Transfer SOL to another wallet.
        Args:
            chat_id: Telegram chat ID.
            amount: SOL amount to transfer.
            destination: Destination wallet address.
            fee_percentage: Fee percentage from FEE_PERCENTAGES.
        Returns:
            (success: bool, message: str, tx_hash: str or None)
        """
        fee_percentage = fee_percentage if fee_percentage in FEE_PERCENTAGES else self.users[chat_id].get("fee_percentage", FEE_PERCENTAGES[0])
        if fee_percentage not in FEE_PERCENTAGES:
            return False, f"Invalid fee percentage. Choose from {FEE_PERCENTAGES}.", None
        try:
            # Validate destination address
            try:
                Pubkey.from_string(destination)
            except Exception:
                return False, "Invalid destination address.", None

            success, msg, tx_hash = await self.trading_bot.transfer_sol(amount, destination, fee_percentage=fee_percentage)
            if success:
                self.users[chat_id]["fee_percentage"] = fee_percentage
            return success, msg, tx_hash
        except Exception as e:
            return False, f"Error executing transfer: {e}", None