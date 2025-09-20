# main.py
import asyncio
import re
import aiohttp
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
import os

# --- Modelos de Dados ---
class UrlList(BaseModel):
    urls: list[str]

# --- Configuração do FastAPI ---
app = FastAPI()

# Configura para servir o arquivo HTML
templates_dir = Path("templates")
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

# --- Lógica de Extração (A mesma que já tínhamos) ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

def _clean_album_title(title: str, default_title="album_sem_titulo") -> str:
    title = title.replace("- ImagePond", "").strip()
    illegal_chars = r'[\\/:*?"<>|]'
    title = re.sub(illegal_chars, "_", title).strip(". ")
    return title if title else default_title

def _collect_data_from_erome(soup: BeautifulSoup) -> tuple[str, list]:
    album_title_tag = soup.find("meta", property="og:title")
    album_title = _clean_album_title(album_title_tag["content"] if album_title_tag else "erome_album")
    media_items = []
    all_media_containers = soup.find_all("div", class_="item")
    for item_container in all_media_containers:
        video_player = item_container.find("video", class_="video-js")
        if video_player:
            video_url, thumb_url = None, ""
            source_tag = item_container.find("source")
            if source_tag and 'src' in source_tag.attrs: video_url = source_tag['src']
            poster_div = item_container.find_previous_sibling("div", class_="vjs-poster")
            if poster_div and 'style' in poster_div.attrs:
                match = re.search(r'url\("?(.+?)"?\)', poster_div['style'])
                if match: thumb_url = match.group(1)
            if video_url: media_items.append({"type": "video", "media_url": video_url, "thumb_url": thumb_url})
        else:
            image_tag = item_container.find("img", class_="img-back")
            if image_tag: media_items.append({"type": "image", "media_url": image_tag["data-src"], "thumb_url": ""})
    return album_title, media_items

def _collect_data_from_imagepond(soup: BeautifulSoup) -> tuple[str, list]:
    media_items = []
    title_tag = soup.find("title")
    title = _clean_album_title(title_tag.text.strip() if title_tag else "imagepond_media")
    video_tag = soup.find("meta", property="og:video")
    thumb_tag = soup.find("meta", property="og:image")
    if video_tag and thumb_tag:
        video_url, thumb_url = video_tag.get('content'), thumb_tag.get('content')
        if video_url and thumb_url: media_items.append({"type": "video", "media_url": video_url, "thumb_url": thumb_url})
    return title, media_items

PARSERS = {
    "www.erome.com": _collect_data_from_erome,
    "www.imagepond.net": _collect_data_from_imagepond,
}

async def process_single_url(session, url):
    try:
        hostname = urlparse(url).hostname
        parser_func = PARSERS.get(hostname)
        if not parser_func:
            raise ValueError(f"Site não suportado: {hostname}")

        async with session.get(url) as response:
            response.raise_for_status()
            html_content = await response.text()
            soup = BeautifulSoup(html_content, "html.parser")
            title, items = parser_func(soup)
            return {"status": "success", "url": url, "title": title, "items": items}
    except Exception as e:
        return {"status": "error", "url": url, "reason": str(e)}

# --- Endpoints da API ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # Esta função carrega a nossa interface (o arquivo index.html)
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/extract")
async def extract_links(data: UrlList):
    # Esta função é chamada quando você clica no botão "Extrair"
    results = []
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [process_single_url(session, url) for url in data.urls]
        results = await asyncio.gather(*tasks) # Processa tudo em paralelo
    
    return {"results": results}