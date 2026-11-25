"""CLI para remessas de áudio com download e conversão independentes."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

import yaml


FORMATS = {"mp3", "m4a", "opus", "original"}


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nome/pasta deve ser texto não vazio")
    if value in {".", ".."} or value.startswith(".") or "/" in value or "\\" in value:
        raise ValueError(f"nome/pasta inseguro: {value!r}")
    cleaned = re.sub(r'[\x00-\x1f<>:"|?*]', "_", value).strip().rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"nome/pasta inválido: {value!r}")
    return cleaned[:160]


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} deve ser inteiro entre {low} e {high}")
    return value


def read_manifest(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("a remessa deve ser um objeto YAML")
    folder = safe_name(data.get("pasta"))
    fmt = data.get("formato", "mp3")
    if fmt not in FORMATS:
        raise ValueError(f"formato deve ser um de {', '.join(sorted(FORMATS))}")
    quality = integer(data.get("qualidade", 192), "qualidade", 32, 320)
    config = data.get("execucao", {})
    if not isinstance(config, dict):
        raise ValueError("execucao deve ser um objeto")
    limits = {
        "downloads": integer(config.get("downloads_simultaneos", 5), "downloads_simultaneos", 1, 5),
        "conversions": integer(config.get("conversoes_simultaneas", 2), "conversoes_simultaneas", 1, 2),
        "attempts": integer(config.get("tentativas", 3), "tentativas", 1, 10),
        "delay": integer(config.get("intervalo_tentativas", 3), "intervalo_tentativas", 0, 60),
    }
    rows = data.get("musicas")
    if not isinstance(rows, list) or not rows:
        raise ValueError("musicas deve ser uma lista não vazia")
    songs = []
    seen_names = set()
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"item {idx}: esperado nome e url")
        name = safe_name(row.get("nome"))
        url = row.get("url")
        if not isinstance(url, str):
            raise ValueError(f"item {idx}: URL inválida")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"} or parsed.username or parsed.password:
            raise ValueError(f"item {idx}: somente URLs HTTPS do YouTube são aceitas")
        if name.casefold() in seen_names:
            raise ValueError(f"item {idx}: nome repetido: {name}")
        seen_names.add(name.casefold())
        key = hashlib.sha256((name + "\0" + url).encode()).hexdigest()[:16]
        songs.append({"name": name, "url": url, "key": key})
    return {"folder": folder, "format": fmt, "quality": quality, "config": limits, "songs": songs}


def check_tools():
    missing = []
    for name in ("yt-dlp", "ffmpeg", "ffprobe"):
        binary = shutil.which(name)
        if not binary:
            missing.append(name)
            print(f"{name}: ausente")
            continue
        result = subprocess.run([binary, "--version" if name == "yt-dlp" else "-version"], capture_output=True, text=True, timeout=10)
        print(f"{name}: {result.stdout.splitlines()[0] if result.stdout else 'versão desconhecida'}")
    runtimes = [name for name in ("deno", "node", "bun", "qjs") if shutil.which(name)]
    print("runtime JavaScript: " + (", ".join(runtimes) if runtimes else "ausente; suporte YouTube pode falhar"))
    return not missing


def write_state(path: Path, data: dict):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


async def process(command: list[str], log: Path):
    with log.open("ab") as output:
        proc = await asyncio.create_subprocess_exec(*command, stdout=output, stderr=asyncio.subprocess.STDOUT)
        try:
            code = await proc.wait()
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            raise
    if code:
        raise RuntimeError(f"{Path(command[0]).name} terminou com código {code}; consulte {log}")


async def run_song(song, manifest, destination, download_limit, convert_limit):
    key = song["key"]
    temp = destination / ".trabalho" / key
    temp.mkdir(parents=True, exist_ok=True)
    log = temp / "execucao.log"
    started = time.monotonic()
    for attempt in range(1, manifest["config"]["attempts"] + 1):
        try:
            print(f"[{song['name']}] download (tentativa {attempt})", flush=True)
            async with download_limit:
                # O template é fixo; cada item tem uma área isolada.
                await process(["yt-dlp", "--ignore-config", "--no-playlist", "--no-overwrites", "--concurrent-fragments", "1", "-f", "bestaudio/best", "-o", str(temp / "audio.%(ext)s"), song["url"]], log)
            candidates = [p for p in temp.glob("audio.*") if p.is_file() and not p.name.endswith((".part", ".ytdl")) and p.stat().st_size > 0]
            if len(candidates) != 1:
                raise RuntimeError("download não produziu exatamente um arquivo de áudio")
            source = candidates[0]
            async with convert_limit:
                print(f"[{song['name']}] conversão", flush=True)
                fmt = manifest["format"]
                extension = source.suffix if fmt == "original" else "." + fmt
                target = destination / (song["name"] + extension)
                if target.exists():
                    raise RuntimeError(f"destino já existe: {target}; não foi sobrescrito")
                staging = temp / ("convertido" + extension)
                if fmt == "original":
                    os.replace(source, staging)
                else:
                    codec = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus"}[fmt]
                    await process(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-map", "0:a:0", "-c:a", codec, "-b:a", f"{manifest['quality']}k", str(staging)], log)
                    if not staging.is_file() or not staging.stat().st_size:
                        raise RuntimeError("conversão não produziu arquivo válido")
                os.replace(staging, target)
            print(f"[{song['name']}] concluído: {target}", flush=True)
            return {"status": "concluido", "file": target.name, "seconds": round(time.monotonic() - started, 1)}
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError) as exc:
            error = str(exc)
            print(f"[{song['name']}] falha: {error}", file=sys.stderr, flush=True)
            if attempt < manifest["config"]["attempts"] and not (destination / (song["name"] + ("." + manifest["format"] if manifest["format"] != "original" else ""))).exists():
                await asyncio.sleep(manifest["config"]["delay"] * attempt)
                continue
            return {"status": "falhou", "error": error, "attempts": attempt}


async def execute(manifest, destination, resume):
    destination.mkdir(parents=True, exist_ok=True)
    state_path = destination / "resultado.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if resume and state_path.exists() else {}
    if not isinstance(state, dict):
        raise ValueError("resultado.json inválido")
    dl_limit = asyncio.Semaphore(manifest["config"]["downloads"])
    cv_limit = asyncio.Semaphore(manifest["config"]["conversions"])
    tasks = []
    for song in manifest["songs"]:
        previous = state.get(song["key"])
        if resume and isinstance(previous, dict) and previous.get("status") == "concluido" and isinstance(previous.get("file"), str) and (destination / previous["file"]).is_file():
            print(f"[{song['name']}] já concluído")
            continue
        tasks.append(asyncio.create_task(named_task(song, manifest, destination, dl_limit, cv_limit)))
    try:
        for future in asyncio.as_completed(tasks):
            song, result = await future
            state[song["key"]] = result
            write_state(state_path, state)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    counts = {status: sum(row.get("status") == status for row in state.values() if isinstance(row, dict)) for status in ("concluido", "falhou")}
    print(f"Resultado: {counts['concluido']} concluídos, {counts['falhou']} falhos. Relatório: {state_path}")
    return not counts["falhou"]


async def named_task(song, manifest, destination, dl_limit, cv_limit):
    return song, await run_song(song, manifest, destination, dl_limit, cv_limit)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="musicas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnostico")
    for action in ("validar", "baixar", "retomar"):
        item = sub.add_parser(action)
        item.add_argument("remessa", type=Path)
        item.add_argument("--destino", type=Path, default=Path.cwd() / "downloads")
        if action != "validar":
            item.add_argument("--sim", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "diagnostico":
            return 0 if check_tools() else 1
        manifest = read_manifest(args.remessa)
        destination = args.destino.expanduser().resolve() / manifest["folder"]
        print(f"Remessa: {manifest['folder']} | {len(manifest['songs'])} músicas | {manifest['format']} | destino: {destination}")
        if args.command == "validar":
            return 0
        if not check_tools():
            return 1
        if not args.sim and input("Você tem autorização para baixar esses itens e deseja continuar? [s/N] ").strip().casefold() not in {"s", "sim"}:
            print("Cancelado.")
            return 0
        return 0 if asyncio.run(execute(manifest, destination, args.command == "retomar")) else 1
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrompido; use 'musicas retomar' para continuar.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
