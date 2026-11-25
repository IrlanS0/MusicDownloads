import asyncio
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remessa_musicas.cli import build_parser, execute, loading_indicator, main, music_directory, prune_sessions, read_manifest, read_song_list, retry_entry, logs_for_file, run_song, manifest_from_rows


class CommandTests(unittest.TestCase):
    # Confere que editar a retomada CSV atualiza a fila sem modificar o arquivo original.
    def test_resume_csv_edits_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "lista.csv"
            content = "album,nome,url\nÁlbum,Faixa,https://youtu.be/old\n"
            source.write_text(content, encoding="utf-8")
            manifest = read_song_list(source)
            with patch("pathlib.Path.cwd", return_value=root):
                logs = logs_for_file(source)
                queue = root / "downloads" / "retomada.json"
                queue.parent.mkdir()
                queue.write_text(json.dumps({"version": 1, "items": [retry_entry(manifest["songs"][0], manifest, root / "audio", logs)]}))
                with patch("remessa_musicas.cli.check_tools", return_value=True), patch("remessa_musicas.cli.execute_with_loading", return_value=False) as run, patch("builtins.input", side_effect=["s", "s", "https://youtu.be/new"]):
                    self.assertEqual(main(["-r", "-dir", str(source), "-de", str(root / "audio")]), 1)
            self.assertEqual(run.call_args.args[0]["songs"][0]["url"], "https://youtu.be/new")
            self.assertEqual(json.loads(queue.read_text())["items"][0]["url"], "https://youtu.be/new")
            self.assertEqual(source.read_text(encoding="utf-8"), content)

    # Confere o cadastro interativo e o download imediato sem invocar ferramentas externas.
    def test_add_single(self):
        with tempfile.TemporaryDirectory() as temp:
            values = iter(["Meu álbum", "Minha faixa", "https://youtu.be/example"])
            async def fake_execute(*args):
                return True

            with patch("builtins.input", side_effect=lambda _: next(values)), patch("remessa_musicas.cli.check_tools", return_value=True), patch("remessa_musicas.cli.execute_with_loading", side_effect=fake_execute) as run:
                self.assertEqual(main(["add", "-de", temp]), 0)
            manifest, destination, resume, logs = run.call_args.args
            self.assertEqual(manifest["songs"][0]["album"], "Meu álbum")
            self.assertEqual(destination, Path(temp))
            self.assertTrue(resume)
            self.assertIn("downloads/add-", str(logs))

    # Confere o carregamento de lotes de arquivos e a confirmação antes de baixar.
    def test_add_from_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lista.csv"
            path.write_text("album,nome,url\nÁlbum 1,Faixa 1,https://youtu.be/one\nÁlbum 2,Faixa 2,https://youtu.be/two\n", encoding="utf-8")
            async def fake_execute(*args):
                return True

            with patch("remessa_musicas.cli.check_tools", return_value=True), patch("remessa_musicas.cli.execute_with_loading", side_effect=fake_execute) as run, patch("builtins.input", return_value="s"):
                self.assertEqual(main(["add", "-dir", str(path)]), 0)
            self.assertEqual(run.call_args.args[0]["albums"], ["Álbum 1", "Álbum 2"])

    # Verifica aliases e conflitos nas flags com prefixos compartilhados.
    def test_flags(self):
        parser = build_parser()
        for short, long, field in (("-v", "--validate", "validate"), ("-d", "--download", "download"), ("-r", "--resume", "resume")):
            self.assertEqual(getattr(parser.parse_args([short, "test.yaml"]), field), Path("test.yaml"))
            self.assertEqual(getattr(parser.parse_args([long, "test.yaml"]), field), Path("test.yaml"))
        self.assertTrue(parser.parse_args(["-dg"]).diagnose)
        args = parser.parse_args(["-d", "test.yaml", "-de", "audio", "-y"])
        self.assertEqual(args.destination, Path("audio"))
        self.assertTrue(args.yes)
        with patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as error:
                parser.parse_args(["-dg", "-d", "test.yaml"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("argumentos inválidos", output.getvalue())

    # Garante que validar não exige ferramentas de download instaladas.
    def test_validation_without_external_tools(self):
        with patch("remessa_musicas.cli.check_tools") as tools:
            self.assertEqual(main(["-v", "exemplos/remessa.yaml"]), 0)
            tools.assert_not_called()


class ManifestTests(unittest.TestCase):
    # Evita o mesmo vídeo no álbum, inclusive com URLs diferentes e parâmetros extras.
    def test_duplicate_video_links(self):
        rows = [("Álbum", "Primeira", "https://www.youtube.com/watch?v=AbC123&list=lista"),
                ("Álbum", "Mesmo link", "https://www.youtube.com/watch?v=AbC123&list=lista"),
                ("Álbum", "Curto", "https://youtu.be/AbC123?t=30"),
                ("Álbum", "Short", "https://www.youtube.com/shorts/AbC123"),
                ("Álbum", "Outro vídeo", "https://music.youtube.com/watch?v=abc123"),
                ("Outro álbum", "Permitida", "https://youtu.be/AbC123")]
        with patch("sys.stderr", new_callable=io.StringIO) as warnings:
            manifest = manifest_from_rows(rows)
        self.assertEqual([song["name"] for song in manifest["songs"]], ["Primeira", "Outro vídeo", "Permitida"])
        self.assertEqual(warnings.getvalue().count("link repetido"), 3)

    # Agrupa linhas de um álbum, ignora duplicatas e rejeita listas malformadas.
    def test_import_formats(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lista.txt"
            path.write_text("# Comentário\nÁlbum | Faixa 1 | https://youtu.be/one\nÁlbum | Faixa 2 | https://youtu.be/two\n", encoding="utf-8")
            manifest = read_song_list(path)
            self.assertEqual(manifest["albums"], ["Álbum"])
            self.assertEqual(len(manifest["songs"]), 2)
            path.write_text("Álbum | Faixa | https://youtu.be/one\nÁlbum | Faixa | https://youtu.be/two\n", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO) as warnings:
                manifest = read_song_list(path)
            self.assertEqual(len(manifest["songs"]), 1)
            self.assertEqual(manifest["songs"][0]["url"], "https://youtu.be/one")
            self.assertIn("música repetida", warnings.getvalue())
            path.write_text("Álbum | linha incompleta\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "linha 1"):
                read_song_list(path)

    def test_music_directory_linux_xdg(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".config").mkdir()
            (home / ".config" / "user-dirs.dirs").write_text('XDG_MUSIC_DIR="$HOME/Músicas"\n')
            with patch("pathlib.Path.home", return_value=home), patch("sys.platform", "linux"):
                self.assertEqual(music_directory(), home / "Músicas")

    def test_prune_keeps_three_latest_sessions_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "resultado.json").write_text("{}")
            sessions = root / "sessoes"
            sessions.mkdir()
            for number in range(5):
                folder = sessions / str(number)
                folder.mkdir()
                (folder / "execucao.log").write_text("log")
            prune_sessions(sessions)
            self.assertEqual(sorted(path.name for path in sessions.iterdir()), ["2", "3", "4"])
            self.assertTrue((root / "resultado.json").exists())

    def test_rejects_path_traversal_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remessa.yaml"
            path.write_text('albuns:\n  - nome: "../fora"\n    musicas:\n      - nome: Teste\n        url: https://youtu.be/example\n')
            with self.assertRaises(ValueError):
                read_manifest(path)
            path.write_text('albuns:\n  - nome: Dentro\n    musicas:\n      - nome: Teste\n        url: https://youtu.be/one\n      - nome: teste\n        url: https://youtu.be/two\n')
            with patch("sys.stderr", new_callable=io.StringIO) as warnings:
                manifest = read_manifest(path)
            self.assertEqual(len(manifest["songs"]), 1)
            self.assertEqual(manifest["songs"][0]["url"], "https://youtu.be/one")
            self.assertIn("música repetida", warnings.getvalue())
            path.write_text('pasta: Antigo\nmusicas:\n  - nome: Teste\n    url: https://youtu.be/one\n')
            with self.assertRaisesRegex(ValueError, "formato antigo"):
                read_manifest(path)

    def test_two_albums_allow_same_song_name_and_have_distinct_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remessa.yaml"
            path.write_text('albuns:\n  - nome: Álbum 1\n    musicas:\n      - nome: Faixa\n        url: https://youtu.be/same\n  - nome: Álbum 2\n    musicas:\n      - nome: Faixa\n        url: https://youtu.be/same\n')
            manifest = read_manifest(path)
            self.assertEqual(manifest["albums"], ["Álbum 1", "Álbum 2"])
            self.assertEqual(len({song["key"] for song in manifest["songs"]}), 2)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    # Detecta duplicatas surgidas na retomada antes de enfileirar downloads concorrentes.
    async def test_duplicate_links_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = manifest_from_rows([("Álbum", "Primeira", "https://youtu.be/one"), ("Álbum", "Segunda", "https://youtu.be/two")])
            manifest["songs"][1]["url"] = "https://www.youtube.com/watch?v=one&list=radio"
            manifest["_retry_file"] = root / "retomada.json"
            called = []

            async def fail(song, *args):
                called.append(song["name"])
                return {"status": "falhou", "error": "sem conexão"}

            with patch("remessa_musicas.cli.run_song", fail), patch("sys.stderr", new_callable=io.StringIO) as warnings:
                self.assertFalse(await execute(manifest, root / "audio", False, root / "logs"))
            self.assertEqual(called, ["Primeira"])
            self.assertIn("link repetido", warnings.getvalue())
            self.assertEqual(len(json.loads((root / "retomada.json").read_text())["items"]), 1)

    # Simula volumes diferentes entre /tmp e Músicas durante a publicação do MP3.
    async def test_conversion_publishes_across_filesystems(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "Músicas"
            logs = Path(temp) / "logs"
            song = {"album": "teste", "name": "musics1", "url": "https://youtu.be/example", "key": "faixa"}
            manifest = {"format": "mp3", "quality": 192, "config": {"attempts": 1, "delay": 0}}
            original_replace = os.replace

            async def fake_process(command, log):
                if command[0] == "yt-dlp":
                    Path(command[command.index("-o") + 1].replace("%(ext)s", "webm")).write_bytes(b"audio")
                else:
                    Path(command[-1]).write_bytes(b"mp3")

            def different_volumes(source, destination):
                if Path(destination).parent == audio / "teste" and Path(source).parent.parent != audio / "teste":
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                original_replace(source, destination)

            with patch("remessa_musicas.cli.process", fake_process), patch("remessa_musicas.cli.os.replace", side_effect=different_volumes):
                result = await run_song(song, manifest, audio, asyncio.Semaphore(1), asyncio.Semaphore(1), logs)
            self.assertEqual(result["status"], "concluido")
            self.assertEqual((audio / "teste" / "musics1.mp3").read_bytes(), b"mp3")
            self.assertFalse(list((audio / "teste").glob(".musics-*")))

    async def test_audio_and_logs_use_separate_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "Músicas"
            logs = Path(temp) / "projeto" / "downloads" / "Lote"
            audio.mkdir(parents=True)
            song = {"album": "Lote", "name": "Exemplo", "url": "https://youtu.be/example", "key": "faixa"}
            manifest = {"format": "original", "config": {"attempts": 1, "delay": 0}}

            async def fake_process(command, log):
                Path(command[command.index("-o") + 1].replace("%(ext)s", "webm")).write_bytes(b"audio")
                log.write_text("processado")

            with patch("remessa_musicas.cli.process", fake_process):
                result = await run_song(song, manifest, audio, asyncio.Semaphore(1), asyncio.Semaphore(1), logs)
            self.assertEqual(result["status"], "concluido")
            self.assertTrue((audio / "Lote" / "Exemplo.webm").exists())
            self.assertTrue((logs / "faixa" / "execucao.log").exists())
            self.assertFalse(list(logs.rglob("*.webm")))

    # Confere a animação, sua limpeza e a ausência de códigos de terminal em logs.
    async def test_loading_indicator_cleanup(self):
        terminal = io.StringIO()
        with patch.object(terminal, "isatty", return_value=True), patch("sys.stderr", terminal):
            async with loading_indicator():
                await asyncio.sleep(0.15)
        self.assertIn("Processando remessa...", terminal.getvalue())
        self.assertTrue(terminal.getvalue().endswith("\r\033[2K"))
        redirected = io.StringIO()
        with patch("sys.stderr", redirected):
            async with loading_indicator():
                await asyncio.sleep(0)
        self.assertEqual(redirected.getvalue(), "")

    # Confere se a animação é limpa mesmo ao cancelar o processamento.
    async def test_loading_indicator_cancelled(self):
        terminal = io.StringIO()
        with patch.object(terminal, "isatty", return_value=True), patch("sys.stderr", terminal):
            with self.assertRaises(asyncio.CancelledError):
                async with loading_indicator():
                    await asyncio.sleep(0)
                    raise asyncio.CancelledError
        self.assertTrue(terminal.getvalue().endswith("\r\033[2K"))

    async def test_completion_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)
            songs = [{"album": album, "name": "Faixa", "url": "https://youtu.be/faixa", "key": album} for album in ("um", "dois")]
            manifest = {"songs": songs, "config": {"downloads": 5, "conversions": 2}, "_retry_file": dest / "retomada.json"}
            called = []

            async def fake_run(song, config, destination, dl_limit, cv_limit, logs):
                called.append(song["album"])
                await asyncio.sleep(0.01 if song["album"] == "um" else 0)
                album_dir = destination / song["album"]
                album_dir.mkdir(exist_ok=True)
                (album_dir / "Faixa.mp3").write_bytes(b"audio")
                return {"status": "concluido", "album": song["album"], "file": "Faixa.mp3"}

            with patch("remessa_musicas.cli.run_song", fake_run):
                self.assertTrue(await execute(manifest, dest, False))
                self.assertTrue(await execute(manifest, dest, True))
            self.assertEqual(called, ["um", "dois"])
            self.assertTrue((dest / "resultado.json").is_file())
            self.assertEqual(len(list((dest / "sessoes").iterdir())), 2)
            (dest / "um" / "Faixa.mp3").unlink()
            with patch("remessa_musicas.cli.run_song", fake_run):
                self.assertTrue(await execute(manifest, dest, True))
            self.assertEqual(called, ["um", "dois", "um"])

    # Verifica persistência de falhas e retomada de uma faixa ou de toda a fila.
    async def test_retry_queue_and_single_or_batch_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "retomada.json"
            source = root / "lista.txt"
            source.write_text("Álbum | Um | https://youtu.be/one\nÁlbum | Dois | https://youtu.be/two\n", encoding="utf-8")
            manifest = read_song_list(source)
            manifest["_retry_file"] = queue

            async def fail(song, *args):
                return {"status": "falhou", "error": "sem conexão"}

            with patch("remessa_musicas.cli.run_song", fail):
                self.assertFalse(await execute(manifest, root / "audio", False, root / "logs"))
            self.assertEqual(len(json.loads(queue.read_text())["items"]), 2)

            async def succeed(song, manifest, destination, *args):
                folder = destination / song["album"]
                folder.mkdir(exist_ok=True)
                (folder / (song["name"] + ".mp3")).write_bytes(b"audio")
                return {"status": "concluido", "album": song["album"], "file": song["name"] + ".mp3"}

            # main executa seu próprio loop; roda em thread para testar o comando real.
            with patch("remessa_musicas.cli.run_song", succeed), patch("remessa_musicas.cli.check_tools", return_value=True), patch("pathlib.Path.cwd", return_value=root):
                (root / "downloads").mkdir()
                default_queue = root / "downloads" / "retomada.json"
                queue.replace(default_queue)
                self.assertEqual(await asyncio.to_thread(main, ["-r", "-y"]), 0)
                remaining = json.loads(default_queue.read_text())["items"]
                self.assertEqual(len(remaining), 1)
                with patch("remessa_musicas.cli.run_song", fail), patch("builtins.input", side_effect=["s", "s", "https://example.com/invalido", "https://youtu.be/replacement"]), patch("sys.stderr", new_callable=io.StringIO) as warnings:
                    self.assertEqual(await asyncio.to_thread(main, ["-r", "-dir"]), 1)
                edited = json.loads(default_queue.read_text())["items"]
                self.assertEqual(len(edited), 1)
                self.assertEqual(edited[0]["url"], "https://youtu.be/replacement")
                self.assertIn("somente URLs HTTPS do YouTube", warnings.getvalue())
                with patch("builtins.input", side_effect=["s", "s", ""]):
                    self.assertEqual(await asyncio.to_thread(main, ["-r", "-dir", str(default_queue)]), 0)
                self.assertEqual(json.loads(default_queue.read_text())["items"], [])
                self.assertEqual(await asyncio.to_thread(main, ["-r", "-dir", str(default_queue), "-y"]), 0)


if __name__ == "__main__":
    unittest.main()
