"""Concurrency regression tests for Supply Chain Telegram mutation handlers."""
import asyncio
import unittest
from unittest.mock import patch

import supply_chain


class SupplyChainMutationSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Each isolated test owns its event loop.
        supply_chain._SC_MUTATION_LOCK = asyncio.Lock()

    async def test_callback_excel_and_text_handlers_share_one_mutation_gate(self):
        active = 0
        maximum_active = 0

        async def fake_handler(*args):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return True

        with patch.object(supply_chain, "_callback", fake_handler), \
             patch.object(supply_chain, "_handle_excel_document", fake_handler), \
             patch.object(supply_chain, "_text", fake_handler):
            results = await asyncio.gather(
                supply_chain._serialized_callback(None, None),
                supply_chain._serialized_excel_document(None, None),
                supply_chain._serialized_text(None, None),
            )

        self.assertEqual(maximum_active, 1)
        self.assertEqual(results, [None, None, True])


if __name__ == "__main__":
    unittest.main()
