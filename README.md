# 🤖 Polymarket BTC Up/Down 5-Minute Bot

Bot automation untuk trading market **BTC Up/Down 5 menit** di Polymarket dengan strategy **EMA 9/21 + RSI 14** dan **Odds Filter 0.45-0.55**.

## 📋 Arsitektur

```
[Private Key / EOA]
        ↓ (sign)
[Proxy Wallet / Smart Contract]
        ↓ (execute)
[Polymarket CLOB / Relayer API]
```

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone https://github.com/Jametkudasigan/polyemarsi.git
```
```
cd polyemarsi
```
```
python -m venv venv
```
```
source venv/bin/activate
```
```
pip install -r requirements.txt
```

### 2. Konfigurasi .env

```bash
cp .env.example .env
nano .env
```

Isi **hanya 2 variable** berikut:

```env
POLY_PRIVATE_KEY=0x_your_private_key_here
POLY_PROXY_ADDRESS=0x_your_proxy_wallet_address_here
POLY_SIGNATURE_TYPE=1
```

**Catatan:**
- `POLY_PRIVATE_KEY`: Export dari Polymarket Settings > Private Key
- `POLY_PROXY_ADDRESS`: Alamat proxy wallet tempat USDC disimpan (lihat di Polymarket > Deposit)
- `POLY_SIGNATURE_TYPE`: `1` untuk Email/Magic wallet, `2` untuk Browser Proxy

API Key, Secret, dan Passphrase akan **digenerate otomatis** oleh bot dari private key.

### 3. Jalankan Bot

```bash
python main.py
```

## 📊 Strategy

### BUY Setup
- Harga di atas EMA 21
- EMA 9 di atas EMA 21
- RSI 14 turun ke 30–55 lalu mantul naik
- Entry pas candle mulai naik lagi

### SELL Setup
- Harga di bawah EMA 21
- EMA 9 di bawah EMA 21
- RSI 14 naik ke 55–75 lalu turun
- Entry pas candle mulai turun lagi

### Odds Filter
- Entry hanya di odds **0.45 – 0.55**
- Risk/reward seimbang, tidak beli mahal / jual murah

## 🖥️ UI Features

- **Box layout** dengan Rich terminal UI
- **Countdown timer** ke window 5 menit berikutnya
- **Real-time indicators** (Price, EMA9, EMA21, RSI)
- **Win/Loss tracking** dengan PnL
- **Balance Polymarket USD** real-time
- **Market link** saat posisi aktif
- **Single refresh** per detik (no spam)

## 🔄 Trade Flow

```
IDLE → SCANNING → ENTERING → POSITION → REDEEMING → IDLE
```

1. **IDLE**: Tunggu window 5 menit baru (30 detik sebelum start)
2. **SCANNING**: Fetch Binance klines, hitung EMA+RSI, cek odds
3. **ENTERING**: Eksekusi market order FOK jika semua filter pass
4. **POSITION**: Monitor sampai market resolved (5 menit)
5. **REDEEMING**: Hitung PnL, save history, kembali ke IDLE

## ⚙️ Konfigurasi Lanjutan

Edit `.env` untuk mengubah parameter:

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `BOT_MODE` | `DRY_RUN` | `LIVE` untuk trading real, `DRY_RUN` untuk simulasi |
| `MAX_ENTRY` | `1.0` | Max entry per trade (USD) |
| `MIN_ODDS` | `0.45` | Batas bawah odds filter |
| `MAX_ODDS` | `0.55` | Batas atas odds filter |
| `POLYGON_RPC` | `https://polygon-rpc.com` | RPC endpoint Polygon |

## 🛡️ Safety

- **DRY_RUN mode** default: Bot berjalan tanpa eksekusi order real
- **Max entry $1**: Limit exposure per trade
- **Odds filter**: Hindari entry di odds ekstrem
- **FOK orders**: Fill-or-Kill, tidak ada partial fill yang menggantung

## 📁 Struktur File

```
polymarket-btc-bot/
├── .env                  # Konfigurasi (jangan di-commit!)
├── .env.example          # Template konfigurasi
├── requirements.txt      # Dependencies
├── main.py               # Entry point
├── README.md
├── config/
│   └── settings.py       # Config loader
├── src/
│   ├── bot.py            # Main bot state machine
│   ├── ui.py             # Rich terminal UI
│   ├── indicators.py     # EMA & RSI calculations
│   ├── binance_client.py # Binance API wrapper
│   ├── polymarket_client.py # Polymarket API + CLOB
│   ├── position_manager.py  # Trade tracking & PNL
│   └── utils.py          # Helpers
└── data/
    └── trades.json       # Trade history (auto-generated)
```

## ⚠️ Disclaimer

Bot ini untuk **educational purposes**. Trading prediction markets memiliki risiko kehilangan dana. Pastikan:
- Sudah paham strategy sebelum pakai mode LIVE
- Sudah set token allowances (untuk EOA wallet)
- Punya cukup USDC di proxy wallet
- Jangan trade dengan dana yang tidak sanggup hilang

## 📚 Referensi API

- [Polymarket CLOB Client Python](https://github.com/Polymarket/py-clob-client)
- [Polymarket Gamma API](https://docs.polymarket.com/api-reference)
- [Polymarket Gasless Trading](https://docs.polymarket.com/trading/gasless)
- [Binance Klines API](https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data)
