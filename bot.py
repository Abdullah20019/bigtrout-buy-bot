import asyncio
import aiohttp
import logging
import os
from collections import deque
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIG =================
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TARGET_TOKEN_MINT = os.getenv("TARGET_TOKEN_MINT")
MIN_USD_VALUE = float(os.getenv("MIN_USD_VALUE") or 20)

IMAGE_PATH = r"C:\Users\pcp\solana-buy-bot\trout.jpg"

HELIUS_TX_API = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
DEXSCREENER_API = f"https://api.dexscreener.com/latest/dex/tokens/{TARGET_TOKEN_MINT}"

# =========================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("BigTrout")

seen_signatures = deque(maxlen=12000)


# ================= HELPERS =================
def format_number(n):
    for unit in ["", "K", "M", "B"]:
        if abs(n) < 1000:
            return f"{n:.1f}{unit}"
        n /= 1000
    return f"{n:.1f}T"


def volume_emojis(usd):
    return "🤖" * min(20, max(1, int(usd // 250)))


def whale_status(usd):
    if usd >= 10000:
        return "🐋 Mega Whale"
    if usd >= 5000:
        return "🐋 Whale"
    if usd >= 2000:
        return "🐬 Dolphin"
    if usd >= 1000:
        return "🦈 Shark"
    if usd >= 500:
        return "🐟 Big Fish"
    return "🐟 Fish"


def is_program(addr):
    return addr.endswith("11111111111111111111111111111111")


# ================= BOT =====================
class BigTroutBot:

    def __init__(self):
        self.session = None
        self.bot = Bot(TELEGRAM_BOT_TOKEN)
        self.token_price = 0
        self.market_cap = 0
        self.token_symbol = "BigTrout"
        self.sol_price = 0

    async def start(self):
        self.session = aiohttp.ClientSession()
        await self.update_prices()

        await self.bot.send_message(
            TELEGRAM_CHAT_ID,
            f"🚀 <b>{self.token_symbol} Buy Bot Online</b>\n\n"
            f"💰 Min Buy: ${MIN_USD_VALUE}\n"
            f"💵 Token: ${self.token_price:.8f}\n"
            f"💎 SOL: ${self.sol_price:.2f}\n"
            f"📊 MCap: ${format_number(self.market_cap)}",
            parse_mode=ParseMode.HTML
        )

        await self.monitor()

    # =============== PRICES =================
    async def update_prices(self):
        async with self.session.get(DEXSCREENER_API) as r:
            data = await r.json()
            pair = max(
                (p for p in data.get("pairs", []) if p.get("chainId") == "solana"),
                key=lambda x: x.get("liquidity", {}).get("usd", 0),
                default=None
            )
            if pair:
                self.token_price = float(pair.get("priceUsd", 0))
                self.market_cap = float(pair.get("marketCap", 0))
                self.token_symbol = pair.get("baseToken", {}).get("symbol", "BigTrout")

        async with self.session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        ) as r:
            self.sol_price = (await r.json())["solana"]["usd"]

    # =============== MONITOR =================
    async def monitor(self):
        while True:
            try:
                txs = await self.fetch_transactions()
                for tx in txs:
                    sig = tx["signature"]
                    if sig in seen_signatures:
                        continue

                    seen_signatures.append(sig)
                    result = self.analyze_transaction(tx)

                    if result and result["usd"] >= MIN_USD_VALUE:
                        await self.send_alert(result)
                        await asyncio.sleep(1.2)

                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)

    # =============== FETCH ===================
    async def fetch_transactions(self):
        payload = {
            "query": {"tokenMint": TARGET_TOKEN_MINT},
            "limit": 50
        }
        async with self.session.post(HELIUS_TX_API, json=payload) as r:
            return await r.json()

    # =============== ANALYZE =================
    def analyze_transaction(self, tx):
        token_transfers = [
            t for t in tx.get("tokenTransfers", [])
            if t["mint"] == TARGET_TOKEN_MINT
        ]
        if not token_transfers:
            return None

        account_changes = {}
        for acc in tx.get("accountData", []):
            account_changes[acc["account"]] = acc["nativeBalanceChange"] / 1e9

        # find wallet with max SOL outflow
        buyer, sol_spent = None, 0
        for addr, delta in account_changes.items():
            if delta < sol_spent and not is_program(addr):
                sol_spent = delta
                buyer = addr

        sol_spent = abs(sol_spent)
        if sol_spent <= 0.001:
            return None

        # confirm token inflow (BUY)
        token_in = any(
            t["toUserAccount"] == buyer and t["tokenAmount"] > 0
            for t in token_transfers
        )
        if not token_in:
            return None

        usd = sol_spent * self.sol_price
        tokens = usd / self.token_price if self.token_price else 0

        return {
            "buyer": buyer,
            "sol": sol_spent,
            "usd": usd,
            "tokens": tokens,
            "signature": tx["signature"],
            "timestamp": tx.get("timestamp") or int(datetime.now().timestamp())
        }

    # =============== ALERT ===================
    async def send_alert(self, r):
        caption = (
            f"🛒 <b>{self.token_symbol} BUY</b>\n\n"
            f"{volume_emojis(r['usd'])}\n\n"
            f"💸 <b>{r['sol']:.3f} SOL (${r['usd']:,.2f})</b>\n"
            f"🐟 {format_number(r['tokens'])} {self.token_symbol}\n"
            f"👤 <code>{r['buyer'][:12]}…{r['buyer'][-4:]}</code>\n"
            f"{whale_status(r['usd'])}\n"
            f"📈 ${self.token_price:.8f}\n"
            f"<i>{datetime.fromtimestamp(r['timestamp']).strftime('%I:%M %p')}</i>\n"
            f"<a href='https://solscan.io/tx/{r['signature']}'>Txn</a>"
        )

        if os.path.isfile(IMAGE_PATH):
            with open(IMAGE_PATH, "rb") as img:
                await self.bot.send_photo(
                    TELEGRAM_CHAT_ID,
                    photo=img,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            await self.bot.send_message(
                TELEGRAM_CHAT_ID,
                caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )


# =============== MAIN ======================
async def main():
    bot = BigTroutBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())