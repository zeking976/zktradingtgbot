import os
from dotenv import load_dotenv

# Load from ~/t.env
dotenv_path = os.path.expanduser("~/t.env")
load_dotenv(dotenv_path=dotenv_path)

# Solana configuration
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_ENDPOINT = os.getenv("RPC_ENDPOINT")
RPC_WEBSOCKET_ENDPOINT = os.getenv("RPC_WEBSOCKET_ENDPOINT")

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

# Trading configuration
NUM_BUYS = int(os.getenv("NUM_BUYS", 10))
BUY_AMOUNT = float(os.getenv("BUY_AMOUNT", 0.1))
TRANSACTION_FEE = float(os.getenv("TRANSACTION_FEE", 0.001))

# Filter thresholds
MIN_LIQUIDITY_USD = float(os.getenv("MIN_LIQUIDITY_USD", 1000))
MAX_TOKEN_AGE_MINUTES = float(os.getenv("MAX_TOKEN_AGE_MINUTES", 60))
MAX_TOP_10_HOLDERS_PERCENT = float(os.getenv("MAX_TOP_10_HOLDERS_PERCENT", 50))

# Pump.fun program ID
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"