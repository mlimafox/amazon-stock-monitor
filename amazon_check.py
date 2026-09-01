import asyncio
import json
import os
import re
from pathlib import Path

import requests
from playwright.async_api import async_playwright


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = Path("state.json")

PRODUCTS = [
    {
        "asin": "B0789QHT4P",
        "name": "Mansions of Madness — Sanctum of Twilight",
    },
    {
        "asin": "B07VZSM1XF",
        "name": "Mansions of Madness — Path of the Serpent",
    },
    {
        "asin": "B08NVB7BS6",
        "name": "Amazon — B08NVB7BS6",
    },
    {
        "asin": "B0992PXW6L",
        "name": "Sentinels of the Multiverse — Definitive Edition",
    },
    {
        "asin": "B0C93LL82B",
        "name": "Metal Gear Solid: Master Collection Vol. 1 — PS5",
    },
    {
        "asin": "B09MC7TNRW",
        "name": "Amazon — B09MC7TNRW",
    },
    {
        "asin": "B07W1BF6D5",
        "name": "Marvel Champions — Core Set",
    },
    {
        "asin": "B0DRHYR931",
        "name": "Neo Geo Mini",
    },
    {
        "asin": "B0BRNY49VK",
        "name": "Amazon — B0BRNY49VK",
    },
    {
        "asin": "B0BRNVYSLY",
        "name": "Amazon — B0BRNVYSLY",
    },
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
    prices = re.findall(r"R\$\s*[\d.]+,\d{2}", text)

    if prices:
        return prices[0]

    return "Preço não identificado"


def detect_stock(text):
    lower = text.lower()

    blocked = [
        "captcha",
        "robot check",
        "verificação de segurança",
        "digite os caracteres",
        "confirme que você não é um robô",
    ]

    if any(word in lower for word in blocked):
        return "unknown", "Amazon solicitou verificação"

    available_phrases = [
        "adicionar ao carrinho",
        "comprar agora",
        "em estoque",
        "disponível para envio",
    ]

    unavailable_phrases = [
        "atualmente indisponível",
        "este produto não está disponível",
        "temporariamente esgotado",
        "não temos previsão de quando este produto estará disponível",
    ]

    if any(word in lower for word in available_phrases):
        return "available", "Oferta de compra encontrada"

    if any(word in lower for word in unavailable_phrases):
        return "unavailable", "Amazon indicou indisponibilidade"

    return "unknown", "Não foi possível confirmar o estoque"


async def get_buybox_text(page):
    selectors = [
        "#desktop_buybox",
        "#buybox",
        "#rightCol",
        "#availability",
        "#qualifiedBuybox",
    ]

    parts = []

    for selector in selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0:
                txt = await locator.first.inner_text(timeout=3000)
                if txt:
                    parts.append(txt)
        except Exception:
            pass

    return "\n".join(parts)


async def check_product(page, product):
    asin = product["asin"]
    name = product["name"]
    url = f"https://www.amazon.com.br/dp/{asin}"

    print(f"\nVerificando: {name}")
    print(f"ASIN: {asin}")

    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(5000)

        if response and response.status >= 400:
            print(f"🟡 HTTP {response.status}")
            return None

        buybox_text = await get_buybox_text(page)

        if not buybox_text.strip():
            print("🟡 Buy box não encontrada")
            return {
                "status": "unknown",
                "price": "Preço não identificado",
                "evidence": "Buy box não encontrada",
            }

        status, evidence = detect_stock(buybox_text)
        price = extract_price(buybox_text)

        if status == "available":
            print(f"🟢 DISPONÍVEL — {price}")
            print(f"   Evidência: {evidence}")

        elif status == "unavailable":
            print("🔴 INDISPONÍVEL")
            print(f"   Evidência: {evidence}")

        else:
            print("🟡 ESTADO DESCONHECIDO")
            print(f"   Motivo: {evidence}")

        return {
            "status": status,
            "price": price,
            "evidence": evidence,
        }

    except Exception as e:
        print(f"🟡 ERRO/ESTADO DESCONHECIDO: {e}")
        return None


async def main():
    state = load_state()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page(
            locale="pt-BR",
            viewport={
                "width": 1365,
                "height": 900,
            },
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
        )

        for product in PRODUCTS:
            result = await check_product(page, product)

            if result is None:
                continue

            asin = product["asin"]

            previous = state.get(
                asin,
                {
                    "status": None,
                    "price": None,
                    "unavailable_count": 0,
                    "alerted_available": False,
                },
            )

            current_status = result["status"]

            # UNKNOWN nunca altera o estado.
            if current_status == "unknown":
                print("   Estado anterior preservado.")
                continue

            # PRODUTO DISPONÍVEL
            if current_status == "available":
                previous["unavailable_count"] = 0

                # Só alerta se não estiver marcado como já alertado.
                if not previous.get("alerted_available", False):
                    if previous.get("status") == "unavailable":
                        message = (
                            "🟢 PRODUTO VOLTOU AO ESTOQUE!\n\n"
                            f"📦 {product['name']}\n"
                            f"💰 {result['price']}\n"
                            f"🔢 ASIN: {asin}\n\n"
                            f"🛒 https://www.amazon.com.br/dp/{asin}"
                        )

                        print("🚨 ENVIANDO ALERTA TELEGRAM!")
                        send_telegram(message)

                    previous["alerted_available"] = True

                previous["status"] = "available"
                previous["price"] = result["price"]
                previous["evidence"] = result["evidence"]

                state[asin] = previous
                continue

            # PRODUTO APARENTEMENTE INDISPONÍVEL
            if current_status == "unavailable":
                unavailable_count = previous.get("unavailable_count", 0) + 1
                previous["unavailable_count"] = unavailable_count

                print(
                    f"   Confirmação de indisponibilidade: "
                    f"{unavailable_count}/2"
                )

                # Só desarma o alerta depois de 2 leituras seguidas.
                if unavailable_count >= 2:
                    previous["status"] = "unavailable"
                    previous["alerted_available"] = False

                previous["price"] = result["price"]
                previous["evidence"] = result["evidence"]

                state[asin] = previous

        await browser.close()

    save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
