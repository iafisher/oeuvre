import os
import re
import shutil
import sys
import tempfile
import unittest
from io import StringIO

from oeuvre import Application, KeywordField, parse_list_field, parse_longform_field


class OeuvreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        d = os.path.join(self._directory.name, "test_database")
        shutil.copytree("test_database", d)

        # Guard against different test cases interfering with one another by resetting
        # the editor before each test case.
        os.environ["EDITOR"] = "/dev/null"

        self.app = Application(d, stdout=None, stderr=None, stdin=None, editor=None)
        self.reset_io()

    def test_show_command(self):
        self.app.main(["show", "libra.txt"])
        self.assertOutput(LIBRA_FULL)

    def test_show_command_with_brief_flag(self):
        self.app.main(["show", "--brief", "libra.txt"])
        self.assertOutput(LIBRA_BRIEF)

    def test_search_command_with_bare_keyword(self):
        self.app.main(["--no-color", "search", "DeLillo", "--detailed"])
        self.assertOutput(
            "Libra (Don DeLillo) [libra.txt]\n"
            + "  creator: matched text (Don DeLillo)\n"
        )

    def test_search_command_with_scoped_keyword(self):
        self.app.main(["--no-color", "search", "type:book", "--detailed"])
        self.assertOutput(
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n"
            + "  type: matched text (book)\n"
            + "Libra (Don DeLillo) [libra.txt]\n"
            + "  type: matched text (book)\n"
        )

    def test_search_command_on_year_field(self):
        # Regression test for issue #19
        self.app.main(["--no-color", "search", "year:1988"])
        self.assertOutput("Libra (Don DeLillo) [libra.txt]\n")

    def test_search_command_with_multiple_terms(self):
        # Regression test for issue #21
        self.app.main(["--no-color", "search", "year:1988", "type:book"])
        self.assertOutput("Libra (Don DeLillo) [libra.txt]\n")

    def test_search_command_with_location(self):
        # Regression test for issue #22
        # Note that Crime and Punishment has St. Petersburg as its location, not
        # Russia, so this tests the use of the location database to look up
        # locations.
        self.app.main(["--no-color", "search", "locations:russia"])
        self.assertOutput(
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n"
        )

    def test_search_command_with_unknown_field(self):
        # Regression test for issue #23
        with self.assertRaises(SystemExit):
            self.app.main(["--no-color", "search", "lol:whatever"])

        self.assertOutput("error: unknown field 'lol'\n", stderr=True)

    def test_search_command_with_partial_word_match(self):
        # Regression test for issue #4
        self.app.main(["--no-color", "search", "kw:modernist"])
        self.assertOutput("")

    # See the long comment below this test class for an explanation on how the new and
    # edit commands are tested.

    def test_new_command(self):
        editor = FakeEditor()
        editor.set_field("title", "Blood Meridian")
        editor.set_field("creator", "Cormac McCarthy")
        editor.set_field("type", "book")
        self.app.editor = editor

        self.app.main(["--no-color", "new", "test_new_command_entry.txt"])
        self.assertOutput(
            "title: Blood Meridian\ncreator: Cormac McCarthy\ntype: book\n"
        )

        # Check that the entry has been successfully persisted to disk.
        self.reset_io()
        self.app.main(["--no-color", "show", "test_new_command_entry.txt"])
        self.assertOutput(
            "title: Blood Meridian\ncreator: Cormac McCarthy\ntype: book\n"
        )

    def test_new_command_without_txt_extension(self):
        # Regression test for issue #25
        with self.assertRaises(SystemExit):
            self.app.main(["--no-color", "new", "no-extension"])

        self.assertOutput("error: entry name must end in .txt\n", stderr=True)

    def test_edit_command(self):
        editor = FakeEditor()
        editor.set_field("creator", "Thomas Pynchon", overwrite=True)
        self.app.editor = editor

        self.app.main(["--no-color", "edit", "libra.txt"])
        self.assertOutput(LIBRA_EDITED)

        self.reset_io()
        self.app.main(["--no-color", "show", "libra.txt"])
        self.assertOutput(LIBRA_EDITED)

    def test_new_command_adding_new_keyword(self):
        editor = FakeEditor()
        editor.set_field("title", "The Maltese Falcon")
        editor.set_field("type", "film")
        editor.add_to_list_field("keywords", "film-noir")
        self.app.editor = editor
        self.app.stdin = StringIO("yes\n")

        self.app.main(["--no-color", "new", "test_new_command_adding_new_keyword.txt"])
        self.assertOutput(
            "new keywords for test_new_command_adding_new_keyword.txt: "
            + "film-noir\nKeep? "
            + "title: The Maltese Falcon\n"
            + "type: film\n"
            + "keywords:\n"
            + "  film-noir\n"
        )

        self.reset_io()
        self.app.main(["--no-color", "show", "test_new_command_adding_new_keyword.txt"])
        self.assertOutput(
            "title: The Maltese Falcon\n"
            + "type: film\n"
            + "keywords:\n"
            + "  film-noir\n"
        )

    def test_edit_command_with_multiple_files(self):
        # Make sure the entries don't already have the keyword we are going to add.
        self.app.main(["--no-color", "search", "keywords:edited"])
        self.assertOutput("")

        self.reset_io()
        editor = FakeEditor()
        editor.add_to_list_field("keywords", "edited")
        self.app.editor = editor
        # Accept confirmation for adding new keywords.
        self.app.stdin = StringIO("yes\nyes\n")

        self.app.main(["--no-color", "edit", "type:book"])
        self.assertOutput(
            "new keywords for crime-and-punishment.txt: edited\nKeep? "
            + "new keywords for libra.txt: edited\nKeep? "
        )

        self.reset_io()
        self.app.main(["--no-color", "search", "keywords:edited"])
        self.assertOutput(
            "Crime and Punishment (Fyodor Dostoyevsky) [crime-and-punishment.txt]\n"
            + "Libra (Don DeLillo) [libra.txt]\n"
        )

    def test_edit_command_with_invalid_edit(self):
        editor = FakeEditor()
        editor.set_field("type", "whatever", overwrite=True)
        self.app.editor = editor
        self.app.stdin = StringIO("no\n")

        self.app.main(["--no-color", "edit", "libra.txt"])
        self.assertEqual(
            self.app.stderr.getvalue(),
            "error: 'type' must be one of: book, film, play, story, television"
            + " (libra.txt, line 3)\n",
        )
        self.assertEqual(self.app.stdout.getvalue(), "Try again? ")

        # Make sure the edit was not saved.
        self.reset_io()
        self.app.main(["--no-color", "show", "libra.txt"])
        self.assertIn("type: book", self.app.stdout.getvalue())
        self.assertNotIn("type: whatever", self.app.stdout.getvalue())

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

    def assertOutput(self, expected, *, stderr=False):
        if stderr:
            stream = self.app.stderr
            other_stream = self.app.stdout
        else:
            stream = self.app.stdout
            other_stream = self.app.stderr

        self.assertEqual(stream.getvalue(), expected)
        self.assertEqual(other_stream.getvalue(), "")

    def reset_io(self):
        self.app.stdin = None
        self.app.stdout = FakeStdout()
        self.app.stderr = FakeStderr()
        self.app.editor = None

    def tearDown(self):
        self._directory.cleanup()


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


class FakeEditor:
    def __init__(self):
        self.stored_edits = []

    def set_field(self, *args, **kwargs):
        self.stored_edits.append((self._set_field, (args, kwargs)))

    def add_to_list_field(self, *args, **kwargs):
        self.stored_edits.append((self._add_to_list_field, (args, kwargs)))

    def __call__(self, paths):
        for path in paths:
            contents = self._read_file(path)
            for edit_function, (args, kwargs) in self.stored_edits:
                contents = edit_function(contents, *args, **kwargs)
            self._write_file(path, contents)

    @staticmethod
    def _set_field(contents, field, value, *, overwrite=False):
        if overwrite:
            pattern = re.compile("^" + re.escape(field) + r":.*$", re.MULTILINE)
        else:
            pattern = re.compile("^" + re.escape(field) + r":\s*$", re.MULTILINE)

        new_contents = pattern.sub(field + ": " + value, contents, count=1)
        if new_contents == contents:
            raise Exception(f"unable to set field {field!r}")

        return new_contents

    @staticmethod
    def _add_to_list_field(contents, field, value):
        pattern = re.compile("^" + re.escape(field) + r":\s*$", re.MULTILINE)
        new_contents = pattern.sub(field + ":\n  " + value, contents, count=1)
        if new_contents == contents:
            raise Exception(f"unable to add to list field {field!r}")

        return new_contents

    @staticmethod
    def _read_file(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _write_file(path, contents):
        with open(path, "w", encoding="utf-8") as f:
            f.write(contents)


class FakeEditorTests(unittest.TestCase):
    def test_set_field(self):
        old_contents = "title:\ncreator:\nyear:\n"
        new_contents = FakeEditor._set_field(old_contents, "title", "Lorem Ipsum")
        self.assertEqual(new_contents, "title: Lorem Ipsum\ncreator:\nyear:\n")

    def test_set_field_with_overwrite(self):
        old_contents = "title: Bigfoot\ncreator:\nyear:\n"
        new_contents = FakeEditor._set_field(
            old_contents, "title", "Sasquatch", overwrite=True
        )
        self.assertEqual(new_contents, "title: Sasquatch\ncreator:\nyear:\n")

    def test_set_field_with_no_overwrite(self):
        old_contents = "title: Bigfoot\ncreator:\nyear:\n"
        with self.assertRaises(Exception):
            FakeEditor._set_field(old_contents, "title", "Sasquatch", overwrite=False)

    def test_add_to_list_field(self):
        old_contents = "title:\nkeywords:\nnotes:\n"
        new_contents = FakeEditor._add_to_list_field(
            old_contents, "keywords", "whatever"
        )
        self.assertEqual(new_contents, "title:\nkeywords:\n  whatever\nnotes:\n")

    def test_add_to_list_field_with_missing_field(self):
        old_contents = "title:\nkeywords:\nnotes:\n"
        with self.assertRaises(Exception):
            FakeEditor._add_to_list_field(old_contents, "settings", "whatever")


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
    unittest.main()
