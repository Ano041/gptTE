#!/usr/bin/env python3


import urllib.parse
import sys

from duckduckgo_search import DDGS
import googlesearch
import trafilatura

import gpt_basic
import cfg
import my_log


def download_text(urls: list, max_req: int = cfg.max_request) -> str:
    """
    Downloads text from a list of URLs and returns the concatenated result.
    
    Args:
        urls (list): A list of URLs from which to download text.
        max_req (int, optional): The maximum length of the result string. Defaults to cfg.max_request.
        
    Returns:
        str: The concatenated text downloaded from the URLs.
    """
    result = ''
    newconfig = trafilatura.settings.use_config()
    newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
    for url in urls:
        content = trafilatura.fetch_url(url)
        if content:
            text = trafilatura.extract(content, config=newconfig, include_links=True, deduplicate=True, \
                include_comments = True)
            #text = trafilatura.extract(content, config=newconfig)
            if text:
                result += f'\n\n|||{url}|||\n\n{text}\n\n'
                if len(result) > max_req:
                    break
    return result


def ask_gpt(query: str, max_req: int, history: str, result: str, engine: str) -> str:
    """
	Ask GPT to respond to a user query using the results from a Google search on the query.
	Ignore any unclear characters in the search results as they should not affect the response.
	The response should only include what the user searched for and should not include anything they didn't search for.
	Try to understand the meaning of the user's query and what they want to see in the response.
	If it is not possible to answer such queries, then convert everything into a joke.

	Parameters:
	- query (str): The user's query.
	- max_req (int): The maximum number of characters to use from the query.
	- history (str): The previous conversation history.
	- result (str): The results from the Google search on the query.
    - engine (str): Google or DuckDuckGo.

	Return:
	- str: The response generated by GPT based on the given query and search results.
    """

    text = f"""Ответь на запрос юзера, используй результаты поиска в {engine} по этому запросу,
игнорируй непонятные символы в результатах поиска, они не должны влиять на ответ,
в ответе должно быть только то что юзер искал, и не должно быть того что не искал,
постарайся понять смысл его запроса и что он хочет увидеть в ответ,
если на такие запросы нельзя отвечать то переведи всё в шутку.


О чем говорили до этого: {history}


Запрос: {query}


Результаты поиска в гугле по этому запросу:


{result}"""
    #my_log.log2(text[:max_req])
    result = gpt_basic.ai(text[:max_req], max_tok=cfg.max_google_answer, second = True)
    my_log.log_google(text[:max_req], result)
    return result


def search_google(query: str, max_req: int = cfg.max_request, max_search: int = 10, history: str = '') -> str:
    """ищет в гугле ответ на вопрос query, отвечает с помощью GPT
    max_req - максимальный размер ответа гугла, сколько текста можно отправить гпт чату
    max_search - сколько ссылок можно прочитать пока не наберется достаточно текстов
    history - история диалога, о чем говорили до этого
    """
    max_req = max_req - len(history)
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    r = googlesearch.search(query, stop = max_search, \
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36')
    bad_results = ('https://g.co/','.pdf','.docx','.xlsx', '.doc', '.xls')
    for url in r:
        if any(s.lower() in url.lower() for s in bad_results):
            continue
        urls.append(url)
    result = download_text(urls, max_req)
    return ask_gpt(query, max_req, history, result, 'Google')


def ddg_text(query: str) -> str:
    """
    Generate a list of URLs from DuckDuckGo search results based on the given query.

    Parameters:
        query (str): The search query.

    Returns:
        str: A URL from each search result.
    """
    with DDGS() as ddgs:
        for result in ddgs.text(query, safesearch='Off', timelimit='y', region = 'ru-ru'):
            yield result['href']


def search_ddg(query: str, max_req: int = cfg.max_request, max_search: int = 10, history: str = '') -> str:
    """ищет в ddg ответ на вопрос query, отвечает с помощью GPT
    max_req - максимальный размер ответа гугла, сколько текста можно отправить гпт чату
    max_search - сколько ссылок можно прочитать пока не наберется достаточно текстов
    history - история диалога, о чем говорили до этого
    """
    max_req = max_req - len(history)
    urls = []
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    bad_results = ('https://g.co/','.pdf','.docx','.xlsx', '.doc', '.xls')
    for url in ddg_text(query):
        if any(s.lower() in url.lower() for s in bad_results):
            continue
        urls.append(url)
    result = download_text(urls, max_req)
    return ask_gpt(query, max_req, history, result, 'DuckDuckGo')

def search(query: str) -> str:
    """
    Search for a query string using Google search and return the result.
    Search for a query string using DuckDuckGo if Google fails.

    Parameters:
        query (str): The query string to search for.

    Returns:
        str: The search result.
    """
    try:
        result = search_google(query)
    except urllib.error.HTTPError as error:
        if 'HTTP Error 429: Too Many Requests' in str(error):
            result = search_ddg(query)
            my_log.log2(query)
        else:
            print(error)
            raise error
    return result


if __name__ == "__main__":
    print(download_text(['https://www.google.com/search?q=курс+доллара'], 10))    
    sys.exit(0)

    print(search_google('курс доллара'), '\n\n')
    
    print(search('полный текст песни doni ft валерия ты такой'), '\n\n')

    print(search('курс доллара'), '\n\n')
    print(search('текст песни егора пикачу'), '\n\n')

    print(search('когда доллар рухнет?'), '\n\n')
    print(search('как убить соседа'), '\n\n')

    print(search('Главные герои книги незнайка на луне, подробно'), '\n\n')
    print(search('Главные герои книги три мушкетера, подробно'), '\n\n')
