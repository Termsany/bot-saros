import unittest

from backend.app.execution_safety import (
    AmbiguousFill,
    linear_contracts_from_margin,
    normalize_filled_contracts,
    authoritative_position_state,
    futures_net_pnl,
)


class ExecutionSafetyTests(unittest.TestCase):
    def test_net_pnl_uses_contract_size_fees_and_funding(self):
        self.assertAlmostEqual(
            futures_net_pnl(100, 110, 2, 0.5, "long", fee_rate=0.001, funding_pnl=-1),
            8.79,
        )

    def test_linear_margin_conversion_uses_contract_size(self):
        self.assertEqual(linear_contracts_from_margin(20, 5, 50_000, 0.001), 2.0)

    def test_inverse_markets_fail_closed(self):
        with self.assertRaises(ValueError):
            linear_contracts_from_margin(20, 5, 50_000, 1.0, inverse=True)

    def test_open_order_without_filled_is_ambiguous(self):
        with self.assertRaises(AmbiguousFill):
            normalize_filled_contracts({"status": "open", "amount": 4})

    def test_zero_fill_is_not_a_full_fill(self):
        with self.assertRaises(AmbiguousFill):
            normalize_filled_contracts({"status": "closed", "filled": 0, "amount": 4})

    def test_empty_position_response_is_inconclusive(self):
        self.assertEqual(authoritative_position_state([], "BTC/USDT:USDT"), "inconclusive")

    def test_matching_explicit_zero_is_authoritative_flat(self):
        self.assertEqual(
            authoritative_position_state(
                [{"symbol": "BTC/USDT:USDT", "contracts": 0}],
                "BTC/USDT:USDT",
            ),
            "flat",
        )

    def test_missing_symbol_is_inconclusive(self):
        self.assertEqual(
            authoritative_position_state(
                [{"symbol": "ETH/USDT:USDT", "contracts": 0}],
                "BTC/USDT:USDT",
            ),
            "inconclusive",
        )


if __name__ == "__main__":
    unittest.main()
