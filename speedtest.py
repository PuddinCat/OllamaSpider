from collections import defaultdict
from typing import Sequence
from pathlib import Path
from tqdm import tqdm
import asyncio
import json
import httpx
import time
import random

url = "https://raw.githubusercontent.com/PuddinCat/OllamaSpider/refs/heads/main/url_models.json"

url_models = httpx.get(url).json()
locks = defaultdict(asyncio.Lock)
sema = asyncio.Semaphore(32)


URLS = set(item["url"] for item in url_models)


async def get_models(client: httpx.AsyncClient, url: str, pbar: tqdm | None = None):
    try:
        resp = None
        async with locks[url], sema:
            resp = await client.get(url + "/api/ps")
        return [
            info["model"]
            for info in resp.json()["models"]
            if 10 * 1000**3 < info["size"]
        ]

    except Exception:
        return None
    finally:
        if pbar is not None:
            pbar.update(1)


async def test_url(
    client: httpx.AsyncClient, url: str, model: str, pbar: tqdm | None = None
) -> float | None:
    async with locks[url], sema:
        times = []
        try:
            async with client.stream(
                method="POST",
                url=url + "/api/generate",
                json={
                    "model": model,
                    "prompt": "Introduce yourself with about 50 words",
                },
            ) as resp:
                async for data in resp.aiter_lines():
                    if "response" not in json.loads(data):
                        print(url, data)
                    times.append(time.time())
                    if times[-1] - times[0] > 30:
                        return None
        except Exception:
            return None
        finally:
            if pbar is not None:
                pbar.update(1)
        if len(times) < 10:
            return None
        speed = len(times) / (times[-1] - times[0])
        return speed


async def test_speed(urls: Sequence[str]):
    async with httpx.AsyncClient(timeout=5) as client:
        with tqdm(urls) as pbar:
            running_models = await asyncio.gather(
                *[get_models(client, url, pbar=pbar) for url in urls]
            )
        running_models_url = [
            (url, model)
            for url, models in zip(urls, running_models)
            if models
            for model in models
        ]
        random.shuffle(running_models_url)
        with tqdm(running_models_url) as pbar:
            speed_result = await asyncio.gather(
                *[
                    test_url(client, url, model, pbar=pbar)
                    for url, model in running_models_url
                ]
            )
        speeds = [
            {
                "url": url,
                "speeds": [
                    {"model": model, "speed": speed}
                    for (speed, (url2, model)) in zip(speed_result, running_models_url)
                    if url2 == url and speed is not None
                ],
            }
            for url in set(url for url, _ in running_models_url)
        ]
        speeds.sort(
            key=lambda item: (
                max(
                    speed_info["speed"] if speed_info["speed"] else 0
                    for speed_info in item["speeds"]
                )
                if item["speeds"]
                else 0
            ),
            reverse=True,
        )
        return speeds


async def main():
    Path("speeds.json").write_text(json.dumps(await test_speed(URLS)))


if __name__ == "__main__":
    asyncio.run(main())
