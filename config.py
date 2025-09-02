# Configuration file for ZKET_TG_Tradingbot
from dotenv import load_dotenv
import os

# Load environment variables from t.env
load_dotenv('t.env')

# Solana RPC Endpoint (default, can be overridden in t.env)
RPC_ENDPOINT = os.getenv("RPC_ENDPOINT", "https://api.mainnet-beta.solana.com")

# Default Transaction Fees (overridable in t.env)
GAS_BUFFER_DEFAULT = float(os.getenv("GAS_BUFFER", 0.001))  # Default gas buffer in SOL
CONGESTION_FEE_DEFAULT = float(os.getenv("CONGESTION_FEE", 0.001))  # Default congestion fee in SOL
FEE_PERCENTAGES = [0.5, 1.0, 2.0, 3.0, 4.0]  # Auto-calculated percentages
# Solana Logo Emoji
SOL_LOGO = "◎"
# Custom Name Update Cooldown (14 days in seconds)
NAME_UPDATE_COOLDOWN = 14 * 24 * 3600