import os
import re
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
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        d = os.path.join(self._directory.name, "test_database")
        shutil.copytree("test_database", d)
        self.app = Application(d)
        # Guard against different test cases interfering with one another by resetting
        # the editor before each test case.
        os.environ["EDITOR"] = "does not exist"

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

    # See the long comment below this test class for an explanation on how the new and
    # edit commands are tested.

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_new_command(self, stdout):
        os.environ["EDITOR"] = "python3 oeuvre_test.py --fake-editor test_new_command"
        self.app.main(["--no-color", "new", "test_new_command_entry.txt"])
        self.app.main(["--no-color", "show", "test_new_command_entry.txt"])
        self.assertEqual(
            stdout.getvalue(),
            # The entry is printed twice: once by the new command and once by the show
            # command. We check both to make sure the entry has been successfully
            # persisted to disk.
            "title: Blood Meridian\ncreator: Cormac McCarthy\ntype: book\n"
            + "title: Blood Meridian\ncreator: Cormac McCarthy\ntype: book\n",
        )

    @patch("sys.stdout", new_callable=FakeStdout)
    def test_edit_command(self, stdout):
        os.environ["EDITOR"] = "python3 oeuvre_test.py --fake-editor test_edit_command"
        self.app.main(["--no-color", "edit", "libra.txt"])
        self.app.main(["--no-color", "show", "libra.txt"])
        self.assertEqual(
            stdout.getvalue(),
            # The entry is printed twice: once by the edit command and once by the show
            # command. We check both to make sure the entry has been successfully
            # persisted to disk.
            LIBRA_EDITED + LIBRA_EDITED,
        )

    # TODO(#24): Test adding a new keyword.
    # TODO(#24): Test editing multiple files.
    # TODO(#24): Test invalid edit (e.g., wrong value for 'type' field).

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

    def tearDown(self):
        self._directory.cleanup()


# Testing the new and edit subcommands is tricky because they normally involve opening
# a text editor for the user to edit one or more entries. It would be difficult to
# programmatically interact with a text editor, so instead the test suite patches in a
# custom editor (via the EDITOR environment variable) which is really just a shell
# script that edits the entry without user interaction.
#
# To keep all of the testing code in one place, the shell script that is used as the
# editor is actually this very file! When invoked with the --fake-editor flag, this
# Python file acts as a fake editor rather than a test suite. It calls the `fake_editor`
# function below with whatever test case is being run and all the paths to be edited.
# `fake_editor` makes different changes depending on which test case is being run.


def fake_editor(test_case, paths):
    if test_case == "test_new_command":
        path = paths[0]
        with open(path, "r", encoding="utf-8") as f:
            contents = f.read()

        contents = set_field(contents, "title", "Blood Meridian")
        contents = set_field(contents, "creator", "Cormac McCarthy")
        contents = set_field(contents, "type", "book")

        with open(path, "w", encoding="utf-8") as f:
            f.write(contents)
    elif test_case == "test_edit_command":
        path = paths[0]
        with open(path, "r", encoding="utf-8") as f:
            contents = f.read()

        contents = set_field(contents, "creator", "Thomas Pynchon", overwrite=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(contents)
    else:
        # Note that this exception will never be seen in the test suite because the code
        # runs in a subcommand.
        raise Exception(f"unknown test case for fake editor: {test_case}")


def set_field(contents, field, value, *, overwrite=False):
    if overwrite:
        pattern = re.compile("^" + re.escape(field) + r":.*$", re.MULTILINE)
    else:
        pattern = re.compile("^" + re.escape(field) + r":\s*$", re.MULTILINE)

    new_contents = pattern.sub(field + ": " + value, contents, count=1)
    if new_contents == contents:
        raise Exception(f"unable to set field {field!r}")

    return new_contents


class FakeEditorTests(unittest.TestCase):
    """
    Small test suite for the functions used by the fake editor in tests.
    """

    def test_set_field(self):
        old_contents = "title:\ncreator:\nyear:\n"
        new_contents = set_field(old_contents, "title", "Lorem Ipsum")
        self.assertEqual(new_contents, "title: Lorem Ipsum\ncreator:\nyear:\n")

    def test_set_field_with_overwrite(self):
        old_contents = "title: Bigfoot\ncreator:\nyear:\n"
        new_contents = set_field(old_contents, "title", "Sasquatch", overwrite=True)
        self.assertEqual(new_contents, "title: Sasquatch\ncreator:\nyear:\n")

    def test_set_field_with_no_overwrite(self):
        old_contents = "title: Bigfoot\ncreator:\nyear:\n"
        with self.assertRaises(Exception):
            set_field(old_contents, "title", "Sasquatch", overwrite=False)


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

LIBRA_TEMPLATE = """\
title: Libra
creator: {}
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
LIBRA_FULL = LIBRA_TEMPLATE.format("Don DeLillo")
LIBRA_EDITED = LIBRA_TEMPLATE.format("Thomas Pynchon")


if __name__ == "__main__":
    if "--fake-editor" in sys.argv:
        test_case = sys.argv[2]
        paths = sys.argv[3:]
        fake_editor(test_case, paths)
    else:
        unittest.main()
