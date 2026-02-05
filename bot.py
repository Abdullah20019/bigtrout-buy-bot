import asyncio
import aiohttp
import logging
import os
import ssl
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

# Configuration
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TARGET_TOKEN_MINT = os.getenv('TARGET_TOKEN_MINT')
MIN_USD_VALUE = float(os.getenv('MIN_USD_VALUE', 20))

# FIXED: Image path - change this to your actual file name
IMAGE_PATH = r"C:\Users\pcp\solana-buy-bot\trout.jpg"

HELIUS_ENHANCED_API = f"https://api.helius.xyz/v0/addresses/{TARGET_TOKEN_MINT}/transactions"
DEXSCREENER_API = f"https://api.dexscreener.com/latest/dex/tokens/{TARGET_TOKEN_MINT}"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

seen_signatures = set()


def format_number(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    else:
        return f"{num:.0f}"


def get_volume_emojis(usd_value):
    if usd_value >= 10000:
        return "🤖" * 20
    elif usd_value >= 5000:
        return "🤖" * 15
    elif usd_value >= 2000:
        return "🤖" * 10
    elif usd_value >= 1000:
        return "🤖" * 7
    elif usd_value >= 500:
        return "🤖" * 5
    elif usd_value >= 200:
        return "🤖" * 3
    else:
        return "🤖"


def get_whale_status(usd_value):
    if usd_value >= 10000:
        return "🐋 Mega Whale"
    elif usd_value >= 5000:
        return "🐋 Whale"
    elif usd_value >= 2000:
        return "🐬 Dolphin"
    elif usd_value >= 1000:
        return "🦈 Shark"
    elif usd_value >= 500:
        return "🐟 Big Fish"
    else:
        return "🐟 Fish"


class BigTroutBot:
    """FINAL WORKING VERSION"""
    
    def __init__(self):
        self.session = None
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.stats = {'buys': 0, 'volume': 0.0, 'checked': 0, 'errors': 0}
        self.token_price = 0.0
        self.market_cap = 0.0
        self.token_symbol = "BigTrout"
        self.sol_price = 105.0
        
    async def start(self):
        logger.info("=" * 70)
        logger.info("🚀 BIGTROUT BUY BOT - Final Version")
        logger.info("=" * 70)
        logger.info(f"📊 Token: {TARGET_TOKEN_MINT}")
        logger.info(f"💰 Min: ${MIN_USD_VALUE}")
        logger.info(f"📁 Image Path: {IMAGE_PATH}")
        logger.info(f"📁 Image Exists: {os.path.exists(IMAGE_PATH)}")
        logger.info("=" * 70)
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = aiohttp.ClientSession(connector=connector)
        
        await self.update_prices()
        
        try:
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=(
                    f"🚀 <b>{self.token_symbol} Bot Online!</b>\n\n"
                    f"📊 <code>{TARGET_TOKEN_MINT[:16]}...</code>\n"
                    f"💰 Min: ${MIN_USD_VALUE}\n"
                    f"💵 Token: ${self.token_price:.8f}\n"
                    f"💎 SOL: ${self.sol_price:.2f}\n"
                    f"📊 MCap: ${format_number(self.market_cap)}\n\n"
                    f"✅ Only real buys tracked\n"
                    f"🎨 Image: {'✅ Found' if os.path.exists(IMAGE_PATH) else '❌ Not Found'}"
                ),
                parse_mode=ParseMode.HTML
            )
            logger.info("📱 Started\n")
        except Exception as e:
            logger.error(f"TG: {e}\n")
        
        try:
            await self.monitor()
        except KeyboardInterrupt:
            logger.info(f"\n⏹️ Stopped")
            logger.info(f"📊 Stats: {self.stats}")
        finally:
            if self.session:
                await self.session.close()
    
    async def update_prices(self):
        try:
            async with self.session.get(DEXSCREENER_API, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if 'pairs' in data and len(data['pairs']) > 0:
                        pair = data['pairs'][0]
                        
                        self.token_price = float(pair.get('priceUsd', 0))
                        self.market_cap = float(pair.get('marketCap', 0))
                        
                        base_token = pair.get('baseToken', {})
                        self.token_symbol = base_token.get('symbol', 'BigTrout')
                        
                        logger.info(f"💵 Token: ${self.token_price:.8f} | MCap: ${format_number(self.market_cap)}")
        except Exception as e:
            logger.warning(f"Token price: {e}")
            if self.token_price == 0:
                self.token_price = 0.004
                self.market_cap = 4000000
        
        try:
            coingecko_api = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with self.session.get(coingecko_api, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'solana' in data and 'usd' in data['solana']:
                        self.sol_price = float(data['solana']['usd'])
                        logger.info(f"💎 SOL: ${self.sol_price:.2f}")
                        return
        except:
            pass
        
        if self.sol_price == 0:
            self.sol_price = 105.0
        logger.info(f"💎 SOL: ${self.sol_price:.2f}")
    
    async def monitor(self):
        logger.info("👀 Monitoring...\n")
        
        try:
            initial_txs = await self.fetch_transactions()
            if initial_txs:
                for tx in initial_txs[:10]:
                    sig = tx.get('signature')
                    if sig:
                        seen_signatures.add(sig)
                logger.info(f"📍 Baseline: {len(seen_signatures)} signatures\n")
        except Exception as e:
            logger.error(f"Initial: {e}")
        
        await asyncio.sleep(3)
        
        price_update_counter = 0
        error_count = 0
        
        while True:
            try:
                price_update_counter += 1
                if price_update_counter >= 10:
                    await self.update_prices()
                    price_update_counter = 0
                
                txs = await self.fetch_transactions()
                
                if not txs:
                    await asyncio.sleep(5)
                    continue
                
                new_count = 0
                buy_count = 0
                
                for tx in txs:
                    try:
                        sig = tx.get('signature')
                        
                        if not sig or sig in seen_signatures:
                            continue
                        
                        seen_signatures.add(sig)
                        new_count += 1
                        self.stats['checked'] += 1
                        
                        if self.is_liquidity(tx):
                            continue
                        
                        result = self.analyze_transaction(tx)
                        
                        if result['is_buy'] and result['usd'] >= MIN_USD_VALUE:
                            buy_count += 1
                            self.stats['buys'] += 1
                            self.stats['volume'] += result['usd']
                            
                            logger.info(f"🟢 ${result['usd']:,.2f} | {result['tokens_formatted']} {self.token_symbol}")
                            
                            await self.send_alert(result)
                            await asyncio.sleep(1.5)
                    
                    except Exception as e:
                        self.stats['errors'] += 1
                        logger.error(f"TX error: {e}")
                        continue
                
                if new_count > 0:
                    logger.info(f"✅ {new_count} new | {buy_count} buys\n")
                
                if len(seen_signatures) > 10000:
                    old = list(seen_signatures)[:5000]
                    for s in old:
                        seen_signatures.discard(s)
                
                error_count = 0
                await asyncio.sleep(3)
                
            except Exception as e:
                error_count += 1
                self.stats['errors'] += 1
                logger.error(f"Monitor error: {e}")
                
                if error_count > 10:
                    logger.error("Restarting session...")
                    await self.session.close()
                    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context())
                    self.session = aiohttp.ClientSession(connector=connector)
                    error_count = 0
                
                await asyncio.sleep(10)
    
    def is_liquidity(self, tx):
        try:
            tx_type = str(tx.get('type', '')).upper()
            description = str(tx.get('description', '')).lower()
            
            if any(kw in tx_type for kw in ['LIQUIDITY', 'LP_']):
                return True
            
            if any(kw in description for kw in ['add liquidity', 'remove liquidity']):
                return True
            
            return False
        except:
            return False
    
    async def fetch_transactions(self):
        params = {
            'api-key': HELIUS_API_KEY,
            'limit': 50
        }
        
        try:
            async with self.session.get(HELIUS_ENHANCED_API, params=params, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else []
                return []
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return []
    
    def analyze_transaction(self, tx):
        try:
            sig = tx.get('signature', '')
            timestamp = tx.get('timestamp', 0)
            
            token_transfers = tx.get('tokenTransfers', [])
            
            if not token_transfers:
                return self._empty()
            
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                
                if mint != TARGET_TOKEN_MINT:
                    continue
                
                from_addr = transfer.get('fromUserAccount', '')
                to_addr = transfer.get('toUserAccount', '')
                
                if to_addr and from_addr and to_addr != from_addr:
                    sol_spent = self._calculate_sol_spent(tx, to_addr)
                    
                    if sol_spent > 0:
                        usd = sol_spent * self.sol_price
                        
                        if usd > 0 and self.token_price > 0:
                            expected_tokens = usd / self.token_price
                            tokens_formatted = format_number(expected_tokens)
                            
                            return {
                                'is_buy': True,
                                'usd': usd,
                                'sol': sol_spent,
                                'tokens': expected_tokens,
                                'tokens_formatted': tokens_formatted,
                                'buyer': to_addr,
                                'signature': sig,
                                'timestamp': timestamp,
                                'source': 'DEX'
                            }
            
            return self._empty()
            
        except Exception as e:
            logger.error(f"Analyze: {e}")
            return self._empty()
    
    def _calculate_sol_spent(self, tx, buyer_addr):
        try:
            account_data = tx.get('accountData', [])
            
            for account in account_data:
                addr = account.get('account', '')
                
                if addr == buyer_addr:
                    balance_change = account.get('nativeBalanceChange', 0)
                    
                    if balance_change < 0:
                        sol = abs(balance_change) / 1e9
                        if sol > 0.001:
                            return sol
                    elif balance_change > 0:
                        return 0
            
            max_sol = 0
            for account in account_data:
                balance_change = account.get('nativeBalanceChange', 0)
                
                if balance_change < 0:
                    sol = abs(balance_change) / 1e9
                    if sol > 0.001:
                        max_sol = max(max_sol, sol)
            
            if max_sol > 0:
                return max_sol
            
            native_transfers = tx.get('nativeTransfers', [])
            total_sol = 0
            
            for transfer in native_transfers:
                amount = transfer.get('amount', 0)
                if amount > 0:
                    total_sol += amount / 1e9
            
            if total_sol > 0.001:
                return total_sol
            
            return 0
            
        except Exception as e:
            logger.error(f"SOL calc: {e}")
            return 0
    
    def _empty(self):
        return {
            'is_buy': False,
            'usd': 0,
            'sol': 0,
            'tokens': 0,
            'tokens_formatted': '0',
            'buyer': '',
            'signature': '',
            'timestamp': 0,
            'source': ''
        }
    
    async def send_alert(self, result):
        try:
            sig = result['signature']
            usd = result['usd']
            sol = result['sol']
            tokens_formatted = result['tokens_formatted']
            buyer = result['buyer']
            timestamp = result['timestamp']
            
            volume_emojis = get_volume_emojis(usd)
            whale_status = get_whale_status(usd)
            
            dt = datetime.fromtimestamp(timestamp)
            time_str = dt.strftime('%I:%M %p')
            
            caption = f"""
🛒 <b>{self.token_symbol} Buy!</b>

{volume_emojis}

💸 <b>{sol:.3f} SOL (${usd:,.2f})</b>
🐟 <b>{tokens_formatted} {self.token_symbol}</b>
👤 <code>{buyer[:12]}</code>...{buyer[-4:]} | <a href="https://solscan.io/tx/{sig}">Txn</a>
{whale_status}
📈 Price: ${self.token_price:.8f}
📊 Market Cap: ${format_number(self.market_cap)}

<i>{time_str}</i>
"""
            
            # Try to send with image
            if os.path.isfile(IMAGE_PATH):
                try:
                    with open(IMAGE_PATH, 'rb') as photo_file:
                        await self.bot.send_photo(
                            chat_id=TELEGRAM_CHAT_ID,
                            photo=photo_file,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    logger.info("✅ Alert sent with image")
                    return
                except Exception as photo_error:
                    logger.error(f"Image send error: {photo_error}")
            
            # Fallback to text only
            logger.warning(f"Sending without image (Image path: {IMAGE_PATH})")
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            logger.info("✅ Alert sent (text only)")
            
        except Exception as e:
            if "Flood control" not in str(e):
                logger.error(f"Alert error: {e}")


async def main():
    bot = BigTroutBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
