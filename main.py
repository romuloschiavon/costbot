from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()

from services import Services, today_sp
from state import BotState, normalize_bank, parse_desc_and_value

app = FastAPI()
svc = Services()
bot = BotState()


@app.get("/")
async def root() -> Dict[str, bool]:
    return {"ok": True}


def chunk(rows: List[str], n: int) -> List[List[str]]:
    return [rows[i : i + n] for i in range(0, len(rows), n)]


def has_required_fields(*fields: str) -> bool:
    for f in fields:
        if f not in bot.data or bot.data[f] in (None, ""):
            return False
    return True


async def ask_pai() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "Sim", "callback_data": "pai_sim"},
                {"text": "Não", "callback_data": "pai_nao"},
            ]
        ]
    }
    await svc.send("Gasto com o Pai?", kb)


async def ask_cc() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "Sim", "callback_data": "cc_sim"},
                {"text": "Não", "callback_data": "cc_nao"},
            ]
        ]
    }
    await svc.send("Cartão de crédito?", kb)


async def ask_bank() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "BB", "callback_data": "bank_BB"},
                {"text": "Itaú", "callback_data": "bank_Itau"},
            ],
            [
                {"text": "XP", "callback_data": "bank_XP"},
                {"text": "Infinite", "callback_data": "bank_Infinite"},
            ],
        ]
    }
    await svc.send("Qual conta?", kb)


async def ask_category() -> None:
    cats = await svc.get_categories()
    if not cats:
        cats = [
            "Comida",
            "Moradia",
            "Transporte",
            "Pessoal",
            "Higiene/Saúde",
            "Tech",
            "Carro",
            "Internet",
            "Academia",
        ]

    kb = {
        "keyboard": chunk(cats, 3),
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    await svc.send("Escolha a categoria:", kb)


def build_google_post_payload() -> Dict[str, Any]:
    return {
        "nome": str(bot.data["nome"]),
        "valor": str(bot.data["valor"]),
        "data": today_sp(),
        "categoria": str(bot.data["cat"]),
        "conta": "Cartão" if bool(bot.data["cc"]) else str(bot.data["bank"]),
        "pai": bool(bot.data["pai"]),
        "cc": bool(bot.data["cc"]),
    }


def build_google_check_params() -> Dict[str, Any]:
    return {
        "action": "check",
        "nome": str(bot.data["nome"]),
        "valor": str(bot.data["valor"]),
        "data": today_sp(),
        "cc": str(bool(bot.data["cc"])).lower(),
    }


async def check_google_with_retry() -> Dict[str, Any]:
    last: Dict[str, Any] = {"encontrado": False}
    for delay in (0.2, 0.6, 1.2, 2.0):
        last = await svc.check_google(build_google_check_params())
        if bool(last.get("encontrado")):
            return last
        await asyncio.sleep(delay)
    return last


async def finalize_send_to_google() -> None:
    if not has_required_fields("nome", "valor", "cat", "pai", "cc"):
        await svc.send(
            "Sessão expirada ou fora de ordem. Envie /novo para começar de novo."
        )
        bot.reset()
        return

    if not bool(bot.data.get("cc", False)) and not has_required_fields("bank"):
        await svc.send("Faltou escolher a conta. Envie /novo e tente novamente.")
        bot.reset()
        return

    await svc.send("Enviando...")

    post_resp = await svc.post_google(build_google_post_payload())
    if post_resp.get("status") == "erro":
        await svc.send(
            f"Erro ao gravar no Google: {post_resp.get('mensagem', 'desconhecido')}"
        )
        bot.reset()
        return

    check_resp = await check_google_with_retry()
    if bool(check_resp.get("encontrado")):
        await svc.send("Confirmado na planilha!")
    else:
        erro = check_resp.get("erro")
        if erro:
            await svc.send(f"Google recebeu, mas não confirmou. Erro: {erro}")
        else:
            await svc.send("Google recebeu, mas não confirmou.")
    bot.reset()


async def handle_message(text: str) -> None:
    text = (text or "").strip()

    if text == "/cancelar":
        bot.reset()
        await svc.send("Cancelado.")
        return

    if text == "/novo" and bot.step == "IDLE":
        bot.step = "WAITING_PAI"
        await ask_pai()
        return

    if bot.step == "WAITING_DESC":
        parsed = parse_desc_and_value(text)
        if not parsed:
            await svc.send("Formato inválido!\nExemplo: mercado,-150,00")
            return

        nome, valor = parsed
        bot.data["nome"] = nome
        bot.data["valor"] = valor
        bot.step = "WAITING_CAT"
        await ask_category()
        return

    if bot.step == "WAITING_CAT":
        bot.data["cat"] = text
        if bool(bot.data.get("cc", False)):
            await finalize_send_to_google()
        else:
            bot.step = "WAITING_BANK"
            await ask_bank()
        return


async def handle_callback(data_cb: str, callback_id: str) -> None:
    await svc.answer_callback(callback_id)

    if data_cb.startswith("pai_"):
        if bot.step not in ("WAITING_PAI", "IDLE"):
            await svc.send("Sessão fora de ordem. Envie /novo.")
            bot.reset()
            return
        bot.data["pai"] = data_cb == "pai_sim"
        bot.step = "WAITING_CC"
        await ask_cc()
        return

    if data_cb.startswith("cc_"):
        if bot.step != "WAITING_CC":
            await svc.send("Sessão fora de ordem. Envie /novo.")
            bot.reset()
            return
        bot.data["cc"] = data_cb == "cc_sim"
        bot.step = "WAITING_DESC"
        await svc.send("Digite no formato:\nmercado,-150,00")
        return

    if data_cb.startswith("bank_"):
        if bot.step != "WAITING_BANK":
            await svc.send("Sessão fora de ordem. Envie /novo.")
            bot.reset()
            return
        bank = data_cb.split("_", 1)[1]
        bot.data["bank"] = normalize_bank(bank)
        await finalize_send_to_google()
        return


@app.on_event("startup")
async def on_startup() -> None:
    await svc.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await svc.close()


@app.post("/webhook")
async def webhook(req: Request) -> Dict[str, bool]:
    body = await req.json()

    if "callback_query" in body:
        cb = body["callback_query"]
        if str(cb["from"]["id"]) != svc.my_chat_id:
            return {"ok": True}
        await handle_callback(str(cb.get("data", "")), str(cb.get("id", "")))
        return {"ok": True}

    if "message" in body:
        msg = body["message"]
        if str(msg["chat"]["id"]) != svc.my_chat_id:
            return {"ok": True}
        text = str(msg.get("text", "") or "")
        await handle_message(text)

    return {"ok": True}
