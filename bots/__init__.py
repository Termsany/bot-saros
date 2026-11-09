"""The strategies, one file each: their signals, cycle and public status. The order path they share — reconcile_live,
the single-leg and basket live adapters, close_live_position, place_order, the stop orders, the risk and activation
gates, state load/save — stays one copy in bot.py.

Every bot.py name a strategy uses is read as `bot.<name>` at call time, and bot.py re-exports each strategy's names:
mock.patch.object(bot, ...) in the tests and the CLI's rebinding of STATE_PATH / LOG_PATH reach the strategy code.
"""
