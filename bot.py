import asyncio
import io
import logging
import os
import random
import time
from urllib.parse import urlsplit

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "-1003867089540"))
ALERT_TOPIC_ID = int(os.getenv("ALERT_TOPIC_ID", "17135"))
ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", "500000"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "8") or "8")
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com").rstrip("/")
BINANCE_PROXY_URLS_RAW = os.getenv("BINANCE_PROXY_URLS", "")
BINANCE_PROXY_URL = (
    os.getenv("BINANCE_PROXY_URL")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("HTTP_PROXY")
    or os.getenv("ALL_PROXY")
    or ""
).strip()
BINANCE_DIRECT_FALLBACK = os.getenv("BINANCE_DIRECT_FALLBACK", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PUBLIC_PROXY_FALLBACK = os.getenv("PUBLIC_PROXY_FALLBACK", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

WATCHLIST = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "UNI",
    "FIL",
    "DOT",
    "LTC",
    "LINK",
    "XLM",
    "ATOM",
    "ZIL",
]

LEVERAGE_DIST = {
    2: 0.05,
    3: 0.08,
    5: 0.15,
    10: 0.25,
    20: 0.22,
    50: 0.15,
    100: 0.10,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

http = requests.Session()
http.trust_env = False
http.headers.update({"User-Agent": "liqbot/1.0"})

_proxy_cache = []


def _normalize_proxy_url(proxy_url: str) -> str:
    proxy_url = proxy_url.strip().strip("'").strip('"')
    if proxy_url and "://" not in proxy_url:
        proxy_url = f"http://{proxy_url}"
    return proxy_url.rstrip("/")


def _proxy_config(proxy_url: str):
    normalized = _normalize_proxy_url(proxy_url)
    return {"http": normalized, "https": normalized}


def _proxy_label(proxy_url: str) -> str:
    parsed = urlsplit(_normalize_proxy_url(proxy_url))
    host = parsed.hostname or "proxy"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    auth = "***:***@" if (parsed.username or parsed.password) else ""
    return f"{parsed.scheme or 'http'}://{auth}{host}"


def _load_configured_proxies():
    raw_values = [BINANCE_PROXY_URLS_RAW, BINANCE_PROXY_URL]
    proxies = []
    seen = set()

    for raw_value in raw_values:
        if not raw_value:
            continue
        prepared = raw_value.replace(",", "\n").replace(";", "\n")
        for part in prepared.splitlines():
            normalized = _normalize_proxy_url(part)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            proxies.append(normalized)

    return proxies


CONFIGURED_PROXY_URLS = _load_configured_proxies()


def refresh_proxies():
    global _proxy_cache

    if not PUBLIC_PROXY_FALLBACK:
        return

    try:
        r = http.get(
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=all",
            timeout=5,
        )
        r.raise_for_status()
        proxies = [f"http://{p}" for p in r.text.strip().split("\n")[:20] if p.strip()]
        _proxy_cache = proxies
        logger.info("Loaded %s public proxies", len(proxies))
    except Exception as e:
        logger.warning("Proxy refresh failed: %s", e)


def _binance_attempts(include_public: bool = True):
    attempts = []

    configured_proxies = list(CONFIGURED_PROXY_URLS)
    if len(configured_proxies) > 1:
        configured_proxies = random.sample(configured_proxies, len(configured_proxies))

    for proxy_url in configured_proxies:
        attempts.append((f"configured proxy {_proxy_label(proxy_url)}", _proxy_config(proxy_url)))

    if not configured_proxies or BINANCE_DIRECT_FALLBACK:
        attempt_name = "direct fallback" if configured_proxies else "direct"
        attempts.append((attempt_name, None))

    if include_public and PUBLIC_PROXY_FALLBACK:
        if not _proxy_cache:
            refresh_proxies()
        for proxy_url in random.sample(_proxy_cache, min(3, len(_proxy_cache))):
            attempts.append((f"public proxy {_proxy_label(proxy_url)}", _proxy_config(proxy_url)))

    return attempts


def _format_error(error: Exception) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:140]


def _probe_binance():
    url = f"{BINANCE_BASE_URL}/fapi/v1/ping"
    results = []

    for attempt_name, proxies in _binance_attempts(include_public=False):
        started = time.monotonic()
        try:
            r = http.get(url, proxies=proxies, timeout=REQUEST_TIMEOUT)
            elapsed = time.monotonic() - started
            r.raise_for_status()
            results.append(
                {
                    "attempt": attempt_name,
                    "ok": True,
                    "status": r.status_code,
                    "elapsed": elapsed,
                }
            )
        except Exception as e:
            elapsed = time.monotonic() - started
            results.append(
                {
                    "attempt": attempt_name,
                    "ok": False,
                    "elapsed": elapsed,
                    "error": _format_error(e),
                }
            )

    return results


def _proxy_summary_lines():
    lines = [
        "🌐 <b>Binance transport</b>",
        f"Base URL: <code>{BINANCE_BASE_URL}</code>",
        f"Timeout: <code>{REQUEST_TIMEOUT:.1f}s</code>",
        f"Direct fallback: <code>{'on' if BINANCE_DIRECT_FALLBACK else 'off'}</code>",
        f"Public proxy fallback: <code>{'on' if PUBLIC_PROXY_FALLBACK else 'off'}</code>",
    ]

    if CONFIGURED_PROXY_URLS:
        lines.append(f"Configured proxies: <code>{len(CONFIGURED_PROXY_URLS)}</code>")
        for idx, proxy_url in enumerate(CONFIGURED_PROXY_URLS, start=1):
            lines.append(f"{idx}. <code>{_proxy_label(proxy_url)}</code>")
    else:
        lines.append("Configured proxies: <code>0</code>")

    return lines


def _probe_summary_lines(results):
    lines = ["🩺 <b>Binance diagnostic</b>", f"Ping URL: <code>{BINANCE_BASE_URL}/fapi/v1/ping</code>"]

    for item in results:
        icon = "✅" if item["ok"] else "❌"
        if item["ok"]:
            detail = f"HTTP {item['status']} in {item['elapsed']:.2f}s"
        else:
            detail = f"{item['error']} after {item['elapsed']:.2f}s"
        lines.append(f"{icon} <code>{item['attempt']}</code> - {detail}")

    return lines


def _transport_label():
    if CONFIGURED_PROXY_URLS:
        label = f"{len(CONFIGURED_PROXY_URLS)} configured proxies"
    else:
        label = "direct"
    if BINANCE_DIRECT_FALLBACK and CONFIGURED_PROXY_URLS:
        label = f"{label} + direct fallback"
    if PUBLIC_PROXY_FALLBACK:
        label = f"{label} + public proxy fallback"
    return label


def binance_get(path, params=None):
    url = f"{BINANCE_BASE_URL}{path}"
    last_error = None

    for attempt_name, proxies in _binance_attempts():
        try:
            r = http.get(url, params=params, proxies=proxies, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            if not r.text:
                raise ValueError("empty response")
            return r.json()
        except Exception as e:
            last_error = e
            logger.warning("Binance request failed via %s: %s", attempt_name, e)

    logger.error("Binance request failed for %s: %s", url, last_error)
    return None


def get_price(sym: str) -> float:
    data = binance_get("/fapi/v1/ticker/price", {"symbol": sym})
    if data and "price" in data:
        return float(data["price"])

    r = http.get(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "linear", "symbol": sym},
        timeout=10,
    )
    r.raise_for_status()
    return float(r.json()["result"]["list"][0]["lastPrice"])


def get_oi(sym: str, price: float) -> float:
    data = binance_get("/fapi/v1/openInterest", {"symbol": sym})
    if data and "openInterest" in data:
        return float(data["openInterest"]) * price

    try:
        r = http.get(
            "https://api.bybit.com/v5/market/open-interest",
            params={"category": "linear", "symbol": sym, "intervalTime": "1h", "limit": 1},
            timeout=10,
        )
        d = r.json()
        if d.get("result") and d["result"].get("list"):
            return float(d["result"]["list"][0]["openInterest"]) * price
    except Exception:
        pass

    return price * 1_000_000


def _dec(p: float) -> int:
    if p >= 1000:
        return 1
    if p >= 10:
        return 2
    if p >= 0.01:
        return 4
    return 6


def build_df(coin: str):
    sym = coin.upper().replace("USDT", "").replace("BUSD", "") + "USDT"
    price = get_price(sym)
    oi = get_oi(sym, price)
    rows = []

    for lev, share in LEVERAGE_DIST.items():
        side_liq = oi * share
        for i in range(1, 31):
            lp = price * (1 - 0.4 * i / 30) * (1 - 1 / lev)
            sp = price * (1 + 0.4 * i / 30) * (1 + 1 / lev)
            if lp > 0:
                rows.append({"price": lp, "usd_value": side_liq / 30, "type": "long"})
            rows.append({"price": sp, "usd_value": side_liq / 30, "type": "short"})

    df = pd.DataFrame(rows)
    df["price"] = df["price"].round(_dec(price))
    grouped = df.groupby(["price", "type"], as_index=False)["usd_value"].sum()
    return grouped, price, sym


def build_chart(df: pd.DataFrame, symbol: str, price: float) -> io.BytesIO:
    bg = "#131722"
    grid = "#2a2e39"
    green = "#089981"
    red = "#f23645"
    gold = "#f5c518"
    text = "#d1d4dc"

    df = df.sort_values("price").reset_index(drop=True)
    lo = df[df["type"] == "long"]
    sh = df[df["type"] == "short"]

    price_range = df["price"].max() - df["price"].min()
    levels = len(df["price"].unique())
    bar_height = (price_range / max(levels, 1)) * 0.75
    dec = _dec(df["price"].max())

    fig, ax = plt.subplots(figsize=(12, max(8, levels * 0.18)))
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    ax.barh(lo["price"], lo["usd_value"], height=bar_height, color=red, alpha=0.92)
    ax.barh(sh["price"], sh["usd_value"], height=bar_height, color=green, alpha=0.92)
    ax.axhline(
        y=price,
        color=gold,
        linewidth=1.2,
        linestyle="--",
        alpha=0.9,
        label=f"Price: {price:,.{dec}f}",
    )

    ax.grid(axis="x", color=grid, linestyle="--", alpha=0.5, linewidth=0.7)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_edgecolor(grid)

    ax.tick_params(colors=text, labelsize=9, length=3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.{dec}f}"))
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily("monospace")
        label.set_color(text)

    ax.set_xlabel("USD Value", color=text, fontsize=11, fontfamily="monospace")
    ax.set_ylabel("Price", color=text, fontsize=11, fontfamily="monospace")
    ax.set_title(
        f"Predicted Liquidation Levels - {symbol}",
        color=text,
        fontsize=13,
        pad=14,
        fontfamily="monospace",
    )
    ax.legend(facecolor=bg, edgecolor=grid, labelcolor=text, fontsize=9, loc="upper right")

    plt.tight_layout(pad=1.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=bg)
    buf.seek(0)
    plt.close(fig)
    return buf


@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    coins = "\n".join([f"  <code>/liq {s}</code>" for s in WATCHLIST])
    await message.answer(
        "📊 <b>Liquidation Map Bot</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 Отправь <code>/liq BTC</code> или <code>/liq BTCUSDT</code>\n\n"
        "🩺 Проверка сети: <code>/net</code>\n"
        "🌐 Текущие прокси: <code>/proxy</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗂 <b>Доступные монеты:</b>\n{coins}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 Зелёный — шорты ликвидируются → цена растёт\n"
        "🔴 Красный — лонги ликвидируются → цена падает\n"
        "🟡 Линия — текущая цена\n"
        "⚡ Автоалерт свыше <b>$500,000</b>",
        parse_mode="HTML",
    )


@dp.message(Command("liq"))
async def cmd_liq(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.reply("⚠️ Пример: <code>/liq BTC</code>", parse_mode="HTML")
        return

    wait = await message.reply(
        f"⏳ Загружаю данные для {parts[1].upper()}...",
        parse_mode="HTML",
    )

    try:
        df, price, sym = build_df(parts[1])
        buf = build_chart(df, sym, price)
        ms = df[df["type"] == "short"]["usd_value"].max()
        ml = df[df["type"] == "long"]["usd_value"].max()
        dec = _dec(price)

        await bot.send_photo(
            message.chat.id,
            photo=BufferedInputFile(buf.read(), filename=f"liq_{sym}.png"),
            caption=(
                f"📊 <b>Liquidation Map — {sym}</b>\n\n"
                f"💰 Цена: <b>${price:,.{dec}f}</b>\n"
                f"🟢 Шорт-зона: <b>${ms:,.0f}</b>\n"
                f"🔴 Лонг-зона:  <b>${ml:,.0f}</b>"
            ),
            parse_mode="HTML",
            message_thread_id=message.message_thread_id,
        )
    except Exception as e:
        logger.exception(e)
        await message.reply(f"❌ Ошибка получения данных: {e}")
    finally:
        await wait.delete()


@dp.message(Command("proxy"))
async def cmd_proxy(message: types.Message):
    await message.answer("\n".join(_proxy_summary_lines()), parse_mode="HTML")


@dp.message(Command("net"))
async def cmd_net(message: types.Message):
    wait = await message.reply("⏳ Проверяю доступ к Binance...", parse_mode="HTML")

    try:
        results = await asyncio.to_thread(_probe_binance)
        await message.reply("\n".join(_probe_summary_lines(results)), parse_mode="HTML")
    except Exception as e:
        logger.exception(e)
        await message.reply(f"❌ Диагностика не удалась: {e}")
    finally:
        await wait.delete()


async def auto_alert_loop():
    await asyncio.sleep(15)
    refresh_proxies()

    while True:
        for coin in WATCHLIST:
            try:
                df, price, sym = build_df(coin)
                ms = df[df["type"] == "short"]["usd_value"].max()
                ml = df[df["type"] == "long"]["usd_value"].max()

                if max(ms, ml) >= ALERT_THRESHOLD:
                    buf = build_chart(df, sym, price)
                    emoji = "🟢" if ms > ml else "🔴"
                    dec = _dec(price)

                    await bot.send_photo(
                        ALERT_CHAT_ID,
                        photo=BufferedInputFile(buf.read(), filename=f"alert_{sym}.png"),
                        caption=(
                            f"🚨 <b>АЛЕРТ — {sym}</b>\n\n"
                            f"{emoji} Мощная зона!\n💰 ${price:,.{dec}f}\n"
                            f"🟢 ${ms:,.0f}  🔴 ${ml:,.0f}"
                        ),
                        parse_mode="HTML",
                        message_thread_id=ALERT_TOPIC_ID,
                    )
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("%s: %s", coin, e)

        refresh_proxies()
        await asyncio.sleep(1800)


async def main():
    asyncio.create_task(auto_alert_loop())
    logger.info("Bot started. Binance transport: %s", _transport_label())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
