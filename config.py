# Configuration file for ZKET_TG_Tradingbot
from dotenv import load_dotenv
import os

# Load environment variables from t.env
load_dotenv('t.env')

# Solana RPC Endpoint (default, can be overridden in t.env)
RPC_ENDPOINT = os.getenv("RPC_ENDPOINT", "https://api.mainnet-beta.solana.com")

# Transaction Fee Percentages
FEE_PERCENTAGES = [1.0]  # Auto-calculated percentages

# Solana Logo Emoji
SOL_LOGO = "◎"

# Custom Name Update Cooldown (14 days in seconds)
NAME_UPDATE_COOLDOWN = 14 * 24 * 3600