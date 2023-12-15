#!/usr/bin/env python3
# https://ai.google.dev/

# Проверь присылает ли Джемини картинки вне текста в ответе

import random
import requests


import cfg


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 14000

# максимальный размер истории (32к ограничение Google?)
MAX_CHAT_SIZE = 25000


# хранилище диалогов {id:list(mem)}
CHATS = {}


def ai(q: str, mem) -> str:
    """
    Generate the response of an AI model based on a given question and memory.

    Parameters:
    - q (str): The question to be passed to the AI model.
    - mem: The memory of the AI model which contains previous interactions.

    Returns:
    - str: The response generated by the AI model based on the given question and memory.
    """
    mem_ = {"contents": mem + [{"role": "user", "parts": [{"text": q}]}],
            "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
            }

    keys = cfg.gemini_keys[:]
    random.shuffle(keys)
    for key in keys:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + key
        response = requests.post(url, json=mem_, timeout=60)
        if response.status_code == 200:
            break

    try:
        resp = response.json()['candidates'][0]['content']['parts'][0]['text']
        # print(response.json()['candidates'][0]['content'])
    except Exception as ai_error:
        resp = 'Gemini didnt respond'
        # print(ai_error)

    if resp:
        mem.append({"role": "user", "parts": [{"text": q}]})
        mem.append({"role": "model", "parts": [{"text": resp}]})
        size = 0
        for x in mem:
            text = x['parts'][0]['text']
            size += len(text)
        while size > MAX_CHAT_SIZE:
            mem = mem[2:]
            size = 0
            for x in mem:
                text = x['parts'][0]['text']
                size += len(text)


    return resp


def chat(query: str, chat_id: str) -> str:
    """
    A function that handles chat queries.

    Args:
        query (str): The query string.
        chat_id (str): The ID of the chat.

    Returns:
        str: The response from the AI.
    """
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    return ai(query, mem)


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    for x in mem:
        role = x['role']
        try:
            text = x['parts'][0]['text'].split(']: ', maxsplit=1)[1]
        except IndexError:
            text = x['parts'][0]['text']
        result += f'{role}: {text}\n'
        if role == 'model':
            result += '\n'
    return result    


if __name__ == '__main__':
    while 1:
        q = input('>')
        r = chat(q, 'test')
        print(r)
