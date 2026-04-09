"""Tests for services.payment_service — payment verification stubs."""
import unittest
from services.payment_service import get_payment_info, verify_rub_payment, verify_usdt_payment


class TestPaymentService(unittest.TestCase):

    def test_get_payment_info_returns_dict(self):
        info = get_payment_info()
        for key in ("rub_price", "usdt_price", "days", "rub_details", "usdt_wallets", "networks"):
            self.assertIn(key, info)

    def test_verify_rub_payment_stub(self):
        result = verify_rub_payment(user_id=1, amount=500.0, tx_id="TX123")
        self.assertFalse(result["verified"])

    def test_verify_usdt_payment_stub(self):
        result = verify_usdt_payment(user_id=1, amount=10.0, tx_hash="0xabc", network="TRC20")
        self.assertFalse(result["verified"])

    def test_verify_usdt_unsupported_network(self):
        result = verify_usdt_payment(user_id=1, amount=10.0, tx_hash="0xabc", network="FAKE")
        self.assertFalse(result["verified"])
        self.assertIn("не поддерживается", result["reason"])


if __name__ == "__main__":
    unittest.main()
