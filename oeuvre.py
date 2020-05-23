#!/usr/bin/env python3
"""
I keep a database of notes on books that I've read and films that I've watched. This
script helps me manage this database by

- allowing me to search the database intelligently.

- assisting with data entry and automatically formatting the entries nicely.


Author:  Ian Fisher (iafisher@protonmail.com)
Version: May 2020
"""
import argparse
import datetime
import glob
import os
import readline  # noqa: F401
import subprocess
import sys
import textwrap
from collections import defaultdict, OrderedDict
from typing import Dict, IO, Iterator, List, Tuple, Union


OEUVRE_DIRECTORY = "/home/iafisher/Dropbox/oeuvre"


# Type definitions
Field = Union[List[str], str]
Entry = Dict[str, Field]


def main(args: List[str]) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    parser_edit = subparsers.add_parser("edit")
    parser_edit.add_argument("path")
    parser_edit.set_defaults(func=main_edit)

    parser_list = subparsers.add_parser("list")
    parser_list.add_argument("--sorted", action="store_true")
    parser_list.set_defaults(func=main_list)

    parser_new = subparsers.add_parser("new")
    parser_new.set_defaults(func=main_new)

    parser_search = subparsers.add_parser("search")
    parser_search.add_argument("terms", nargs="*")
    parser_search.add_argument("--verbose", action="store_true")
    parser_search.set_defaults(func=main_search)

    parsed_args = parser.parse_args(args)
    if hasattr(parsed_args, "func"):
        parsed_args.func(parsed_args)
    else:
        error("no subcommand")


def main_edit(args: argparse.Namespace) -> None:
    """
    Opens the entry for editing and then formats it before saving.
    """
    fullpath = os.path.join(OEUVRE_DIRECTORY, args.path)
    if not os.path.exists(fullpath):
        error(f"{args.path} does not exist")

    while True:
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, fullpath])
        timestamp = make_timestamp()

        try:
            with open(fullpath, "r", encoding="utf8") as f:
                entry = parse_entry(f)
        except OeuvreError as e:
            print(f"Error: {e}")
            if not confirm("Try again? "):
                sys.exit(1)
        else:
            entry["last-updated"] = timestamp
            with open(fullpath, "w", encoding="utf8") as f:
                f.write(longform(entry))
                f.write("\n")

            print(longform(entry))
            break


def main_list(args: argparse.Namespace) -> None:
    """
    Lists all keywords from the database.
    """
    counter: defaultdict = defaultdict(int)
    entries = read_entries()
    for entry in entries:
        if "keywords" in entry:
            for keyword in entry["keywords"]:
                counter[keyword] += 1

    # Sort by count and then by name if --sorted flag was present. Otherwise, just by
    # name.
    key = lambda kv: (-kv[1], kv[0]) if args.sorted else kv[0]
    for keyword, count in sorted(counter.items(), key=key):
        print(f"{keyword} ({count})")


def main_new(args: argparse.Namespace) -> None:
    """
    Creates a new entry through interactive prompts.
    """
    while True:
        entry = OrderedDict()  # type: Entry
        for fieldname, field in FIELDS.items():
            if not field.editable:
                continue

            value = prompt_field(fieldname, field)
            if value:
                entry[fieldname] = value

        timestamp = make_timestamp()
        entry["last-updated"] = timestamp
        entry["created-at"] = timestamp

        print()
        print()
        print(longform(entry))
        print()

        if confirm("Looks good? "):
            break

    while True:
        path = input("Enter the file path to save the entry: ")
        path = path.strip()
        fullpath = os.path.join(OEUVRE_DIRECTORY, path)

        if os.path.exists(fullpath):
            print("A file already exists at that path.")
        else:
            break

    with open(fullpath, "w", encoding="utf8") as f:
        f.write(longform(entry))
        f.write("\n")


def main_search(args: argparse.Namespace) -> None:
    """
    Searches all database entries and prints the matching ones.
    """
    entries = read_entries()
    matching = [entry for entry in entries if match(entry, args.terms, partial=True)]
    for entry in sorted(matching, key=alphabetical_key):
        if args.verbose:
            print(longform(entry))
            print()
            print()
        else:
            print(shortform(entry))


def read_entries() -> List[Entry]:
    """
    Returns a list of all entries in the database.
    """
    entries = []
    for path in sorted(glob.glob(OEUVRE_DIRECTORY + "/**/*.txt", recursive=True)):
        with open(path, "r", encoding="utf8") as f:
            try:
                entry = parse_entry(f)
            except OeuvreError as e:
                error(str(e))

            entries.append(entry)
    return entries


def prompt_field(fieldname: str, field: "FieldDef") -> Field:
    """
    Prompts for the field based on its definition (required, accepts multiple values).
    """
    values = []
    while True:
        try:
            value = input(fieldname + "? ")
        except EOFError:
            print()
            value = ""
        except KeyboardInterrupt:
            print()
            sys.exit(1)

        value = value.strip()
        if field.multiple:
            if value:
                values.append(value)
            elif not field.required:
                if field.alphabetical:
                    values.sort()

                return values
        else:
            if value or not field.required:
                return value


def confirm(prompt: str) -> bool:
    """
    Prompts the user for confirmation and returns whether they accepted or not.
    """
    try:
        yesno = input(prompt)
    except EOFError:
        print()
        return False
    except KeyboardInterrupt:
        print()
        sys.exit(1)

    yesno = yesno.strip().lower()
    return yesno.startswith("y")


def match(entry: Entry, search_terms: List[str], *, partial: bool) -> bool:
    """
    Returns True if the entry matches the search terms.

    Search terms are joined by an implicit AND operator.

    If `partial` is True, then the search term can match partially, e.g. `war` can match
    `civil-war`.
    """
    return all(
        match_one(entry, search_term, partial=partial) for search_term in search_terms
    )


def match_one(entry: Entry, search_term: str, *, partial: bool) -> bool:
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
        ]

    matches = False
    for field in fields_to_match:
        if field not in entry:
            continue

        if isinstance(entry[field], list):
            matches = matches or any(pred(v) for v in entry[field])
        else:
            matches = matches or pred(entry[field])

    return matches


def split_term(term: str) -> Tuple[str, str]:
    """
    Splits the term into a field name (which may be empty) and a bare term.
    """
    if ":" in term:
        field, term = term.split(":", maxsplit=1)
        return (field, term)
    else:
        return ("", term)


def shortform(entry: Entry) -> str:
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
    ):
        self.required = required
        self.multiple = multiple
        self.alphabetical = alphabetical
        self.searchable = searchable
        self.editable = editable


FIELDS: Dict[str, FieldDef] = OrderedDict(
    [
        ("title", FieldDef(required=True, searchable=True)),
        ("creator", FieldDef(searchable=True)),
        ("type", FieldDef(required=True)),
        ("year", FieldDef()),
        ("language", FieldDef()),
        ("plot-summary", FieldDef()),
        ("characters", FieldDef(multiple=True, alphabetical=False, searchable=True)),
        ("themes", FieldDef(searchable=True)),
        ("locations", FieldDef(multiple=True, alphabetical=False, searchable=True)),
        ("keywords", FieldDef(multiple=True, alphabetical=True, searchable=True)),
        ("quotes", FieldDef()),
        ("notes", FieldDef()),
        ("last-updated", FieldDef(editable=False)),
        ("created-at", FieldDef(editable=False)),
    ]
)


MAXIMUM_LENGTH = 80
INDENT = "  "


def longform(entry: Entry) -> str:
    """
    Returns the full string representation of the entry.

    This is the form that is written to file.
    """
    lines = []
    for field, fielddef in FIELDS.items():
        if field not in entry:
            continue

        value = entry[field]
        if (
            isinstance(value, list)
            or "\n" in value
            or len(single_line_field(field, value)) > MAXIMUM_LENGTH
        ):
            lines.extend(
                list(multi_line_field(field, value, alphabetical=fielddef.alphabetical))
            )
        else:
            lines.append(single_line_field(field, value))

    return "\n".join(lines)


def single_line_field(field: str, value: str) -> str:
    """
    Returns the field and value as a single line.
    """
    return field + ": " + value


def multi_line_field(
    field: str, value: Field, *, alphabetical: bool = False
) -> Iterator[str]:
    """
    Returns the field and value as multiple indented lines.
    """
    if isinstance(value, list):
        yield ""
        yield field + ":"
        for v in sorted(value) if alphabetical else value:
            yield INDENT + v
    else:
        yield ""
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


def parse_entry(f: IO[str]) -> Entry:
    """
    Reads a database entry from a file object.

    Raises an `OeuvreError` if the file is incorrectly formatted.
    """
    entry = OrderedDict()  # type: Entry
    field = None
    sep = " "

    for lineno, line in enumerate(f, start=1):
        indented = line.startswith("  ")
        line = line.strip()
        if not line:
            sep = "\n"
            continue

        if indented:
            if field is None:
                raise OeuvreError(f"indented text without a field (line {lineno})")

            previous_value = entry[field]
            if FIELDS[field].multiple:
                previous_value.append(line)
            else:
                entry[field] = previous_value + sep + line if previous_value else line
        else:
            if ":" not in line:
                raise OeuvreError(f"un-indented line without a colon (line {lineno})")

            field, value = line.split(":", maxsplit=1)
            field = field.strip()
            value = value.strip()

            if field not in FIELDS:
                raise OeuvreError(f"unknown field {field!r} (line {lineno})")

            if FIELDS[field].multiple:
                entry[field] = [value] if value else []
            else:
                entry[field] = value

        sep = " "

    entry["filename"] = f.name.replace(OEUVRE_DIRECTORY + "/", "")
    return entry


def alphabetical_key(entry):
    """
    Key for sort functions to sort entries alphabetically.
    """
    name = shortform(entry)
    if name.startswith("The "):
        return name[4:]
    elif name.startswith(("Le ", "La ")):
        return name[3:]
    else:
        return name


def make_timestamp() -> str:
    """
    Returns a timestamp for the current time.
    """
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def warning(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


class OeuvreError(Exception):
    pass


if __name__ == "__main__":
    x = 2 + 2
    main(sys.argv[1:])
