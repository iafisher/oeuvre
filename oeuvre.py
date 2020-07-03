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
from collections import defaultdict, OrderedDict
from typing import Dict, IO, Iterator, List, Optional, Tuple, Union


OEUVRE_DIRECTORY = "/home/iafisher/files/oeuvre"


# Type definitions
Field = Union[List[str], List["KeywordField"], str]
Entry = Dict[str, Field]


class Application:
    def __init__(self, directory: str) -> None:
        self.directory = directory
        try:
            with open(os.path.join(self.directory, "locations.json"), "r") as f:
                self.locdb = json.load(f)
        except FileNotFoundError:
            self.locdb = {}

    def main(self, args: List[str]) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        parser_edit = subparsers.add_parser("edit")
        parser_edit.add_argument("terms", nargs="*")
        parser_edit.add_argument("--strict-location", action="store_true")
        parser_edit.set_defaults(func=self.main_edit)

        parser_list = subparsers.add_parser("keywords")
        parser_list.add_argument("--sorted", action="store_true")
        parser_list.add_argument("field", nargs="?")
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
        Opens the entry for editing and then formats it before saving.
        """
        locdb = {} if args.strict_location else self.locdb
        matching = self.read_matching_entries(args.terms, locdb=locdb)
        if not matching:
            error("no matching entries")

        editpaths = []
        for e in matching:
            editpath = self.create_entry_for_editing(e)
            editpaths.append(editpath)

        while True:
            editor = os.environ.get("EDITOR", "nano")
            r = subprocess.run([editor] + editpaths)
            if r.returncode != 0:
                error(f"editor process exited with error code {r.returncode}")

            success = True
            for original_entry, editpath in zip(matching, editpaths):
                try:
                    with open(editpath, "r", encoding="utf8") as f:
                        entry = parse_entry(self.directory, f)
                except OeuvreError as e:
                    success = False
                    error(str(e), lineno=e.lineno, path=editpath, fatal=False)
                    if not confirm("Try again? "):
                        sys.exit(1)
                else:
                    # Call `format_for_disk` before opening the file for writing, so
                    # that if there's an error the file is not wiped out.
                    text = format_for_disk(entry)
                    assert isinstance(original_entry["filename"], str)
                    original_full_path = os.path.join(
                        self.directory, original_entry["filename"]
                    )
                    with open(original_full_path, "w", encoding="utf8") as f:
                        f.write(text)
                        f.write("\n")

                    # Only print the entry if only one was opened for editing.
                    if len(editpaths) == 1:
                        print(text)

            if success:
                break

    def main_keywords(self, args: argparse.Namespace) -> None:
        """
        Lists all keywords from the database.
        """
        if args.field:
            if args.field not in FIELDS:
                error(f"{args.field} is not a valid field")

            if not FIELDS[args.field].keyword_style:
                error(f"{args.field} is not a keyword field")

        counter: defaultdict = defaultdict(int)
        entries = self.read_entries()
        for entry in entries:
            for field in entry:
                if field not in FIELDS:
                    continue

                if field == "characters":
                    continue

                if not FIELDS[field].keyword_style:
                    continue

                if args.field and field != args.field:
                    continue

                for keyword in entry[field]:
                    assert isinstance(keyword, KeywordField)
                    name = (
                        keyword.keyword if args.field else field + ":" + keyword.keyword
                    )
                    counter[name] += 1

        # Sort by count and then by name if --sorted flag was present. Otherwise, just
        # by name.
        key = lambda kv: (-kv[1], kv[0]) if args.sorted else kv[0]
        for keyword, count in sorted(counter.items(), key=key):
            print(f"{keyword} ({count})")

    def main_new(self, args: argparse.Namespace) -> None:
        """
        Creates a new entry.
        """
        editpath = self.create_entry_for_editing({"filename": "new_entry.txt"})
        while True:
            editor = os.environ.get("EDITOR", "nano")
            r = subprocess.run([editor, editpath])
            if r.returncode != 0:
                error(f"editor process exited with error code {r.returncode}")

            try:
                with open(editpath, "r", encoding="utf8") as f:
                    entry = parse_entry(self.directory, f)
            except OeuvreError as e:
                error(str(e), lineno=e.lineno, path=editpath, fatal=False)
                if not confirm("Try again? "):
                    sys.exit(1)

                continue
            else:
                # Call `format_for_disk` before opening the file for writing, so
                # that if there's an error the file is not wiped out.
                text = format_for_disk(entry)
                original_full_path = os.path.join(self.directory, args.path)
                with open(original_full_path, "w", encoding="utf8") as f:
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
            assert isinstance(entry["filename"], str)
            path = os.path.join(self.directory, entry["filename"])
            text = format_for_disk(entry)
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
            print(format_for_display(entry))

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
                print("  " + format_for_display(entry))
        else:
            print(format_for_disk(matching[0], brief=args.brief))

    def create_entry_for_editing(self, original_entry: Entry) -> str:
        """
        Creates a temporary file for editing the given entry and returns the file path.
        """
        editdir = os.path.join(self.directory, "editing")
        if not os.path.exists(editdir):
            os.mkdir(editdir)

        editpath = os.path.join(editdir, original_entry["filename"].replace("/", "__"))
        text = format_for_editing(original_entry)
        with open(editpath, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")

        return editpath

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
                try:
                    entry = parse_entry(self.directory, f)
                except OeuvreError as e:
                    error(str(e), lineno=e.lineno, path=path)

                entries.append(entry)
        return entries


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

    # TODO(2020-05-17): Handle location matching more intelligently.
    if search_field:
        fields_to_match = [search_field]
    else:
        fields_to_match = [
            field for field, fielddef in FIELDS.items() if fielddef.searchable
        ] + ["filename"]

    for field in fields_to_match:
        if field not in entry:
            continue

        field_value = entry[field]
        if search_field == "locations":
            if match_location(field_value, term, locdb):  # type: ignore
                return True
        elif isinstance(field_value, list):
            if any(
                pred(v.keyword if isinstance(v, KeywordField) else v)
                for v in field_value
            ):
                return True
        else:
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


def format_for_display(entry: Entry) -> str:
    """
    Returns the short string representation of the entry.

    This is the form that is shown to users for search results.
    """
    assert isinstance(entry["title"], str)
    assert isinstance(entry["filename"], str)
    if "creator" in entry:
        assert isinstance(entry["creator"], str)
        return (
            entry["title"] + " (" + entry["creator"] + ") [" + entry["filename"] + "]"
        )
    else:
        return entry["title"] + " [" + entry["filename"] + "]"


class FieldDef:
    def __init__(
        self,
        required=False,
        multiple=False,
        alphabetical=False,
        searchable=False,
        editable=True,
        keyword_style=False,
        choices=None,
        longform=False,
    ):
        if required and not editable:
            raise OeuvreError("required field must be editable")

        if keyword_style and not multiple:
            raise OeuvreError("multiple must be True if keyword_style is True")

        if alphabetical and not multiple:
            raise OeuvreError("multiple must be True if alphabetical is True")

        if longform and multiple:
            raise OeuvreError("multiple must not be True if longform is True")

        self.required = required
        self.multiple = multiple
        self.alphabetical = alphabetical
        self.searchable = searchable
        self.editable = editable
        self.keyword_style = keyword_style
        self.choices = choices
        self.longform = longform


class KeywordField:
    def __init__(self, keyword, description):
        self.keyword = keyword
        self.description = description

    @classmethod
    def from_string(cls, s):
        if ":" in s:
            keyword, description = s.split(":", maxsplit=1)
            keyword = keyword.rstrip()
            description = description.lstrip()
        else:
            keyword = s
            description = ""

        return cls(keyword, description)

    def __bool__(self):
        return bool(self.keyword or self.description)

    def __repr__(self):
        return f"KeywordField({self.keyword!r}, {self.description!r})"

    def __str__(self):
        if self.description:
            return f"{self.keyword}: {self.description}"
        else:
            return self.keyword


FIELDS: Dict[str, FieldDef] = OrderedDict(
    [
        ("title", FieldDef(required=True, searchable=True)),
        ("creator", FieldDef(searchable=True)),
        (
            "type",
            FieldDef(
                required=True, choices={"book", "story", "film", "play", "television"}
            ),
        ),
        ("year", FieldDef()),
        ("language", FieldDef()),
        ("plot-summary", FieldDef(longform=True)),
        (
            "characters",
            FieldDef(
                multiple=True, alphabetical=False, searchable=True, keyword_style=True
            ),
        ),
        (
            "locations",
            FieldDef(
                multiple=True, alphabetical=False, searchable=True, keyword_style=True
            ),
        ),
        (
            "topics",
            FieldDef(
                multiple=True, alphabetical=True, searchable=True, keyword_style=True
            ),
        ),
        (
            "settings",
            FieldDef(
                multiple=True, alphabetical=True, searchable=True, keyword_style=True
            ),
        ),
        (
            "technical",
            FieldDef(
                multiple=True, alphabetical=True, searchable=True, keyword_style=True
            ),
        ),
        (
            "external",
            FieldDef(
                multiple=True, alphabetical=True, searchable=True, keyword_style=True
            ),
        ),
        ("quotes", FieldDef(longform=True)),
        ("notes", FieldDef(longform=True)),
    ]
)


MAXIMUM_LENGTH = 80
INDENT = "  "


def format_for_editing(entry: Entry) -> str:
    """
    Returns the editable string representation of the entry.

    As opposed to `format_for_disk`, blank fields are included and non-editable fields
    are excluded.
    """
    lines = []
    for field, fielddef in FIELDS.items():
        if not fielddef.editable:
            continue

        value = entry.get(field, "")
        if fielddef.longform:
            lines.extend(list(multi_line_field(field, value, alphabetical=False)))
            lines.append("")
        elif (
            fielddef.multiple
            or "\n" in value
            or len(single_line_field(field, value)) > MAXIMUM_LENGTH
        ):
            lines.extend(
                list(multi_line_field(field, value, alphabetical=fielddef.alphabetical))
            )
            lines.append("")
        else:
            lines.append(single_line_field(field, value))

    if lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines)


def format_for_disk(entry: Entry, *, brief: bool = False) -> str:
    """
    Returns the string representation of the entry to be written to disk.

    If `brief` is True, then the values of fields marked `longform` are not printed.
    """
    lines = []
    for field, fielddef in FIELDS.items():
        if field not in entry:
            continue

        value = entry[field]
        if not value:
            continue

        if fielddef.longform:
            if brief:
                lines.append(single_line_field(field, "<hidden>"))
            else:
                lines.extend(list(multi_line_field(field, value, alphabetical=False)))
                lines.append("")
        elif (
            fielddef.multiple
            or "\n" in value
            or len(single_line_field(field, value)) > MAXIMUM_LENGTH
        ):
            lines.extend(
                list(multi_line_field(field, value, alphabetical=fielddef.alphabetical))
            )
            lines.append("")
        else:
            lines.append(single_line_field(field, value))

    if lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines)


def single_line_field(field: str, value: Field) -> str:
    """
    Returns the field and value as a single line.
    """
    return field + ": " + str(value)


def multi_line_field(
    field: str, value: Field, *, alphabetical: bool = False
) -> Iterator[str]:
    """
    Returns the field and value as multiple indented lines.
    """
    if isinstance(value, list):
        yield field + ":"
        values = [str(v) for v in value]
        for v in sorted(values) if alphabetical else values:
            yield from textwrap.wrap(
                str(v),
                width=MAXIMUM_LENGTH,
                initial_indent=INDENT,
                subsequent_indent=(INDENT * 2),
            )
    else:
        yield field + ":"

        paragraphs = value.splitlines()
        for i, paragraph in enumerate(paragraphs):
            if i != 0:
                yield ""

            yield from textwrap.wrap(
                paragraph,
                width=MAXIMUM_LENGTH,
                initial_indent=INDENT,
                subsequent_indent=INDENT,
            )


def parse_entry(directory: str, f: IO[str]) -> Entry:
    """
    Reads a database entry from a file object.

    Raises an `OeuvreError` if the file is incorrectly formatted.
    """
    entry = OrderedDict()  # type: Entry
    # The name of the current field that is being populated.
    field = None
    sep = " "

    for lineno, line in enumerate(f, start=1):
        indented = line.startswith("  ")
        double_indented = line.startswith("    ")
        line = line.strip()
        if not line:
            sep = "\n"
            continue

        if double_indented and field is not None and FIELDS[field].keyword_style:
            if not entry[field]:
                raise OeuvreError("unexpected double indentation", lineno=lineno)

            # If doubly indented and the field is keyword-style, then the line belongs
            # to the description of the previous keyword.
            previous_value = entry[field][-1]
            previous_value.description += " " + line
        elif indented:
            if field is None:
                raise OeuvreError("indented text without a field", lineno=lineno)

            previous_value = entry[field]
            if FIELDS[field].multiple:
                if FIELDS[field].keyword_style:
                    line = KeywordField.from_string(line)

                previous_value.append(line)
            else:
                entry[field] = previous_value + sep + line if previous_value else line
        else:
            if ":" not in line:
                raise OeuvreError("un-indented line without a colon", lineno=lineno)

            field, value = line.split(":", maxsplit=1)
            field = field.strip()
            value = value.strip()

            if field not in FIELDS:
                raise OeuvreError(f"unknown field {field!r}", lineno=lineno)

            if FIELDS[field].multiple:
                if FIELDS[field].keyword_style:
                    value = KeywordField.from_string(value)

                entry[field] = [value] if value else []
            else:
                entry[field] = value

        sep = " "

    validate_entry(entry)

    entry["filename"] = f.name.replace(directory + "/", "")
    return entry


def validate_entry(entry):
    """
    Checks if the entry is valid.
    """
    for field, fielddef in FIELDS.items():
        if fielddef.required and (field not in entry or not entry[field]):
            raise OeuvreError(f"missing required field {field!r}")
        elif fielddef.choices:
            if field not in entry or not entry[field]:
                continue

            if entry[field] not in fielddef.choices:
                choices = ", ".join(fielddef.choices)
                raise OeuvreError(f"value of field {field!r} must be one of: {choices}")


def alphabetical_key(entry):
    """
    Key for sort functions to sort entries alphabetically.
    """
    name = format_for_display(entry)
    if name.startswith("The "):
        return name[4:]
    elif name.startswith(("Le ", "La ")):
        return name[3:]
    else:
        return name


def error(
    message: str,
    *,
    lineno: Optional[int] = None,
    path: Optional[str] = None,
    fatal: bool = True,
) -> None:
    location: Optional[str]
    if path is not None:
        if lineno is not None:
            location = f"{path}, line {lineno}"
        else:
            location = path
    else:
        location = None

    if location:
        print(f"error: {message} ({location})", file=sys.stderr)
    else:
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


if __name__ == "__main__":
    app = Application(OEUVRE_DIRECTORY)
    app.main(sys.argv[1:])
