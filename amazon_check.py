import asyncio
import json
import os
import re
from pathlib import Path

import requests
from playwright.async_api import async_playwright


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = "176701300"

STATE_FILE = Path("state.json")

PRODUCTS = [
    {
        "asin": "B0789QHT4P",
        "name": "Mansions of Madness — Sanctum of Twilight",
    },

    # Adicione outros produtos aqui:
    # {
    #     "asin": "XXXXXXXXXX",
    #     "name": "Nome do produto",
    # },
]


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    response.raise_for_status()


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def extract_price(text):
    matches = re.findall(r"R\$\s*[\d.]+,\d{2}", text)

    if matches:
        return matches[0]

    return "Preço não identificado"


async def check_product(page, product):
    asin = product["asin"]
    name = product["name"]

    url = f"https://www.amazon.com.br/dp/{asin}"

    print(f"\nVerificando: {name}")
    print(f"ASIN: {asin}")

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(4000)

        text = await page.locator("body").inner_text()

        blocked_words = [
            "Digite os caracteres",
            "Digite o código",
            "CAPTCHA",
            "Robot Check",
            "Verificação de segurança",
        ]

        if any(word.lower() in text.lower() for word in blocked_words):
            print("🟡 Amazon pediu verificação. Ignorando esta verificação.")
            return None

        available = (
            "Adicionar ao carrinho" in text
            or "Comprar agora" in text
        )

        if "Não disponível" in text or "Indisponível" in text:
            available = False

        price = extract_price(text)

        if available:
            print(f"🟢 DISPONÍVEL — {price}")
            status = "available"
        else:
            print("🔴 INDISPONÍVEL")
            status = "unavailable"

        return {
            "status": status,
            "price": price,
        }

    except Exception as e:
        print(f"❌ Erro ao verificar {asin}: {e}")
        return None


async def main():

    state = load_state()

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page(
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        for product in PRODUCTS:

            result = await check_product(page, product)

            if result is None:
                continue

            asin = product["asin"]

            previous_status = state.get(asin, {}).get("status")

            if (
                previous_status == "unavailable"
                and result["status"] == "available"
            ):

                message = (
                    "🟢 PRODUTO VOLTOU AO ESTOQUE!\n\n"
                    f"📦 {product['name']}\n"
                    f"💰 {result['price']}\n"
                    f"🔢 ASIN: {asin}\n\n"
                    f"🛒 https://www.amazon.com.br/dp/{asin}"
                )

                print("🚨 ENVIANDO ALERTA TELEGRAM!")

                send_telegram(message)

            state[asin] = {
                "status": result["status"],
                "price": result["price"],
            }

        await browser.close()

    save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
