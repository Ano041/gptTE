#!/usr/bin/env python3
# https://ai.google.dev/


import base64
import pickle
import random
import threading
import requests

import cfg
import my_dic
import my_log


# роли {id:str} инструкция которая вставляется всегда
ROLES = my_dic.PersistentDict('db/gemini_roles.pkl')

# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# memory save lock
SAVE_LOCK = threading.Lock()

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 14000

# максимальный размер истории (32к ограничение Google?)
MAX_CHAT_SIZE = 25000


# хранилище диалогов {id:list(mem)}
CHATS = {}
DB_FILE = 'db/gemini_dialogs.pkl'


def load_memory_from_file():
    """
    Load memory from a file and store it in the global CHATS variable.

    Parameters:
        None

    Returns:
        None
    """
    global CHATS
    try:
        with open(DB_FILE, 'rb') as f:
            CHATS = pickle.load(f)
    except Exception as error:
        CHATS = {}
        my_log.log2(f'load_memory_from_file:{str(error)}')


def save_memory_to_file():
    """
    Saves the contents of the CHATS dictionary to a file.

    This function is responsible for serializing the CHATS dictionary and
    saving its contents to a file specified by the DB_FILE constant. It
    ensures that the operation is thread-safe by acquiring the SAVE_LOCK
    before performing the file write.

    Parameters:
        None

    Returns:
        None

    Raises:
        Exception: If an error occurs while saving the memory to the file.
    """
    try:
        with SAVE_LOCK:
            with open(DB_FILE, 'wb') as f:
                pickle.dump(CHATS, f)
    except Exception as error:
        my_log.log2(f'save_memory_to_file:{str(error)}')


def img2txt(data_: bytes, prompt: str = "Что на картинке, подробно?") -> str:
    """
    Generates a textual description of an image based on its contents.

    Args:
        data_: The image data as bytes.
        prompt: The prompt to provide for generating the description. Defaults to "Что на картинке, подробно?".

    Returns:
        A textual description of the image.

    Raises:
        None.
    """
    try:
        img_data = base64.b64encode(data_).decode("utf-8")
        data = {
            "contents": [
                {
                "parts": [
                    {"text": prompt},
                    {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": img_data
                    }
                    }
                ]
                }
            ]
            }
        api_key = random.choice(cfg.gemini_keys)
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={api_key}",
            json=data,
            timeout=60
        ).json()

        return response['candidates'][0]['content']['parts'][0]['text']
    except Exception as error:
        my_log.log2(f'img2txt:{error}')
    return ''


def update_mem(query: str, resp: str, mem) -> list:
    """
    Update the memory with the given query and response.

    Parameters:
        query (str): The input query.
        resp (str): The response to the query.
        mem: The memory object to update, if str than mem is a chat_id

    Returns:
        list: The updated memory object.
    """
    chat_id = ''
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        if mem not in CHATS:
            CHATS[mem] = []
        mem = CHATS[mem]

    if resp:
        mem.append({"role": "user", "parts": [{"text": query}]})
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
        if chat_id:
            CHATS[chat_id] = mem
            save_memory_to_file()
        return mem


def ai(q: str, mem = []) -> str:
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
            ],
            # "generationConfig": {
                # "stopSequences": [
                #     "Title"
                # ],
                # "temperature": 1.0,
                # "maxOutputTokens": 8000,
                # "topP": 0.8,
                # "topK": 10
                # }
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
    except Exception as ai_error:
        my_log.log2(f'ai:{ai_error}\n\n{str(response.json())}')
        resp = ''

    return resp


def chat(query: str, chat_id: str) -> str:
    """
    This function is used to process a chat query and return a response.

    Parameters:
    - query (str): The chat query to process.
    - chat_id (str): The ID of the chat.

    Returns:
    - str: The response to the chat query.
    """
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        if chat_id not in CHATS:
            CHATS[chat_id] = []
        mem = CHATS[chat_id]
        r = ai(query, mem)
        if r:
            mem = update_mem(query, r, mem)
            CHATS[chat_id] = mem
            save_memory_to_file()
        return r


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    CHATS[chat_id] = []
    save_memory_to_file()


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


def translate(text: str, from_lang: str = '', to_lang: str = '') -> str:
    """
    Translates the given text from one language to another.
    
    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        
    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'
    query = f'Translate from language [{from_lang}] to language [{to_lang}]:\n\n{text}'
    translated = ai(query)
    return translated


def chat_cli():
    while 1:
        q = input('>')
        r = chat(q, 'test')
        print(r)


if __name__ == '__main__':

    # t = """'The chatbot responds to the name <b>bot</b>.\nFor example, you can say <b>bot, tell me a joke</b>.\nIn private messages, you don\'t need to mention the bot\'s name\n\n🔭 If you send a link in a private message, the bot will try to extract and provide a brief summary of the content.\n\n🛸 To get text from an image, send the image with the caption "ocr" (or "read"). \n\n🎙️ You can issue commands and make requests using voice messages.\n\nWhen communicating with Claude AI, uploaded files and links are sent directly to Claude, and he can respond based on their content.\n\nChatGPT has a special mode of operation where a model trained for concise answers responds instead of the chat. To use it, simply start your query with a period.\n\n.Write all days of the week separated by commas\n\nThe usual model will add extraneous words to its responses, such as "Okay, I\'ll try," while this model is trained to be concise and informative.\n\n\nYou can send texts longer than 4096 characters. The Telegram client automatically breaks them down into parts, and the bot reassembles them. The restrictions for chatbots are as follows:\n\nChatGPT: 7000\nGoogle Bard: 14000\nClaude AI: 190000\n\n\nWebsite:\nhttps://github.com/theurs/tb1\n\nReport issues on Telegram:\nhttps://t.me/theurs\n\nDonate:\n<a href = "https://www.sberbank.com/ru/person/dl/jc?linkname=EiDrey1GTOGUc3j0u">SBER</a> <a href = "https://qiwi.com/n/KUN1SUN">QIWI</a> <a href = "https://yoomoney.ru/to/4100118478649082">Yoomoney</a>\n'"""
    # print(translate(t, 'en', 'ru'))
    # print(translate('Привет', 'ru', 'en'))
    # print(translate('Hello', 'en', 'es'))
    # print(translate('Bonjour', 'fr', 'de'))
    # print(translate('Ciao', 'it', 'ja'))
    # print(translate('你好', 'zh', 'ko'))
    # print(translate('مرحبا', 'ar', 'nl'))
    # print(translate('Hej', 'sv', 'pl'))
    # print(translate('Γεια σας', 'el', 'pt'))
    # print(translate('Hallo', 'de', 'ru'))
    # print(translate('Hola', 'es', 'fr'))

    chat_cli()
    
    # data = open('1.jpg', 'rb').read()
    # print(img2txt(data))