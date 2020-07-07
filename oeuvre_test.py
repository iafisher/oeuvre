import os
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from oeuvre import Application, KeywordField, parse_list_field, parse_longform_field


class FakeStdout(StringIO):
    # Make sure we are using the real stdout and not the one that we patched.
    original_stdout = sys.stdout

    def fileno(self):
        # oeuvre calls sys.stdout.fileno() to check if standard output is a terminal or
        # not (and thus whether it should use colored output), so we have to define this
        # method on the StringIO class we are using to patch sys.stdout.
        return self.original_stdout.fileno()


class FakeStderr(StringIO):
    original_stderr = sys.stderr

    def fileno(self):
        return self.original_stderr.fileno()


class OeuvreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        d = os.path.join(cls._directory.name, "test_database")
        shutil.copytree("test_database", d)
        cls.app = Application(d)

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_show_command(self, stdout):
        self.app.main(["show", "libra.txt"])
        self.assertEqual(stdout.getvalue(), LIBRA_FULL)

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_show_command_with_brief_flag(self, stdout):
        self.app.main(["show", "--brief", "libra.txt"])
        self.assertEqual(stdout.getvalue(), LIBRA_BRIEF)

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_with_bare_keyword(self, stdout):
        self.app.main(["--no-color", "search", "DeLillo", "--detailed"])
        self.assertEqual(
            stdout.getvalue(),
            "Libra (Don DeLillo) [libra.txt]\n"
            + "  creator: matched text (Don DeLillo)\n",
        )

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_with_scoped_keyword(self, stdout):
        self.app.main(["--no-color", "search", "type:book", "--detailed"])
        self.assertEqual(
            stdout.getvalue(),
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n"
            + "  type: matched text (book)\n"
            + "Libra (Don DeLillo) [libra.txt]\n"
            + "  type: matched text (book)\n",
        )

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_on_year_field(self, stdout):
        # Regression test for issue #19
        self.app.main(["--no-color", "search", "year:1988"])
        self.assertEqual(stdout.getvalue(), "Libra (Don DeLillo) [libra.txt]\n")

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_with_multiple_terms(self, stdout):
        # Regression test for issue #21
        self.app.main(["--no-color", "search", "year:1988", "type:book"])
        self.assertEqual(stdout.getvalue(), "Libra (Don DeLillo) [libra.txt]\n")

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_with_location(self, stdout):
        # Regression test for issue #22
        # Note that Crime and Punishment has St. Petersburg as its location, not Russia,
        # so this tests the use of the location database to look up locations.
        self.app.main(["--no-color", "search", "locations:russia"])
        self.assertEqual(
            stdout.getvalue(),
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n",
        )

    @patch("sys.stderr", new_callable=FakeStderr)
    def test_search_command_with_unknown_field(self, stderr):
        # Regression test for issue #23
        with self.assertRaises(SystemExit):
            self.app.main(["--no-color", "search", "lol:whatever"])

        self.assertEqual(stderr.getvalue(), "error: unknown field 'lol'\n")

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_search_command_with_partial_word_match(self, stdout):
        # Regression test for issue #4
        self.app.main(["--no-color", "search", "kw:modernist"])
        self.assertEqual(stdout.getvalue(), "")

    def test_parse_longform_field(self):
        text = "  Paragraph one\n\n  Paragraph two\n\nfoo: bar"
        lines = list(enumerate(text.splitlines(), start=1))
        lines.reverse()

        value = parse_longform_field(lines)

        self.assertEqual(value, "Paragraph one\nParagraph two")
        self.assertEqual(lines, [(5, "foo: bar")])

    def test_parse_list_field(self):
        text = "  apples\n  oranges: description\n\nfoo: bar"
        lines = list(enumerate(text.splitlines(), start=1))
        lines.reverse()

        value = parse_list_field(lines)

        self.assertEqual(
            value,
            [KeywordField("apples", None), KeywordField("oranges", "description")],
        )
        self.assertEqual(lines, [(4, "foo: bar"), (3, "")])

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
  dallas
  new-orleans
  tokyo
  moscow

keywords:
  conspiracy
  espionage
  military
  non-linear
  postmodernist
"""

LIBRA_FULL = """\
title: Libra
creator: Don DeLillo
type: book
year: 1988
language: English
plot-summary:
  In the aftermath of the failed Bay of Pigs invasion, a group of agents at the
  CIA hatch a plot to attempt an assassination of President Kennedy and blame it
  on the Cuban government. Several different factions are involved in the
  conspiracy and working more or less independently. One faction recruits Cuban
  exiles, while another settles on Lee Harvey Oswald, a former Marine who
  defected to the Soviet Union for several years before returning to Texas. At
  some point, it is decided to actually kill Kennedy rather than missing.

  In the event, Oswald and the Cubans both hit President Kennedy. Oswald is
  arrested and is himself murdered several days later by Jack Ruby, who was
  manipulated into doing it by members of the conspiracy. The chapters of the
  book alternate between Oswald's and various conspirator's perspectives.

locations:
  dallas
  new-orleans
  tokyo
  moscow

keywords:
  conspiracy
  espionage
  military
  non-linear
  postmodernist
"""


if __name__ == "__main__":
    unittest.main()
