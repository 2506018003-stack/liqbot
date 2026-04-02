# liqbot

## Environment

Use `.env.example` as a template for your environment variables.

Example:

```bash
cd /Users/artemt/Downloads/liqbot
export BOT_TOKEN='replace_me'
export REQUEST_TIMEOUT='12'
export BINANCE_BASE_URL='https://fapi.binance.com'
export BINANCE_DIRECT_FALLBACK='1'
export PUBLIC_PROXY_FALLBACK='0'
export BINANCE_PROXY_URLS='http://jbmfxgbs:b6qdned11779@31.59.20.176:6754/,http://jbmfxgbs:b6qdned11779@45.38.107.97:6014/,http://jbmfxgbs:b6qdned11779@198.105.121.200:6462/,http://jbmfxgbs:b6qdned11779@142.111.67.146:5611/,http://jbmfxgbs:b6qdned11779@31.58.9.4:6077/'
python3 bot.py
```

## Telegram commands

- `/liq BTC` builds the liquidation chart for the symbol.
- `/proxy` shows the current Binance base URL, timeout, and configured proxy list.
- `/net` runs a Binance ping diagnostic against the configured routes.

## Curl checks

```bash
curl --proxy "http://jbmfxgbs:b6qdned11779@31.59.20.176:6754/" https://ipv4.webshare.io/
curl --proxy "http://jbmfxgbs:b6qdned11779@45.38.107.97:6014/" https://ipv4.webshare.io/
curl --proxy "http://jbmfxgbs:b6qdned11779@198.105.121.200:6462/" https://ipv4.webshare.io/
curl --proxy "http://jbmfxgbs:b6qdned11779@142.111.67.146:5611/" https://ipv4.webshare.io/
curl --proxy "http://jbmfxgbs:b6qdned11779@31.58.9.4:6077/" https://ipv4.webshare.io/
```

## Optional Binance host switch

If `fapi.binance.com` is slow in your region, try:

```bash
export BINANCE_BASE_URL='https://fapi1.binance.com'
```
