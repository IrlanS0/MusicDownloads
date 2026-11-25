"""CLI para remessas de áudio com download e conversão independentes."""

import argparse
import asyncio
import csv
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import yaml


FORMATS = {"mp3", "m4a", "opus", "original"}


# Resolve a pasta de músicas do usuário conforme o sistema operacional.
def music_directory() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        from uuid import UUID

        # FOLDERID_Music: usa a localização real do Windows, inclusive pastas redirecionadas.
        folder_id = UUID("4bd8d571-6d19-48d3-be97-422220080e43")
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(folder_id.bytes_le)
        result = ctypes.c_wchar_p()
        shell = ctypes.windll.shell32
        shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        shell.SHGetKnownFolderPath.restype = ctypes.c_long
        if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result)) == 0:
            try:
                return Path(result.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(result)
        raise OSError("não foi possível localizar a pasta Músicas do Windows")
    if sys.platform == "darwin":
        return home / "Music"
    config = home / ".config" / "user-dirs.dirs"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r'\s*XDG_MUSIC_DIR="(.*)"\s*', line)
            if match:
                value = match.group(1).replace("$HOME", str(home))
                path = Path(value)
                if path.is_absolute() and (path == home or home in path.parents):
                    return path
    return home / "Music"


# Valida e sanitiza nomes de arquivos e pastas.
def safe_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nome/pasta deve ser texto não vazio")
    if value in {".", ".."} or value.startswith(".") or "/" in value or "\\" in value:
        raise ValueError(f"nome/pasta inseguro: {value!r}")
    cleaned = re.sub(r'[\x00-\x1f<>:"|?*]', "_", value).strip().rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"nome/pasta inválido: {value!r}")
    return cleaned[:160]


# Confere se um valor inteiro está dentro dos limites permitidos.
def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} deve ser inteiro entre {low} e {high}")
    return value


# Lê a remessa YAML e valida seus itens e configurações.
def read_manifest(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_manifest(data)


# Valida a estrutura de uma remessa, independentemente da origem dos dados.
def validate_manifest(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("a remessa deve ser um objeto YAML")
    if "pasta" in data or "musicas" in data:
        raise ValueError("formato antigo: use 'albuns' com 'nome' e 'musicas' em cada álbum")
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
    albums = data.get("albuns")
    if not isinstance(albums, list) or not albums:
        raise ValueError("albuns deve ser uma lista não vazia")
    songs = []
    seen_albums = set()
    album_names = []
    for album_index, album_data in enumerate(albums, 1):
        if not isinstance(album_data, dict):
            raise ValueError(f"álbum {album_index}: esperado nome e lista de músicas")
        album = safe_name(album_data.get("nome"))
        if album.casefold() in seen_albums:
            raise ValueError(f"álbum {album_index}: nome repetido: {album}")
        seen_albums.add(album.casefold())
        album_names.append(album)
        rows = album_data.get("musicas")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"álbum {album}: musicas deve ser uma lista não vazia")
        seen_names = set()
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"álbum {album}, item {idx}: esperado nome e url")
            name = safe_name(row.get("nome"))
            if name.casefold() in seen_names:
                log_message(f"Aviso: álbum {album}, item {idx}: música repetida '{name}'; ignorada (primeira ocorrência mantida).", file=sys.stderr)
                continue
            url = row.get("url")
            if not isinstance(url, str):
                raise ValueError(f"álbum {album}, item {idx}: URL inválida")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"} or parsed.username or parsed.password:
                raise ValueError(f"álbum {album}, item {idx}: somente URLs HTTPS do YouTube são aceitas")
            seen_names.add(name.casefold())
            key = hashlib.sha256((album + "\0" + name + "\0" + url).encode()).hexdigest()[:16]
            songs.append({"album": album, "name": name, "url": url, "key": key})
    return {"albums": album_names, "format": fmt, "quality": quality, "config": limits, "songs": songs}


# Monta uma remessa a partir de linhas inseridas no terminal ou importadas.
def manifest_from_rows(rows):
    albums = {}
    for album, name, url in rows:
        label = album.strip()
        key = label.casefold()
        albums.setdefault(key, {"nome": label, "musicas": []})["musicas"].append({"nome": name.strip(), "url": url.strip()})
    return validate_manifest({"albuns": list(albums.values())})


# Importa faixas de um CSV com cabeçalho ou de um TXT separado por barras verticais.
def read_song_list(path: Path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        if path.suffix.casefold() == ".csv":
            reader = csv.DictReader(source)
            if reader.fieldnames is None or [field.strip().casefold() for field in reader.fieldnames] != ["album", "nome", "url"]:
                raise ValueError("CSV: o cabeçalho deve ser album,nome,url, nessa ordem")
            for line, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"CSV, linha {line}: esperado album,nome,url")
                rows.append(tuple(row[field].strip() for field in reader.fieldnames))
        elif path.suffix.casefold() == ".txt":
            for line, content in enumerate(source, 1):
                content = content.strip()
                if not content or content.startswith("#"):
                    continue
                fields = [field.strip() for field in content.split("|")]
                if len(fields) != 3:
                    raise ValueError(f"TXT, linha {line}: esperado álbum | nome | URL")
                rows.append(tuple(fields))
        else:
            raise ValueError("a lista de músicas deve ter extensão .csv ou .txt")
    if not rows:
        raise ValueError("a lista de músicas está vazia")
    return manifest_from_rows(rows)


# Verifica as ferramentas externas necessárias ao processamento.
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


# Grava o relatório substituindo o arquivo anterior atomicamente.
def write_state(path: Path, data: dict):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# Executa uma ferramenta externa e encerra o processo se a tarefa for cancelada.
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


# Limpa a linha da animação antes de escrever uma mensagem em português.
def log_message(message, *, file=None, flush=True):
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[2K")
        sys.stderr.flush()
    print(message, file=file, flush=flush)


# Atualiza um indicador visual enquanto as tarefas de áudio estão em execução.
async def animate_loading():
    for frame in itertools.cycle("|/-\\"):
        sys.stderr.write(f"\r{frame} Processando remessa...")
        sys.stderr.flush()
        await asyncio.sleep(0.12)


# Mantém a animação ativa no terminal e garante sua limpeza ao terminar.
@asynccontextmanager
async def loading_indicator():
    animation = asyncio.create_task(animate_loading()) if sys.stderr.isatty() else None
    try:
        yield
    finally:
        if animation is not None:
            animation.cancel()
            await asyncio.gather(animation, return_exceptions=True)
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()


# Baixa e converte uma faixa, respeitando limites e novas tentativas.
async def run_song(song, manifest, destination, download_limit, convert_limit, logs=None):
    key = song["key"]
    album_destination = destination / song["album"]
    album_destination.mkdir(parents=True, exist_ok=True)
    logs = logs or destination
    log_dir = logs / key
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "execucao.log"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"musics-{key}-") as temporary:
        temp = Path(temporary)
        for attempt in range(1, manifest["config"]["attempts"] + 1):
            try:
                log_message(f"[{song['name']}] download (tentativa {attempt})")
                async with download_limit:
                    await process(["yt-dlp", "--ignore-config", "--no-playlist", "--no-overwrites", "--concurrent-fragments", "1", "-f", "bestaudio/best", "-o", str(temp / "audio.%(ext)s"), song["url"]], log)
                candidates = [p for p in temp.glob("audio.*") if p.is_file() and not p.name.endswith((".part", ".ytdl")) and p.stat().st_size > 0]
                if len(candidates) != 1:
                    raise RuntimeError("download não produziu exatamente um arquivo de áudio")
                source = candidates[0]
                async with convert_limit:
                    log_message(f"[{song['name']}] conversão")
                    fmt = manifest["format"]
                    extension = source.suffix if fmt == "original" else "." + fmt
                    target = album_destination / (song["name"] + extension)
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
                    # Copia primeiro para o mesmo volume do destino; o rename final é atômico.
                    with tempfile.TemporaryDirectory(prefix=".musics-", dir=album_destination) as publish_dir:
                        local_staging = Path(publish_dir) / target.name
                        shutil.copyfile(staging, local_staging)
                        if target.exists() or target.is_symlink():
                            raise RuntimeError(f"destino já existe: {target}; não foi sobrescrito")
                        os.replace(local_staging, target)
                log_message(f"[{song['name']}] concluído: {target}")
                return {"status": "concluido", "album": song["album"], "file": target.name, "seconds": round(time.monotonic() - started, 1)}
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError) as exc:
                error = str(exc)
                log_message(f"[{song['name']}] falha: {error}", file=sys.stderr)
                if attempt < manifest["config"]["attempts"] and not (album_destination / (song["name"] + ("." + manifest["format"] if manifest["format"] != "original" else ""))).exists():
                    await asyncio.sleep(manifest["config"]["delay"] * attempt)
                    continue
                return {"status": "falhou", "error": error, "attempts": attempt}


# Coordena as tarefas concorrentes, a retomada e a persistência dos resultados.
async def execute(manifest, destination, resume, logs=None):
    destination.mkdir(parents=True, exist_ok=True)
    logs = logs or destination
    logs.mkdir(parents=True, exist_ok=True)
    state_path = logs / "resultado.json"
    sessions = logs / "sessoes"
    sessions.mkdir(exist_ok=True)
    session = sessions / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-{os.getpid()}")
    session.mkdir()
    state = json.loads(state_path.read_text(encoding="utf-8")) if resume and state_path.exists() else {}
    if not isinstance(state, dict):
        raise ValueError("resultado.json inválido")
    retry_path = manifest.get("_retry_file", Path.cwd() / "downloads" / "retomada.json")
    queue = read_retry_queue(retry_path)
    entries = [retry_entry(song, manifest, destination, logs) for song in manifest["songs"]]
    for entry in entries:
        queue["items"] = [item for item in queue["items"] if item != entry]
        queue["items"].append(entry)
    retry_path.parent.mkdir(parents=True, exist_ok=True)
    write_state(retry_path, queue)
    dl_limit = asyncio.Semaphore(manifest["config"]["downloads"])
    cv_limit = asyncio.Semaphore(manifest["config"]["conversions"])
    tasks = []
    for song in manifest["songs"]:
        previous = state.get(song["key"])
        if resume and isinstance(previous, dict) and previous.get("status") == "concluido" and previous.get("album") == song["album"] and isinstance(previous.get("file"), str) and previous["file"] == song["name"] + Path(previous["file"]).suffix and (destination / song["album"] / previous["file"]).is_file():
            log_message(f"[{song['name']}] já concluído")
            queue["items"].remove(retry_entry(song, manifest, destination, logs))
            write_state(retry_path, queue)
            continue
        tasks.append(asyncio.create_task(named_task(song, manifest, destination, dl_limit, cv_limit, session)))
    try:
        for future in asyncio.as_completed(tasks):
            song, result = await future
            state[song["key"]] = result
            write_state(state_path, state)
            if result["status"] == "concluido":
                queue["items"].remove(retry_entry(song, manifest, destination, logs))
            write_state(retry_path, queue)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        prune_sessions(sessions)
    current = [state.get(song["key"]) for song in manifest["songs"]]
    counts = {status: sum(isinstance(row, dict) and row.get("status") == status for row in current) for status in ("concluido", "falhou")}
    log_message(f"Resultado: {counts['concluido']} concluídos, {counts['falhou']} falhos. Relatório: {state_path}")
    if queue["items"]:
        log_message(f"Retomada: {retry_path} — use 'musics -r' ou 'musics -r -dir'.")
    return not counts["falhou"]


# Guarda a faixa, suas configurações e o destino necessários para uma nova tentativa.
def retry_entry(song, manifest, destination, logs):
    return {"album": song["album"], "name": song["name"], "url": song["url"],
            "format": manifest.get("format", "mp3"), "quality": manifest.get("quality", 192),
            "config": manifest["config"], "destination": str(destination.resolve()), "logs": str(logs.resolve())}


# Lê a fila persistente sem descartar itens de outras remessas.
def read_retry_queue(path):
    if not path.exists():
        return {"version": 1, "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("arquivo de retomada inválido")
    for item in data["items"]:
        if not isinstance(item, dict) or not all(key in item for key in ("album", "name", "url", "format", "quality", "config", "destination", "logs")):
            raise ValueError("item inválido no arquivo de retomada")
    return data


# Reconstrói uma remessa validada a partir de um item da fila de retomada.
def manifest_from_retry(item):
    config = item["config"]
    if not isinstance(config, dict):
        raise ValueError("configuração de retomada inválida")
    return validate_manifest({"formato": item["format"], "qualidade": item["quality"],
        "execucao": {"downloads_simultaneos": config.get("downloads", 5), "conversoes_simultaneas": config.get("conversions", 2),
                     "tentativas": config.get("attempts", 3), "intervalo_tentativas": config.get("delay", 3)},
        "albuns": [{"nome": item["album"], "musicas": [{"nome": item["name"], "url": item["url"]}]}]})


# Retoma a primeira faixa pendente ou todos os itens de uma fila, preservando as demais.
def resume_queue(args):
    path = Path(args.directory).expanduser() if args.directory else Path.cwd() / "downloads" / "retomada.json"
    if not path.is_file():
        raise ValueError(f"arquivo de retomada não encontrado: {path}")
    queue = read_retry_queue(path)
    items = queue["items"] if args.directory is not None else queue["items"][:1]
    if not items:
        print("Nenhuma música pendente para retomar.")
        return 0
    groups = {}
    for item in items:
        manifest = manifest_from_retry(item)
        destination = args.destination.expanduser() if args.destination else Path(item["destination"])
        logs = Path(item["logs"])
        key = (str(destination), str(logs), manifest["format"], manifest["quality"], json.dumps(manifest["config"], sort_keys=True))
        if key in groups:
            groups[key][0]["songs"].extend(manifest["songs"])
        else:
            manifest["_retry_file"] = path
            groups[key] = (manifest, destination, logs)
    if not check_tools():
        return 1
    if not args.yes and input(f"Retomar {len(items)} música(s)? [s/N] ").strip().casefold() not in {"s", "sim"}:
        print("Cancelado.")
        return 0
    if args.destination:
        # A alteração de destino também atualiza os itens originais da fila.
        for item in items:
            item["destination"] = str(args.destination.expanduser().resolve())
        write_state(path, queue)
    success = True
    for manifest, destination, logs in groups.values():
        success = asyncio.run(execute_with_loading(manifest, destination, True, logs)) and success
    return 0 if success else 1


# Associa o resultado assíncrono à faixa que o produziu.
async def named_task(song, manifest, destination, dl_limit, cv_limit, logs):
    return song, await run_song(song, manifest, destination, dl_limit, cv_limit, logs)


# Conserva as três sessões mais recentes e remove apenas diretórios de sessão antigos.
def prune_sessions(sessions: Path):
    previous = sorted((path for path in sessions.iterdir() if path.is_dir() and not path.is_symlink()), reverse=True)
    for old in previous[3:]:
        shutil.rmtree(old)


# Executa a remessa com animação de atividade no terminal interativo.
async def execute_with_loading(manifest, destination, resume, logs):
    async with loading_indicator():
        return await execute(manifest, destination, resume, logs)


class PortugueseParser(argparse.ArgumentParser):
    # Apresenta erros de argumentos em português, preservando os nomes das flags.
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"Erro: argumentos inválidos ou conflitantes. Consulte '{self.prog} -h'.\n")

    # Traduz o rótulo de uso produzido pelo argparse.
    def format_usage(self):
        return super().format_usage().replace("usage:", "Uso:", 1)

    # Traduz o cabeçalho da ajuda sem alterar os comandos.
    def format_help(self):
        return super().format_help().replace("usage:", "Uso:", 1)


# Define as flags em inglês e suas descrições em português.
def build_parser():
    parser = PortugueseParser(prog="musics", add_help=False, allow_abbrev=False,
                              description="Baixa e organiza remessas de áudio.")
    parser._optionals.title = "Opções"
    parser.add_argument("-h", "--help", action="help", help="mostra esta ajuda e sai")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("-dg", "--diagnose", action="store_true", help="verifica as dependências")
    actions.add_argument("-v", "--validate", type=Path, metavar="ARQUIVO", help="valida uma remessa YAML")
    actions.add_argument("-d", "--download", type=Path, metavar="ARQUIVO", help="baixa uma remessa")
    actions.add_argument("-r", "--resume", nargs="?", const=True, type=Path, metavar="ARQUIVO", help="retoma uma faixa pendente ou uma remessa indicada")
    parser.add_argument("-dir", "--directory", nargs="?", const="", metavar="ARQUIVO", help="com -r, retoma uma lista; sem caminho, usa downloads/retomada.json")
    parser.add_argument("-de", "--destination", type=Path, metavar="PASTA",
                        default=None, help="substitui a pasta de músicas padrão")
    parser.add_argument("-y", "--yes", action="store_true", help="confirma a execução sem perguntar")
    return parser


# Define as opções para cadastrar uma faixa ou importar uma lista de faixas.
def build_add_parser():
    parser = PortugueseParser(prog="music add", add_help=False, allow_abbrev=False,
                              description="Adiciona uma música ou importa uma lista de músicas.")
    parser._optionals.title = "Opções"
    parser.add_argument("-h", "--help", action="help", help="mostra esta ajuda e sai")
    parser.add_argument("-dir", "--directory", nargs="?", const="", metavar="ARQUIVO",
                        help="importa várias músicas de um arquivo CSV ou TXT; sem arquivo, pergunta o caminho")
    parser.add_argument("-de", "--destination", type=Path, metavar="PASTA",
                        help="substitui a pasta de músicas padrão")
    parser.add_argument("-y", "--yes", action="store_true", help="confirma a importação sem perguntar")
    return parser


# Escolhe um diretório de logs estável para cada arquivo de entrada.
def logs_for_file(path: Path):
    identifier = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:8]
    return Path.cwd() / "downloads" / f"{safe_name(path.stem)}-{identifier}"


# Solicita os dados e inicia o download de uma ou várias faixas.
def add_songs(argv):
    args = build_add_parser().parse_args(argv)
    if args.directory is None:
        album = input("Nome do álbum: ").strip()
        name = input("Nome da música: ").strip()
        url = input("URL da música: ").strip()
        manifest = manifest_from_rows([(album, name, url)])
        logs = Path.cwd() / "downloads" / f"add-{manifest['songs'][0]['key']}"
    else:
        path = Path(args.directory or input("Caminho do arquivo CSV ou TXT: ").strip()).expanduser()
        manifest = read_song_list(path)
        logs = logs_for_file(path)
    destination = args.destination.expanduser() if args.destination else music_directory()
    print(f"Remessa: {len(manifest['albums'])} álbum(ns), {len(manifest['songs'])} música(s) | destino: {destination}")
    if not check_tools():
        return 1
    if args.directory is not None and not args.yes and input("Você tem autorização para baixar esses itens e deseja continuar? [s/N] ").strip().casefold() not in {"s", "sim"}:
        print("Cancelado.")
        return 0
    return 0 if asyncio.run(execute_with_loading(manifest, destination, True, logs)) else 1


# Interpreta os argumentos e encaminha a operação solicitada pelo usuário.
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "add":
        try:
            return add_songs(argv[1:])
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError, EOFError) as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("Interrompido; execute novamente para continuar.", file=sys.stderr)
            return 130
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.directory is not None and (args.resume is None or args.resume is not True):
        parser.error("use -r -dir [ARQUIVO]")
    try:
        if args.diagnose:
            return 0 if check_tools() else 1
        if args.resume is True and (not args.directory or Path(args.directory).suffix.casefold() == ".json"):
            return resume_queue(args)
        if args.directory:
            manifest_path = Path(args.directory).expanduser()
            manifest = read_song_list(manifest_path) if manifest_path.suffix.casefold() in {".txt", ".csv"} else read_manifest(manifest_path)
        else:
            manifest_path = args.validate or args.download or args.resume
            manifest = read_song_list(manifest_path) if args.resume and manifest_path.suffix.casefold() in {".txt", ".csv"} else read_manifest(manifest_path)
        destination = args.destination.expanduser() if args.destination else music_directory()
        logs = logs_for_file(manifest_path)
        print(f"Remessa: {len(manifest['albums'])} álbuns, {len(manifest['songs'])} músicas | {manifest['format']} | destino: {destination}")
        if args.validate:
            return 0
        if not check_tools():
            return 1
        if not args.yes and input("Você tem autorização para baixar esses itens e deseja continuar? [s/N] ").strip().casefold() not in {"s", "sim"}:
            print("Cancelado.")
            return 0
        return 0 if asyncio.run(execute_with_loading(manifest, destination, bool(args.resume), logs)) else 1
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrompido; use 'musics -r -dir' para continuar.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
