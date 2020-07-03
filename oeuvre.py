#!/usr/bin/env python3
"""
I keep a database of notes on books that I've read and films that I've watched. This
script helps me manage this database by

- allowing me to search the database intelligently.

- assisting with data entry and automatically formatting the entries nicely.

Author:  Ian Fisher (iafisher@protonmail.com)
Version: July 2020
"""
import argparse
import glob
import json
import os
import readline  # noqa: F401
import subprocess
import sys
import textwrap
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple, Union


OEUVRE_DIRECTORY = "/home/iafisher/files/oeuvre"


class Entry:
    """
    A class to represent a database entry.

    Database entries consist of fields, some of them with string values and some of them
    with list values. Most fields can be omitted.
    """

    def __init__(
        self,
        *,
        title: str,
        type: str,
        filename: Optional[str] = None,
        creator: Optional[str] = None,
        year: Optional[int] = None,
        language: Optional[str] = None,
        plot_summary: Optional[str] = None,
        characters: Optional[List["KeywordField"]] = None,
        locations: Optional[List["KeywordField"]] = None,
        topics: Optional[List["KeywordField"]] = None,
        settings: Optional[List["KeywordField"]] = None,
        technical: Optional[List["KeywordField"]] = None,
        external: Optional[List["KeywordField"]] = None,
        quotes: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        self.title = title
        self.type = type
        self.filename = filename
        self.creator = creator
        self.year = year
        self.language = language
        self.plot_summary = plot_summary
        self.characters = characters or []
        self.locations = locations or []
        self.topics = topics or []
        self.settings = settings or []
        self.technical = technical or []
        self.external = external or []
        self.quotes = quotes
        self.notes = notes

    def format_for_display(self, *, verbosity: int) -> str:
        """
        Returns a string representation of the entry for display to the user.
        """
        return self._format(verbosity=verbosity, display=True)

    def format_for_disk(self) -> str:
        """
        Returns the string representation of the entry to be written to disk.
        """
        return self._format(verbosity=VERBOSITY_FULL, display=False)

    def _format(self, *, display: bool, verbosity: int) -> str:
        """
        Core internal method for formatting entries.
        """
        builder = EntryStringBuilder(display=display, verbosity=verbosity)
        builder.field("title", self.title)
        builder.field("creator", self.creator)
        builder.field("type", self.type)
        builder.field("year", str(self.year) if self.year is not None else None)
        builder.field("language", self.language)
        builder.longform_field("plot-summary", self.plot_summary)
        builder.list_field("characters", self.characters, alphabetical=False)
        builder.list_field("locations", self.locations, alphabetical=False)
        builder.list_field("topics", self.topics, alphabetical=True)
        builder.list_field("settings", self.settings, alphabetical=True)
        builder.list_field("technical", self.technical, alphabetical=True)
        builder.list_field("external", self.external, alphabetical=True)
        builder.longform_field("notes", self.notes)
        builder.longform_field("quotes", self.quotes)
        return builder.build()

    def __str__(self) -> str:
        creator_suffix = f" ({self.creator})" if self.creator else ""
        filename_suffix = f" [{self.filename}]" if self.filename else ""
        return self.title + creator_suffix + filename_suffix


class Application:
    """
    A class to represent the oeuvre application.
    """

    def __init__(self, directory: str) -> None:
        """
        Args:
          directory: The path to the directory where the database entries are located.
        """
        self.directory = directory
        try:
            with open(os.path.join(self.directory, "locations.json"), "r") as f:
                self.locdb = json.load(f)
        except FileNotFoundError:
            self.locdb = {}

    def main(self, args: List[str]) -> None:
        """
        Runs the program with the given command-line arguments.
        """
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        parser_edit = subparsers.add_parser("edit")
        parser_edit.add_argument("terms", nargs="*")
        parser_edit.add_argument("--strict-location", action="store_true")
        parser_edit.set_defaults(func=self.main_edit)

        parser_list = subparsers.add_parser("keywords")
        parser_list.add_argument("--sorted", action="store_true")
        parser_list.set_defaults(func=self.main_keywords)

        parser_new = subparsers.add_parser("new")
        parser_new.add_argument("path")
        parser_new.set_defaults(func=self.main_new)

        parser_reformat = subparsers.add_parser("reformat")
        parser_reformat.set_defaults(func=self.main_reformat)

        parser_search = subparsers.add_parser("search")
        parser_search.add_argument("terms", nargs="*")
        parser_search.add_argument("--strict-location", action="store_true")
        parser_search.set_defaults(func=self.main_search)

        parser_show = subparsers.add_parser("show")
        parser_show.add_argument("--brief", action="store_true")
        parser_show.add_argument("terms", nargs="*")
        parser_show.set_defaults(func=self.main_show)

        parsed_args = parser.parse_args(args)
        if hasattr(parsed_args, "func"):
            parsed_args.func(parsed_args)
        else:
            error("no subcommand")

    def main_edit(self, args: argparse.Namespace) -> None:
        """
        Opens the entry for editing and formats it before saving.
        """
        locdb = {} if args.strict_location else self.locdb
        matching = self.read_matching_entries(args.terms, locdb=locdb)
        if not matching:
            error("no matching entries")

        paths = [
            os.path.join(self.directory, e.filename) for e in matching  # type: ignore
        ]
        while True:
            editor = os.environ.get("EDITOR", "nano")
            r = subprocess.run([editor] + paths)
            if r.returncode != 0:
                error(f"editor process exited with error code {r.returncode}")

            success = True
            for old_entry in matching:
                assert isinstance(old_entry.filename, str)
                path = os.path.join(self.directory, old_entry.filename)
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()

                try:
                    entry = parse_entry(text)
                except OeuvreError as e:
                    success = False
                    e.path = path
                    error(str(e), fatal=False)
                    if not confirm("Try again? "):
                        # TODO(2020-07-02): Need to write back old entries.
                        sys.exit(1)
                else:
                    # Call `format_for_disk` before opening the file for writing, so
                    # that if there's an error the file is not wiped out.
                    text = entry.format_for_disk()
                    with open(path, "w", encoding="utf8") as f:
                        f.write(text)
                        f.write("\n")

                    # Only print the entry if only one was opened for editing.
                    if len(matching) == 1:
                        print(text)

            if success:
                break

    def main_keywords(self, args: argparse.Namespace) -> None:
        """
        Lists all keywords from the database.
        """
        counter: defaultdict = defaultdict(int)
        entries = self.read_entries()
        for entry in entries:
            for keyword in entry.topics:
                counter[keyword.keyword] += 1

        # Sort by count and then by name if --sorted flag was present. Otherwise, just
        # by name.
        key = lambda kv: (-kv[1], kv[0]) if args.sorted else kv[0]
        for keyword, count in sorted(counter.items(), key=key):
            print(f"{keyword} ({count})")

    def main_new(self, args: argparse.Namespace) -> None:
        """
        Creates a new entry.
        """
        path = os.path.join(self.directory, args.path)
        if os.path.exists(path):
            error(f"{path} already exists.")

        blank_entry = Entry(title="", type="")
        text = blank_entry.format_for_disk()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")

        while True:
            editor = os.environ.get("EDITOR", "nano")
            r = subprocess.run([editor, path])
            if r.returncode != 0:
                error(f"editor process exited with error code {r.returncode}")

            with open(path, "r", encoding="utf8") as f:
                text = f.read()

            try:
                entry = parse_entry(text)
            except OeuvreError as e:
                e.path = path
                error(str(e), fatal=False)
                if not confirm("Try again? "):
                    os.remove(path)
                    sys.exit(1)

                continue
            else:
                # Call `format_for_disk` before opening the file for writing, so
                # that if there's an error the file is not wiped out.
                text = entry.format_for_disk()
                with open(path, "w", encoding="utf8") as f:
                    f.write(text)
                    f.write("\n")

                print(text)

            break

    def main_reformat(self, args: argparse.Namespace) -> None:
        """
        Reformats all database entries.
        """
        if not confirm("Are you sure you want to reformat every entry? "):
            sys.exit(1)

        for entry in self.read_entries():
            if not entry.filename:
                continue

            path = os.path.join(self.directory, entry.filename)
            text = entry.format_for_disk()
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
                f.write("\n")

    def main_search(self, args: argparse.Namespace) -> None:
        """
        Searches all database entries and prints the matching ones.
        """
        locdb = {} if args.strict_location else self.locdb
        matching = self.read_matching_entries(args.terms, locdb=locdb)
        for entry in sorted(matching, key=alphabetical_key):
            print(str(entry))

    def main_show(self, args: argparse.Namespace) -> None:
        """
        Prints the full entry that matches the search terms.
        """
        matching = self.read_matching_entries(args.terms, locdb=self.locdb)
        if len(matching) == 0:
            print("No matching entries.")
        elif len(matching) > 1:
            print("Multiple matching entries:")
            for entry in sorted(matching, key=alphabetical_key):
                print("  " + str(entry))
        else:
            verbosity = VERBOSITY_BRIEF if args.brief else VERBOSITY_FULL
            print(matching[0].format_for_display(verbosity=verbosity))

    def read_matching_entries(
        self, search_terms: List[str], *, locdb: Dict[str, List[str]]
    ) -> List[Entry]:
        """
        Returns a list of all entries in the database that match the search terms.
        """
        entries = self.read_entries()
        return [
            entry
            for entry in entries
            if match(entry, search_terms, partial=True, locdb=locdb)
        ]

    def read_entries(self) -> List[Entry]:
        """
        Returns a list of all entries in the database.
        """
        entries = []
        for path in sorted(glob.glob(self.directory + "/**/*.txt", recursive=True)):
            if path.startswith(self.directory + "/editing/"):
                continue

            with open(path, "r", encoding="utf8") as f:
                text = f.read()

            try:
                entry = parse_entry(text)
            except OeuvreError as e:
                e.path = path
                error(str(e))

            entry.filename = path[len(self.directory) + 1 :]
            entries.append(entry)

        return entries


def match(
    entry: Entry, search_terms: List[str], *, partial: bool, locdb: Dict[str, List[str]]
) -> bool:
    """
    Returns True if the entry matches the search terms.

    Search terms are joined by an implicit AND operator.

    If `partial` is True, then the search term can match partially, e.g. `war` can match
    `civil-war`.
    """
    return all(
        match_one(entry, search_term, partial=partial, locdb=locdb)
        for search_term in search_terms
    )


def match_one(
    entry: Entry, search_term: str, *, partial: bool, locdb: Dict[str, List[str]]
) -> bool:
    """
    Returns True if the entry matches the single search term.

    See `match` for meaning of `partial` argument.
    """
    search_field, term = split_term(search_term)

    if partial:
        pred = lambda v: term.lower() in v.lower()
    else:
        pred = lambda v: term.lower() == v.lower()

    if search_field:
        fields_to_match = [search_field]
    else:
        fields_to_match = [
            "filename",
            "title",
            "creator",
            "characters",
            "locations",
            "topics",
            "settings",
            "technical",
            "external",
        ]

    for field in fields_to_match:
        field_value = getattr(entry, field, None)
        if not field_value:
            continue

        if search_field == "locations":
            if match_location(entry.locations, term, locdb):  # type: ignore
                return True
        elif isinstance(field_value, list):
            if any(pred(v.keyword) for v in field_value):
                return True
        else:
            assert isinstance(field_value, str)
            if pred(field_value):
                return True

    return False


def match_location(
    locations: List["KeywordField"], search_term: str, locdb: Dict[str, List[str]]
) -> bool:
    """
    Returns True if any of the locations match the search term.
    """
    for location in locations:
        if location.keyword == search_term:
            return True

        enclosing = get_enclosing_locations(locdb, location.keyword)
        if search_term in enclosing:
            return True

    return False


def get_enclosing_locations(locdb: Dict[str, List[str]], location: str) -> List[str]:
    """
    Returns all locations that include the given location in the database.
    """
    if location in locdb:
        direct_enclosing = locdb[location]
        indirect_enclosing = []
        for enclosing in direct_enclosing:
            indirect_enclosing.extend(get_enclosing_locations(locdb, enclosing))
        return direct_enclosing + indirect_enclosing
    else:
        return []


def split_term(term: str) -> Tuple[str, str]:
    """
    Splits the term into a field name (which may be empty) and a bare term.
    """
    if ":" in term:
        field, term = term.split(":", maxsplit=1)
        return (field, term)
    else:
        return ("", term)


class KeywordField:
    """
    A field with a keyword value, which includes the keyword itself and an optional
    description.
    """

    def __init__(self, keyword: str, description: Optional[str]) -> None:
        self.keyword = keyword
        self.description = description

    @classmethod
    def from_string(cls, s: str) -> "KeywordField":
        if ":" in s:
            keyword, description = s.split(":", maxsplit=1)
            keyword = keyword.rstrip()
            description = description.lstrip()
        else:
            keyword = s
            description = ""

        return cls(keyword, description)

    def __bool__(self) -> bool:
        return bool(self.keyword or self.description)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.keyword == other

        if not isinstance(other, KeywordField):
            return False

        return self.keyword == other.keyword and self.description == other.description

    def __repr__(self) -> str:
        return f"KeywordField({self.keyword!r}, {self.description!r})"

    def __str__(self) -> str:
        if self.description:
            return f"{self.keyword}: {self.description}"
        else:
            return self.keyword


MAXIMUM_LENGTH = 80
INDENT = "  "
VERBOSITY_BRIEF = 0
VERBOSITY_FULL = 1


class EntryStringBuilder:
    """
    A class to build a string representation of an Entry object.
    """

    def __init__(self, *, display: bool, verbosity: int) -> None:
        """
        Args:
          display: Whether the field is for display to the user.
          verbosity: The desired level of verbosity in the output.
        """
        self.display = display
        self.verbosity = verbosity
        self.lines: List[str] = []

    def field(self, field: str, value: Optional[str]) -> None:
        """
        Adds a regular, single-line field.
        """
        if value:
            self.lines.append(f"{field}: {value}")
        elif not self.display:
            self.lines.append(f"{field}:")

    def longform_field(self, field: str, value: Optional[str]) -> None:
        """
        Adds a longform field.
        """
        if not value:
            if not self.display:
                self.lines.append(f"{field}:")
                self.lines.append("")
            return

        if self.verbosity == VERBOSITY_BRIEF:
            self.lines.append(f"{field}: <hidden>")
            return

        self.lines.append(f"{field}:")
        for i, paragraph in enumerate(value.splitlines()):
            if i != 0:
                self.lines.append("")

            if self.display:
                self.lines.append(
                    textwrap.fill(
                        paragraph,
                        width=MAXIMUM_LENGTH,
                        initial_indent=INDENT,
                        subsequent_indent=INDENT,
                    )
                )
            else:
                self.lines.append(INDENT + paragraph)

        self.lines.append("")

    def list_field(
        self, field: str, values: List["KeywordField"], alphabetical: bool
    ) -> None:
        """
        Adds a list field.
        """
        if not values:
            if not self.display:
                self.lines.append(f"{field}:")
                self.lines.append("")
            return

        stringvalues: Iterable[str] = map(str, values)
        if alphabetical:
            stringvalues = sorted(stringvalues)

        self.lines.append(f"{field}:")
        for value in stringvalues:
            if self.display:
                self.lines.append(
                    textwrap.fill(
                        value,
                        width=MAXIMUM_LENGTH,
                        initial_indent=INDENT,
                        subsequent_indent=(INDENT * 2),
                    )
                )
            else:
                self.lines.append(INDENT + value)

        self.lines.append("")

    def build(self) -> str:
        """
        Builds the accumulated fields into a string.
        """
        return "\n".join(self.lines).strip("\n")


def parse_entry(text: str) -> Entry:
    """
    Reads a database entry from a string.

    Raises an `OeuvreError` if the entry is incorrectly formatted.
    """
    fields: Dict[str, Union[str, int, List["KeywordField"]]] = {}
    lines = list(enumerate(text.splitlines(), start=1))
    lines.reverse()

    while lines:
        lineno, line = lines[-1]
        line = line.strip()
        if not line:
            lines.pop()
            continue

        if ":" not in line:
            raise OeuvreError("expected field definition", lineno=lineno)

        field, value = line.split(":", maxsplit=1)
        field = field.strip().replace("-", "_")
        value = value.strip()

        if field in ("plot_summary", "quotes", "notes"):
            if value:
                raise OeuvreError("trailing content", lineno=lineno)

            lines.pop()
            fields[field] = parse_longform_field(lines)
        elif field in (
            "characters",
            "locations",
            "topics",
            "settings",
            "technical",
            "external",
        ):
            if value:
                raise OeuvreError("trailing content", lineno=lineno)

            lines.pop()
            fields[field] = parse_list_field(lines)
        elif field in ("title", "type", "creator", "language", "year"):
            lines.pop()
            fields[field] = validate_field(field, value, lineno=lineno)
        else:
            raise OeuvreError(f"unknown field {field!r}", lineno=lineno)

    return Entry(**fields)  # type: ignore


def parse_longform_field(lines: List[Tuple[int, str]]) -> str:
    """
    Parses the value of a longform field.

    `lines` should be a list of (line number, line) pairs in reverse order. This
    function will remove all lines from the end of `lines` that it uses.
    """
    paragraphs = []
    while lines:
        lineno, line = lines[-1]

        if not line:
            lines.pop()
            continue

        if not line.startswith(INDENT):
            break

        lines.pop()
        line = line.strip()
        paragraphs.append(line)

    return "\n".join(paragraphs)


def parse_list_field(lines: List[Tuple[int, str]]) -> List["KeywordField"]:
    """
    Parses the value of a list field.

    `lines` should be a list of (line number, line) pairs in reverse order. This
    function will remove all lines from the end of `lines` that it uses.
    """
    values = []
    while lines:
        lineno, line = lines[-1]

        if not line or not line.startswith(INDENT):
            break

        description: Optional[str]
        if ":" in line:
            keyword, description = line.split(":", maxsplit=1)
            keyword = keyword.strip()
            description = description.strip()
        else:
            keyword = line.strip()
            description = None

        lines.pop()
        values.append(KeywordField(keyword, description))

    return values


REQUIRED_FIELDS = {"title", "type"}
TYPE_CHOICES = {"book", "film", "television", "play", "story"}


def validate_field(field: str, value: str, *, lineno: int) -> Union[str, int]:
    """
    Raises an OeuvreError if the field's value is not valid.

    Returns the value of the field, possibly transformed (e.g., converted from a string
    to an integer).
    """
    if field in REQUIRED_FIELDS and not value:
        raise OeuvreError(f"{field!r} field is required", lineno=lineno)

    if field == "type" and value not in TYPE_CHOICES:
        raise OeuvreError(
            f"'type' must be one of: {', '.join(TYPE_CHOICES)}", lineno=lineno
        )

    if field == "year" and value:
        if not value.isdigit():
            raise OeuvreError("'year' must be an integer", lineno=lineno)

        return int(value)

    return value


def alphabetical_key(entry: Entry) -> str:
    """
    Key for sort functions to sort entries alphabetically.
    """
    name = str(entry)
    if name.startswith("The "):
        return name[4:]
    elif name.startswith(("Le ", "La ")):
        return name[3:]
    else:
        return name


def confirm(prompt: str) -> bool:
    """
    Prompts the user for confirmation and returns whether they accepted or not.
    """
    while True:
        try:
            yesno = input(prompt)
        except EOFError:
            print()
            return False
        except KeyboardInterrupt:
            print()
            sys.exit(1)

        yesno = yesno.strip().lower()
        if yesno.startswith("y"):
            return True
        elif yesno.startswith("n"):
            return False


def error(message: str, *, fatal: bool = True) -> None:
    print(f"error: {message}", file=sys.stderr)
    if fatal:
        sys.exit(1)


def warning(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


class OeuvreError(Exception):
    def __init__(
        self, *args, lineno: Optional[int] = None, path: Optional[str] = None, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.lineno = lineno
        self.path = path

    def __str__(self):
        if self.path is not None:
            if self.lineno is not None:
                location_suffix = f" ({self.path}, line {self.lineno})"
            else:
                location_suffix = f" ({self.path})"
        else:
            location_suffix = ""

        return super().__str__() + location_suffix


if __name__ == "__main__":
    app = Application(OEUVRE_DIRECTORY)
    app.main(sys.argv[1:])
