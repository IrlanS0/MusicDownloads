import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remessa_musicas.cli import build_parser, execute, loading_indicator, main, music_directory, prune_sessions, read_manifest, read_song_list, run_song


class CommandTests(unittest.TestCase):
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
            manifest = {"songs": songs, "config": {"downloads": 5, "conversions": 2}}
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


if __name__ == "__main__":
    unittest.main()
