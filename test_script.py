# test_script.py
import asyncio
import aiohttp
import cred
from submit_order import find_what_to_buy
from order_utils import get_expiration, get_tp_value
from data_acquisition import read_config
from datetime import datetime

zones = {'PDHL_1': (702, 525.87, 505.06), 'support_1': (701, 536.9, 537.64), 'PDHL_2': (624, 554.81, 553.68), 'PDHL_3': (598, 547.97, 546.87), 'PDHL_5': (27, 598.2, 597.34), 'resistance_1': (494, 576.41, 575.805), 'resistance_2': (364, 565.02, 564.19), 'support_2': (301, 549.68, 551.16), 'resistance_3': (166, 580.1736, 579.35), 'support_3': (98, 585.97, 587.48), 'support_4': (22, 591.8556, 592.54)}

async def test_find_what_to_buy():
    symbol = "SPY"
    cp = "put"  # or "call"
    num_out_of_the_money = read_config('NUM_OUT_OF_MONEY')
    expiration_date = get_expiration(read_config('OPTION_EXPIRATION_DTE'))

    candle_zone_type = "above PDHL_1 PDH"
    TP_value = get_tp_value(1, candle_zone_type, cp, zones)

    headers = {
        "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            result = await find_what_to_buy(
                symbol, cp, num_out_of_the_money, expiration_date, TP_value, session, headers
            )

            if result:
                strike, ask = result
                print(f"\n✅ Found contract → Strike: {strike}, Ask: {ask}\n")
            else:
                print("\n❌ No suitable contract found within the price ranges.\n")
        finally:
            await session.close()
            await asyncio.sleep(0.1)  # Ensures transport is properly cleaned up

if __name__ == "__main__":
    asyncio.run(test_find_what_to_buy())
