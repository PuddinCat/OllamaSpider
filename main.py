from pathlib import Path
from typing import TypedDict
import asyncio
import json
import random
import time

import httpx
from tqdm import tqdm

MAX_ALIVE_INTERVAL = 86400  # a day
scan_semaphore = asyncio.Semaphore(128)


class ModelInfo(TypedDict):
    name: str
    size: int


def size_to_int(size: str):
    return int(float(size[:-1]) * {"M": 1024**2, "B": 1024**3}.get(size[-1], 0))


async def shodan_query(query: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.shodan.io/shodan/host/search",
            params={
                "key": "eV1r2h3IrCfPKtQ7CiXsjEuxE5aGlQTH",
                "query": query,
                "minify": True,
            },
        )
        return [
            f"http://{item['ip_str']}:{item['port']}"
            for item in resp.json().get("matches", [])
        ]


async def list_models(
    client: httpx.AsyncClient, url: str, pbar: tqdm | None
) -> list[ModelInfo] | None:
    try:
        resp = None
        async with scan_semaphore:
            resp = await client.get(url + "/api/tags")

        result: list[ModelInfo] = list(
            {
                "name": info.get("name", "Unknown"),
                "size": info.get("size", 0),
            }
            for info in resp.json().get("models", [])
        )
        result.sort(
            key=(lambda info: info["size"]),
            reverse=True,
        )
        result.sort(key=lambda info: info["name"][:3])
        return result
    except Exception:
        return None
    finally:
        if pbar:
            pbar.update(1)


async def main():

    urls_path = Path("urls.json")
    urls = await shodan_query("Ollama is running")
    if urls_path.exists():
        urls += json.loads(urls_path.read_text(encoding="utf-8"))
        urls = list(set(urls))

    random.shuffle(urls)

    request_success_time: dict[str, int] = {}
    request_success_time_path = Path("request_success_time.json")
    if request_success_time_path.exists():
        request_success_time = json.loads(
            request_success_time_path.read_text(encoding="utf-8")
        )

    url_models = None
    pbar = tqdm(total=len(urls))
    async with httpx.AsyncClient(timeout=10) as client:
        models = await asyncio.gather(*[list_models(client, url, pbar) for url in urls])
        url_models_list = [(url, models) for url, models in zip(urls, models) if models]
        url_models_list.sort(
            key=lambda info: max(model_info["size"] for model_info in info[1]),
            reverse=True,
        )
        url_models = dict(url_models_list)

    readme = Path("./README_template.md").read_text(encoding="utf-8")
    models_text = ""
    for url, models in url_models.items():
        if not models:
            continue
        models_text += f"- {url}\n"
        models_text += "".join(f"  - {model_info['name']}\n" for model_info in models)

    Path("./README.md").write_text(
        readme.format(models_text=models_text), encoding="utf-8"
    )

    time_now = int(time.time())

    for url in url_models.keys():
        request_success_time[url] = time_now

    urls = [
        url
        for url in urls
        if time_now - request_success_time.get(url, 0) < MAX_ALIVE_INTERVAL
    ]

    urls_path.write_text(json.dumps(urls, indent=2), encoding="utf-8")
    request_success_time_path.write_text(
        json.dumps(request_success_time, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
