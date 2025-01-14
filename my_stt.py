#!/usr/bin/env python3
# pip install -U google-generativeai

import base64
import hashlib
import os
import random
import requests
import subprocess
import time
import threading
import traceback
from pydub import AudioSegment
from io import BytesIO

import speech_recognition as sr

import my_transcribe
import cfg
import my_groq
import my_gemini
import my_log
import utils
from utils import asunc_run


# locks for chat_ids
LOCKS = {}

# [(crc32, text recognized),...]
STT_CACHE = []
CACHE_SIZE = 100


def audio_duration(audio_file: str) -> int:
    """
    Get the duration of an audio file.

    Args:
        audio_file (str): The path to the audio file.

    Returns:
        int: The duration of the audio file in seconds.
    """
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        r = float(result.stdout)
    except ValueError:
        r = 0
    try:
        r = int(r)
    except ValueError:
        r = 0
    return r


def convert_to_ogg_with_ffmpeg(audio_file: str) -> str:
    """
    Converts an audio file to a ogg format using FFmpeg.

    Args:
        audio_file (str): The path to the audio file to be converted.

    Returns:
        str: The path to the converted wave file.
    """
    tmp_wav_file = utils.get_tmp_fname() + '.ogg'
    subprocess.run(['ffmpeg', '-i', audio_file, '-map', '0:a', '-c:a','libvorbis', tmp_wav_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_wav_file


@asunc_run
def debug_log_stt_google_enchance(text: str):
    '''Записывает в журнал распознанное текстовое сообщение и его улучшенную с
    помощью ИИ версию для проверки насколько это вообще годное решение'''
    query = f'''Correct the text received using voice recognition,
fix speech recognition errors, make the text correct and fine,
preserve the original language,
preserve the original form and intent as much as possible,
your answer should only contain the corrected text,
your only work is to correct text,
please do not answer the question in text,
no any other words in reply please: \n\n{text}'''
    resp = my_groq.ai(query, temperature=0, mem_ = my_groq.MEM_UNCENSORED)
    if not resp:
        resp = my_gemini.ai(query, temperature=0, mem = my_gemini.MEM_UNCENSORED)
        my_log.log_debug_stt(f'gemini flash\n\n{text}\n\n{resp}')
    else:
        my_log.log_debug_stt(f'llama 3 70b\n\n{text}\n\n{resp}')

def stt_google(audio_file: str, language: str = 'ru') -> str:
    """
    Speech-to-text using Google's speech recognition API.
    
    Args:
        audio_file (str): The path to the audio file to be transcribed.
        language (str, optional): The language of the audio file. Defaults to 'ru'.
    
    Returns:
        str: The transcribed text from the audio file.
    """
    google_recognizer = sr.Recognizer()

    audio = AudioSegment.from_file(audio_file)
    # Сохраняем сегмент в BytesIO
    wav_bytes = BytesIO()
    audio.export(wav_bytes, format="wav")
    wav_bytes.seek(0)

    with sr.AudioFile(wav_bytes) as source:
        audio = google_recognizer.record(source)  # read the entire audio file

    text = google_recognizer.recognize_google(audio, language=language)

    # if text:
    #     debug_log_stt_google_enchance(text)
    return text


def stt_my_whisper_api(audio_file: str, language: str = 'ru') -> str:
    """
    Speech-to-text using MyWhisper API.
    
    Args:
        audio_file (str): The path to the audio file to be transcribed.
        language (str, optional): The language of the audio file. Defaults to 'ru'.
    
    Returns:
        str: The transcribed text from the audio file.
    """
    if not(hasattr(cfg, 'MY_WHISPER_API') and cfg.MY_WHISPER_API):
        return ''

    # assert audio_duration(audio_file) < 1200, 'Too big'

    servers = cfg.MY_WHISPER_API[:]
    random.shuffle(servers)

    for server in servers:
        addr = server[0]
        port = server[1]
        with open(audio_file, 'rb') as af:
            audio_bytes = af.read()

        audio_bytes_base64 = base64.b64encode(audio_bytes).decode('UTF-8')

        data = {"data": audio_bytes_base64, "lang": language}

        # Проверить доступность сервера
        response = requests.head(f"http://{addr}:{port}/stt", timeout=3)
        if response.status_code != 405:
            continue
        t1 = time.time()
        response = requests.post(
            f"http://{addr}:{port}/stt",
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=600,
        )
        print(time.time() - t1)
        if response.status_code == 200:
            r = base64.b64decode(response.content.decode("UTF-8")).decode('UTF-8')
            return r

    return ''


def stt(input_file: str, lang: str = 'ru', chat_id: str = '_') -> str:
    """
    Generate the function comment for the given function body in a markdown code block with the correct language syntax.

    Args:
        input_file (str): The path to the input file.
        lang (str, optional): The language for speech recognition. Defaults to 'ru'.
        chat_id (str, optional): The ID of the chat. Defaults to '_'.

    Returns:
        str: The recognized speech as text.
    """
    if chat_id not in LOCKS:
        LOCKS[chat_id] = threading.Lock()
    with LOCKS[chat_id]:
        text = ''
        with open(input_file, 'rb') as f:
            data_from_file = f.read()
        data = hashlib.sha256(data_from_file).hexdigest()
        global STT_CACHE
        for x in STT_CACHE:
            if x[0] == data:
                text = x[1]
                return text

        dur = audio_duration(input_file)
        input_file2 = convert_to_ogg_with_ffmpeg(input_file)

        try:
            if not text and dur < 55:
                # быстро и хорошо распознает но до 1 минуты всего
                # и часто глотает последнее слово
                try: # пробуем через гугл
                    text = stt_google(input_file2, lang)
                except Exception as unknown_error:
                    my_log.log2(str(unknown_error))

            if not text:
                try: # gemini
                    # может выдать до 8000 токенов (30000 русских букв) более чем достаточно для голосовух
                    text = stt_genai(input_file2, lang)
                except Exception as error:
                    my_log.log2(f'my_stt:stt:genai:{error}')

            #затем через локальный (моя реализация) whisper
            if not text:
                try:
                    text = stt_my_whisper_api(input_file2, lang)
                except Exception as error:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f'my_stt:stt:{error}\n\n{error_traceback}')

        finally:
            try:
                os.unlink(input_file2)
            except Exception as error:
                my_log.log2(f'my_stt:stt:os.unlink:{error}')

        if text:
            text_ = text
            STT_CACHE.append([data, text_])
            STT_CACHE = STT_CACHE[-CACHE_SIZE:]
            return text_

    return ''


def stt_genai_worker(audio_file: str, part: tuple, n: int, fname: str, language: str = 'ru') -> None:
    with my_transcribe.download_worker_semaphore:
        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            pass

        proc = subprocess.run([my_transcribe.FFMPEG, '-ss', str(part[0]), '-i', audio_file, '-t',
                        str(part[1]), f'{fname}_{n}.ogg'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_ = proc.stdout.decode('utf-8', errors='replace').strip()
        err_ = proc.stderr.decode('utf-8', errors='replace').strip()
        if 'error' in err_:
            my_log.log2(f'my_stt:stt_genai_worker: Error in FFMPEG: {err_}')
        if 'error' in out_:
            my_log.log2(f'my_stt:stt_genai_worker: Error in FFMPEG: {out_}')

        text = my_transcribe.transcribe_genai(f'{fname}_{n}.ogg', language=language)

        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)

        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            my_log.log2(f'my_stt:stt_genai_worker: Failed to delete audio file: {fname}_{n}.ogg')


def stt_genai(audio_file: str, language: str = 'ru') -> str:
    """
    Converts the given audio file to text using the Gemini API.

    Args:
        audio_file (str): The path to the audio file to be converted.

    Returns:
        str: The converted text.
    """
    prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text without time stamps."
    duration = audio_duration(audio_file)
    if duration <= 10*60:
        return my_transcribe.transcribe_genai(audio_file, prompt, language)
    else:
        part_size = 10 * 60 # размер куска несколько минут
        treshold = 5 # захватывать +- несколько секунд в каждом куске
        output_name = utils.get_tmp_fname()

        parts = []
        start = 0
        while start < duration:
            end = min(start + part_size, duration)
            if start == 0:
                parts.append((0, min(duration, end + treshold)))  # Первый фрагмент
            elif end == duration:
                parts.append((max(0, start - treshold), duration - start))  # Последний фрагмент
            else:
                parts.append((max(0, start - treshold), min(duration - start, part_size) + 2 * treshold))  # Остальные фрагменты
            start = end

        n = 0
        threads = []

        for part in parts:
            n += 1
            t = threading.Thread(target=stt_genai_worker, args=(audio_file, part, n, output_name))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        result = ''
        for x in range(1, n + 1):
            # check if file exists
            if os.path.exists(f'{output_name}_{x}.txt'):
                with open(f'{output_name}_{x}.txt', 'r', encoding='utf-8') as f:
                    result += f.read() + '\n\n'
                try:
                    os.unlink(f'{output_name}_{x}.txt')
                except:
                    my_log.log2(f'my_stt:stt_genai: Failed to delete {output_name}_{x}.txt')

        if 'please provide the audio file' in result.lower() and len(result) < 150:
            return ''
        return result


if __name__ == "__main__":
    pass
    # print(stt_genai('1.opus'))
