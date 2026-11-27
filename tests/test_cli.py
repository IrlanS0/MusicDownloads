import asyncio
import errno
import io
import json
import os
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remessa_musicas.cli import build_parser, build_add_parser, execute, loading_indicator, loading_line, main, music_directory, prune_sessions, read_manifest, read_song_list, retry_entry, logs_for_file, run_song, manifest_from_rows, concurrency_budget, choose_concurrency


class CommandTests(unittest.TestCase):
    # Exclui somente os áudios pedidos e respeita o cancelamento interativo.
    def test_remove_single_and_cancel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            album = root / "Álbum"
            album.mkdir()
            audio = album / "Faixa.mp3"
            audio.write_bytes(b"audio")
            (album / "Faixa.txt").write_text("conservar")
            (album / "Outra.mp3").write_bytes(b"outra")
            with patch("builtins.input", side_effect=["Álbum", "Faixa", "n"]), patch("remessa_musicas.cli.check_tools") as tools:
                self.assertEqual(main(["rm", "-de", temp]), 0)
                self.assertTrue(audio.exists())
                tools.assert_not_called()
            with patch("builtins.input", side_effect=["Álbum", "Faixa", "s"]):
                self.assertEqual(main(["rm", "-de", temp]), 0)
            self.assertFalse(audio.exists())
            self.assertTrue((album / "Faixa.txt").exists())
            self.assertTrue((album / "Outra.mp3").exists())

    # Remove listas com ou sem URL e rejeita caminhos que escapem da biblioteca.
    def test_remove_files_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "audio"
            (base / "Álbum").mkdir(parents=True)
            for extension, content in (("csv", "album,nome\nÁlbum,Faixa\nÁlbum,Faixa\n"), ("txt", "Álbum | Faixa | https://youtu.be/ignored\n"), ("yaml", "albuns:\n- nome: Álbum\n  musicas:\n  - nome: Faixa\n")):
                path = root / f"lista.{extension}"
                path.write_text(content, encoding="utf-8")
                audio = base / "Álbum" / "Faixa.mp3"
                audio.write_bytes(b"audio")
                self.assertEqual(main(["rm", "-f", str(path), "-de", str(base), "-y"]), 0)
                self.assertFalse(audio.exists())
            outside = root / "fora"
            outside.mkdir()
            (outside / "Faixa.mp3").write_bytes(b"preservar")
            (base / "Atalho").symlink_to(outside, target_is_directory=True)
            for album in ("../fora", "Atalho"):
                with patch("builtins.input", side_effect=[album, "Faixa"]), patch("sys.stderr", new_callable=io.StringIO):
                    self.assertEqual(main(["rm", "-de", str(base), "-y"]), 2)
            self.assertTrue((outside / "Faixa.mp3").exists())

    # Rejeita as flags substituídas sem iniciar qualquer operação.
    def test_removed_flags_are_rejected(self):
        for argv in (["-d", "lista.yaml"], ["--download", "lista.yaml"], ["add", "-dir", "lista.csv"]):
            with patch("sys.stderr", new_callable=io.StringIO), patch("remessa_musicas.cli.check_tools") as tools:
                with self.assertRaises(SystemExit) as error:
                    main(argv)
                self.assertEqual(error.exception.code, 2)
                tools.assert_not_called()

    # Verifica arredondamento, entrada interativa inválida e limites informados por flags.
    def test_concurrency_choices(self):
        for cores, expected in ((1, 1), (2, 1), (4, 3), (8, 6)):
            with patch("remessa_musicas.cli.os.sched_getaffinity", return_value=set(range(cores)), create=True):
                self.assertEqual(concurrency_budget(), expected)
        manifest = {"config": {"downloads": 5, "conversions": 2}}
        args = SimpleNamespace(downloads=None, conversions=None, yes=False)
        with patch("remessa_musicas.cli.concurrency_budget", return_value=3), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["4", "2", "0", "1"]), patch("sys.stderr", new_callable=io.StringIO):
            choose_concurrency(manifest, args)
        self.assertEqual(manifest["config"], {"downloads": 2, "conversions": 1})
        args.downloads = 4
        with patch("remessa_musicas.cli.concurrency_budget", return_value=3):
            with self.assertRaises(ValueError):
                choose_concurrency(manifest, args)

    # Aceita variantes inequívocas sem alterar nomes de arquivos ou valores com sinais.
    def test_flag_spelling_variants(self):
        parser = build_parser()
        for flag in ("-validate", "--VALIDATE", "–validate", "—validate"):
            args = parser.parse_args([flag, "Minha Lista.YAML", "--de=PASTA Com Espaços"])
            self.assertEqual(args.validate, Path("Minha Lista.YAML"))
            self.assertEqual(args.destination, Path("PASTA Com Espaços"))
        args = parser.parse_args(["--r", "--f", "Lista.CSV", "--y"])
        self.assertIs(args.resume, True)
        self.assertEqual(args.file, "Lista.CSV")
        self.assertTrue(args.yes)
        args = build_add_parser().parse_args(["--FILE=Minha Lista.csv", "-destination", "audio"])
        self.assertEqual(args.file, "Minha Lista.csv")
        self.assertEqual(args.destination, Path("audio"))
        args = parser.parse_args(["--validate=-lista.yaml"])
        self.assertEqual(args.validate, Path("-lista.yaml"))

    # Sugere correções e não inicia downloads quando uma flag desconhecida é usada.
    def test_unknown_flags_and_actionable_errors(self):
        for argv, expected in ((["--validte", "lista.yaml"], "--validate"),
                               (["-r", "--fiel"], "--file"),
                               (["add", "--destinaton", "audio"], "--destination"),
                               (["--validte=lista.yaml"], "--validate"),
                               (["-v"], "esperado um argumento")):
            with self.subTest(argv=argv), patch("sys.stderr", new_callable=io.StringIO) as output, patch("remessa_musicas.cli.check_tools") as tools:
                with self.assertRaises(SystemExit) as error:
                    main(argv)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(expected, output.getvalue())
                if "quis dizer" in output.getvalue():
                    self.assertIn("\nVocê quis dizer", output.getvalue())
                tools.assert_not_called()

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
                    self.assertEqual(main(["-r", "-f", str(source), "-de", str(root / "audio")]), 1)
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
                self.assertEqual(main(["add", "-f", str(path)]), 0)
            self.assertEqual(run.call_args.args[0]["albums"], ["Álbum 1", "Álbum 2"])

    # Verifica aliases e conflitos nas flags com prefixos compartilhados.
    def test_flags(self):
        parser = build_parser()
        for short, long, field in (("-v", "--validate", "validate"), ("-r", "--resume", "resume")):
            self.assertEqual(getattr(parser.parse_args([short, "test.yaml"]), field), Path("test.yaml"))
            self.assertEqual(getattr(parser.parse_args([long, "test.yaml"]), field), Path("test.yaml"))
        self.assertTrue(parser.parse_args(["-dg"]).diagnose)
        args = parser.parse_args(["-v", "test.yaml", "-de", "audio", "-y"])
        self.assertEqual(args.destination, Path("audio"))
        self.assertTrue(args.yes)
        with patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as error:
                parser.parse_args(["-dg", "-v", "test.yaml"])
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
    # Garante que download e conversão compartilhem o orçamento, mesmo com limites maiores.
    async def test_shared_concurrency_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = manifest_from_rows([("Álbum", str(index), f"https://youtu.be/video{index}") for index in range(4)])
            manifest["_retry_file"] = root / "retomada.json"
            active = peak = 0

            async def fake_process(command, log):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.sleep(0.005)
                    if command[0] == "yt-dlp":
                        Path(command[command.index("-o") + 1].replace("%(ext)s", "webm")).write_bytes(b"audio")
                    else:
                        self.assertEqual(command.count("-threads"), 2)
                        Path(command[-1]).write_bytes(b"mp3")
                finally:
                    active -= 1

            with patch("remessa_musicas.cli.concurrency_budget", return_value=1), patch("remessa_musicas.cli.process", fake_process):
                self.assertTrue(await execute(manifest, root / "audio", False, root / "logs"))
            self.assertEqual(peak, 1)

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
        with patch.object(terminal, "isatty", return_value=True), patch("sys.stderr", terminal), patch.dict("os.environ", {"TERM": "xterm-256color"}):
            async with loading_indicator():
                await asyncio.sleep(0.15)
        self.assertIn("0/0", terminal.getvalue())
        self.assertIn("\033[?25h", terminal.getvalue())
        self.assertTrue(terminal.getvalue().endswith("\r\033[2K"))
        redirected = io.StringIO()
        with patch("sys.stderr", redirected):
            async with loading_indicator():
                await asyncio.sleep(0)
        self.assertEqual(redirected.getvalue(), "")

    # Confere contadores reais, largura responsiva e suporte a terminais sem cores.
    async def test_progress_counters_and_terminal_fallback(self):
        progress = {"states": {"a": "concluido", "b": "falhou", "c": "download", "d": "conversao", "e": "fila"}, "started": 100, "unicode": True}
        with patch("remessa_musicas.cli.time.monotonic", return_value=165), patch.dict("os.environ", {"NO_COLOR": "1"}):
            for width in (30, 55, 80, 120):
                with patch("remessa_musicas.cli.shutil.get_terminal_size", return_value=os.terminal_size((width, 24))):
                    line = loading_line(progress, "⠋")
                self.assertLess(len(line), width)
                self.assertIn("2/5", line)
                self.assertIn("01:05", line)
                self.assertNotIn("\033", line)
            self.assertIn("download 1", line)
            self.assertIn("conversão 1", line)
        terminal = io.StringIO()
        with patch.object(terminal, "isatty", return_value=True), patch("sys.stderr", terminal), patch.dict("os.environ", {"TERM": "dumb"}):
            async with loading_indicator(progress):
                await asyncio.sleep(0)
        self.assertEqual(terminal.getvalue(), "")

    # Confere se a animação é limpa mesmo ao cancelar o processamento.
    async def test_loading_indicator_cancelled(self):
        terminal = io.StringIO()
        with patch.object(terminal, "isatty", return_value=True), patch("sys.stderr", terminal), patch.dict("os.environ", {"TERM": "xterm-256color"}):
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
                    self.assertEqual(await asyncio.to_thread(main, ["-r", "-f"]), 1)
                edited = json.loads(default_queue.read_text())["items"]
                self.assertEqual(len(edited), 1)
                self.assertEqual(edited[0]["url"], "https://youtu.be/replacement")
                self.assertIn("somente URLs HTTPS do YouTube", warnings.getvalue())
                with patch("builtins.input", side_effect=["s", "s", ""]):
                    self.assertEqual(await asyncio.to_thread(main, ["-r", "-f", str(default_queue)]), 0)
                self.assertEqual(json.loads(default_queue.read_text())["items"], [])
                self.assertEqual(await asyncio.to_thread(main, ["-r", "-f", str(default_queue), "-y"]), 0)


if __name__ == "__main__":
    unittest.main()
