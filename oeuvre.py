#!/usr/bin/env python3
"""
I keep a database of notes on books that I've read and films that I've watched. This
script helps me manage this database by

- allowing me to search the database intelligently.

- assisting with data entry and automatically formatting the entries nicely.

It is currently (as of May 2020) a work in progress.


Author:  Ian Fisher (iafisher@protonmail.com)
Version: May 2020
"""
import argparse
import glob
import os
import readline  # noqa: F401
import subprocess
import sys
import textwrap
from collections import OrderedDict
from typing import Dict, IO, Iterator, List, Tuple, Union


OEUVRE_DIRECTORY = "/home/iafisher/Dropbox/oeuvre"


# Type definitions
Field = Union[List[str], str]
FieldDef = Dict[str, bool]
Entry = Dict[str, Field]


def main(args: List[str]) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    parser_edit = subparsers.add_parser("edit")
    parser_edit.add_argument("path")
    parser_edit.set_defaults(func=main_edit)

    parser_new = subparsers.add_parser("new")
    parser_new.set_defaults(func=main_new)

    parser_search = subparsers.add_parser("search")
    parser_search.add_argument("terms", nargs="*")
    parser_search.add_argument("--partial", action="store_true")
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

        try:
            with open(fullpath, "r", encoding="utf8") as f:
                entry = parse_entry(f)
        except OeuvreError as e:
            print(f"Error: {e}")
            if not confirm("Try again? "):
                sys.exit(1)
        else:
            with open(fullpath, "w", encoding="utf8") as f:
                f.write(longform(entry))
                f.write("\n")
            break


def main_new(args: argparse.Namespace) -> None:
    """
    Creates a new entry through interactive prompts.
    """
    while True:
        entry = OrderedDict()  # type: Entry
        for fieldname, field in FIELDS.items():
            value = prompt_field(fieldname, field)
            if value:
                entry[fieldname] = value

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
    entries = []
    for path in sorted(glob.glob(OEUVRE_DIRECTORY + "/**/*.txt", recursive=True)):
        with open(path, "r", encoding="utf8") as f:
            try:
                entry = parse_entry(f)
            except OeuvreError as e:
                error(str(e))

            entries.append(entry)

    matching = [
        entry for entry in entries if match(entry, args.terms, partial=args.partial)
    ]
    for entry in sorted(matching, key=alphabetical_key):
        if args.verbose:
            print(longform(entry))
            print()
            print()
        else:
            print(shortform(entry))


def prompt_field(fieldname: str, field: FieldDef) -> Field:
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
        if field.get("multiple"):
            if value:
                values.append(value)
            elif not field.get("required"):
                if field.get("alphabetical"):
                    values.sort()

                return values
        else:
            if value or not field.get("required"):
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


def match(entry: Entry, search_terms: List[str], *, partial: bool = False) -> bool:
    """
    Returns True if the entry matches the search terms.

    Search terms are joined by an implicit AND operator.

    If `partial` is True, then the search term can match partially, e.g. `war` can match
    `civil-war`.
    """
    return all(
        match_one(entry, search_term, partial=partial) for search_term in search_terms
    )


def match_one(entry: Entry, search_term: str, *, partial: bool = False) -> bool:
    """
    Returns True if the entry matches the single search term.

    See `match` for meaning of `partial` argument.
    """
    field, term = split_term(search_term)
    if field not in entry:
        return False

    if partial:
        pred = lambda v: term.lower() in v.lower()
    else:
        pred = lambda v: term.lower() == v.lower()

    # TODO(2020-05-17): Handle location matching more intelligently.
    if isinstance(entry[field], list):
        return any(pred(v) for v in entry[field])
    else:
        return pred(entry[field])


def split_term(term: str) -> Tuple[str, str]:
    """
    Splits the term into a field name and a bare term.

    The field name defaults to 'keywords' if it is not supplied.
    """
    if ":" in term:
        field, term = term.split(":", maxsplit=1)
        return (field, term)
    else:
        return ("keywords", term)


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


FIELDS: Dict[str, FieldDef] = OrderedDict(
    [
        ("title", dict(required=True)),
        ("creator", dict()),
        ("type", dict(required=True)),
        ("year", dict()),
        ("language", dict()),
        ("plot-summary", dict()),
        ("themes", dict()),
        ("locations", dict(multiple=True, alphabetical=False)),
        ("keywords", dict(multiple=True, alphabetical=True)),
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
                list(
                    multi_line_field(
                        field, value, alphabetical=fielddef.get("alphabetical", False)
                    )
                )
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
            if FIELDS[field].get("multiple"):
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

            if FIELDS[field].get("multiple"):
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
