import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remessa_musicas.cli import build_parser, execute, loading_indicator, main, read_manifest


class CommandTests(unittest.TestCase):
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
    def test_rejects_path_traversal_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remessa.yaml"
            path.write_text('pasta: "../fora"\nmusicas:\n  - nome: Teste\n    url: https://youtu.be/example\n')
            with self.assertRaises(ValueError):
                read_manifest(path)
            path.write_text('pasta: Dentro\nmusicas:\n  - nome: Teste\n    url: https://youtu.be/one\n  - nome: teste\n    url: https://youtu.be/two\n')
            with self.assertRaises(ValueError):
                read_manifest(path)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
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
            songs = [{"name": name, "url": f"https://youtu.be/{name}", "key": name} for name in ("um", "dois")]
            manifest = {"songs": songs, "config": {"downloads": 5, "conversions": 2}}
            called = []

            async def fake_run(song, config, destination, dl_limit, cv_limit):
                called.append(song["name"])
                await asyncio.sleep(0.01 if song["name"] == "um" else 0)
                (destination / (song["name"] + ".mp3")).write_bytes(b"audio")
                return {"status": "concluido", "file": song["name"] + ".mp3"}

            with patch("remessa_musicas.cli.run_song", fake_run):
                self.assertTrue(await execute(manifest, dest, False))
                self.assertTrue(await execute(manifest, dest, True))
            self.assertEqual(called, ["um", "dois"])
            self.assertTrue((dest / "resultado.json").is_file())


if __name__ == "__main__":
    unittest.main()
