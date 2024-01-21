import hmac
import time

from hashlib import sha256
from modules import CEX, Logger
from utils.tools import helper
from config import CEX_WRAPED_ID, BINGX_NETWORKS_NAME
from general_settings import GLOBAL_NETWORK
from settings import (
    BINGX_WITHDRAW_NETWORK, BINGX_WITHDRAW_AMOUNT
)


class BingX(CEX, Logger):
    def __init__(self, client):
        self.client = client
        Logger.__init__(self)
        CEX.__init__(self, client, 'BingX')

        self.api_url = "https://open-api.bingx.com"
        self.headers = {
            "Content-Type": "application/json",
            "X-BX-APIKEY": self.api_key,
        }

    @staticmethod
    def parse_params(params):
        sorted_keys = sorted(params)
        params_str = "&".join(["%s=%s" % (x, params[x]) for x in sorted_keys])
        return params_str + "&timestamp=" + str(int(time.time() * 1000))

    def get_sign(self, payload: str = ""):
        try:
            secret_key_bytes = self.api_secret.encode('utf-8')
            signature = hmac.new(secret_key_bytes, payload.encode('utf-8'), sha256).hexdigest()

            return signature
        except Exception as error:
            raise RuntimeError(f'Bad signature for BingX request: {error}')

    async def get_balance(self, ccy: str):
        path = '/openApi/spot/v1/account/balance'

        params = {
            'timestamp': str(int(time.time() * 1000))
        }

        parse_params = self.parse_params(params)

        url = f"{self.api_url}{path}?{parse_params}&signature={self.get_sign(parse_params)}"
        data = await self.make_request(url=url, headers=self.headers, module_name='Balances Data', content_type=None)
        return [item for item in data['balances'] if item['asset'] == ccy][0]['free']

    async def deposit(self):
        pass

    async def get_currencies(self, ccy):
        path = '/openApi/wallets/v1/capital/config/getall'

        params = {
            'timestamp': str(int(time.time() * 1000))
        }

        parse_params = self.parse_params(params)

        url = f"{self.api_url}{path}?{parse_params}&signature={self.get_sign(parse_params)}"
        data = await self.make_request(url=url, headers=self.headers, module_name='Token info')
        return [item for item in data if item['coin'] == ccy]

    @helper
    async def withdraw(self, want_balance:float = 0, multi_withdraw_data:dict = None, transfer_mode:bool = False):
        if GLOBAL_NETWORK == 9:
            await self.client.initialize_account(check_balance=True)

        path = '/openApi/wallets/v1/capital/withdraw/apply'

        if multi_withdraw_data is None:
            network = BINGX_WITHDRAW_NETWORK
            amount = BINGX_WITHDRAW_AMOUNT
        else:
            network = multi_withdraw_data['network']
            amount = multi_withdraw_data['amount']

        ccy = BINGX_NETWORKS_NAME[network].split('-')[0]

        dst_chain_id = CEX_WRAPED_ID[network]
        withdraw_data = (await self.get_currencies(ccy))[0]['networkList']
        networks_data = {item['network']: {'withdrawEnable': item['withdrawEnable'],
                                           'withdrawFee': item['withdrawFee'],
                                           'withdrawMin': item['withdrawMin'],
                                           'withdrawMax': item['withdrawMax']} for item in withdraw_data}

        network_name = ' '.join(BINGX_NETWORKS_NAME[network].split('-')[1:])
        network_data = networks_data[network_name]

        if transfer_mode:
            amount = await self.get_balance(ccy)
        else:
            amount = want_balance if want_balance else await self.client.get_smart_amount(amount)

        self.logger_msg(
            *self.client.acc_info, msg=f"Withdraw {amount:.5f} {ccy} to {network_name}")

        if network_data['withdrawEnable']:
            address = f"0x{hex(self.client.address)[2:]:0>64}" if BINGX_WITHDRAW_NETWORK == 4 else self.client.address
            min_wd, max_wd = float(network_data['withdrawMin']), float(network_data['withdrawMax'])

            if min_wd <= amount <= max_wd:

                params = {
                    "address": address,
                    "amount": amount,
                    "coin": ccy,
                    "network": network_name,
                    "walletType": "1",
                }

                parse_params = self.parse_params(params)

                ccy = f"{ccy}.e" if network_name.split()[-1] == '(Bridged)' else ccy

                old_balance_on_dst = await self.client.wait_for_receiving(dst_chain_id, token_name=ccy,
                                                                          check_balance_on_dst=True)

                url = f"{self.api_url}{path}?{parse_params}&signature={self.get_sign(parse_params)}"

                await self.make_request(method='POST', url=url, headers=self.headers, module_name='Withdraw')

                self.logger_msg(*self.client.acc_info,
                                msg=f"Withdraw complete. Note: wait a little for receiving funds", type_msg='success')

                await self.client.wait_for_receiving(dst_chain_id, old_balance_on_dst, token_name=ccy)

                return True
            else:
                raise RuntimeError(f"Limit range for withdraw: {min_wd:.5f} {ccy} - {max_wd} {ccy}")
        else:
            raise RuntimeError(f"Withdraw from {network_name} is not available")
