"""Payment verification scaffold.

All verification functions are stubs. Real implementation will depend on
chosen payment providers and API integrations.
"""
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

# --- Configuration from environment ---
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "0"))
SUBSCRIPTION_PRICE_USDT = float(os.getenv("SUBSCRIPTION_PRICE_USDT", "0"))
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "0"))
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
PAYMENT_RUB_DETAILS = os.getenv("PAYMENT_RUB_DETAILS", "")
PAYMENT_USDT_WALLETS = os.getenv("PAYMENT_USDT_WALLETS", "")

SUPPORTED_NETWORKS = ["TRC20", "ERC20", "BEP20", "TON", "Polygon", "Arbitrum", "SOL"]


def verify_rub_payment(user_id: int, amount: float, tx_id: str) -> Dict[str, Any]:
    """Verify RUB payment. Stub — always returns unverified."""
    logger.info("[PAYMENT] RUB verification requested: user=%s, amount=%s, tx=%s", user_id, amount, tx_id)
    return {"verified": False, "reason": "Автоматическая верификация RUB ещё не реализована."}


def verify_usdt_payment(user_id: int, amount: float, tx_hash: str, network: str) -> Dict[str, Any]:
    """Verify USDT payment on supported networks. Stub — always returns unverified."""
    if network not in SUPPORTED_NETWORKS:
        return {"verified": False, "reason": f"Сеть {network} не поддерживается. Доступные: {', '.join(SUPPORTED_NETWORKS)}"}
    logger.info("[PAYMENT] USDT verification requested: user=%s, amount=%s, tx=%s, network=%s",
                user_id, amount, tx_hash, network)
    return {"verified": False, "reason": "Автоматическая верификация USDT ещё не реализована."}


def get_payment_info() -> Dict[str, Any]:
    """Return payment details for display to user."""
    return {
        "rub_price": SUBSCRIPTION_PRICE_RUB,
        "usdt_price": SUBSCRIPTION_PRICE_USDT,
        "stars_price": SUBSCRIPTION_PRICE_STARS,
        "days": SUBSCRIPTION_DAYS,
        "rub_details": PAYMENT_RUB_DETAILS,
        "usdt_wallets": PAYMENT_USDT_WALLETS,
        "networks": SUPPORTED_NETWORKS,
    }


async def create_tg_wallet_invoice(user_id: int, amount_stars: int) -> Dict[str, Any]:
    """Create Telegram Stars invoice via Bot Payments API. Stub."""
    logger.info("[PAYMENT] TG Stars invoice requested: user=%s, stars=%s", user_id, amount_stars)
    return {"ok": False, "reason": "Telegram Stars оплата ещё не реализована."}


async def verify_tg_wallet_payment(user_id: int, payment_id: str) -> Dict[str, Any]:
    """Verify Telegram Stars payment. Stub."""
    logger.info("[PAYMENT] TG Stars verification requested: user=%s, payment_id=%s", user_id, payment_id)
    return {"verified": False, "reason": "Верификация Telegram Stars ещё не реализована."}
