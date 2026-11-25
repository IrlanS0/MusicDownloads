import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remessa_musicas.cli import execute, read_manifest


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
