import os
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from oeuvre import Application


class OeuvreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        d = os.path.join(cls._directory.name, "test_database")
        shutil.copytree("test_database", d)
        cls.app = Application(d)

    @patch("sys.stdout", new_callable=StringIO)
    def test_show_command(self, stdout):
        self.app.main(["show", "libra.txt"])
        with open("test_database/libra.txt", "r") as f:
            contents = f.read()
        self.assertEqual(stdout.getvalue(), contents)

    @patch("sys.stdout", new_callable=StringIO)
    def test_show_command_with_brief_flag(self, stdout):
        self.app.main(["show", "--brief", "libra.txt"])
        self.assertEqual(stdout.getvalue(), LIBRA_BRIEF)

    @patch("sys.stdout", new_callable=StringIO)
    def test_search_command_with_bare_keyword(self, stdout):
        self.app.main(["search", "DeLillo"])
        self.assertEqual(stdout.getvalue(), "Libra (Don DeLillo) [libra.txt]\n")

    @patch("sys.stdout", new_callable=StringIO)
    def test_search_command_with_scoped_keyword(self, stdout):
        self.app.main(["search", "type:book"])
        self.assertEqual(
            stdout.getvalue(),
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n"
            + "Libra (Don DeLillo) [libra.txt]\n",
        )

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()


LIBRA_BRIEF = """\
title: Libra
creator: Don DeLillo
type: book
year: 1988
language: English
plot-summary: <hidden>
locations:
  Dallas
  New Orleans
  Tokyo
  Moscow

topics:
  conspiracy
  espionage
  military

technical:
  non-linear

external:
  postmodernist

last-updated: Sat 30 May 2020 08:44 AM PDT
"""


if __name__ == "__main__":
    unittest.main()
