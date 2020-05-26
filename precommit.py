"""Pre-commit configuration for git.

This file was created by precommit (https://github.com/iafisher/precommit).
You are welcome to edit it yourself to customize your pre-commit hook.
"""
from precommitlib import checks


def init(precommit):
    # Generic checks
    precommit.check(checks.NoStagedAndUnstagedChanges())
    precommit.check(checks.NoWhitespaceInFilePath())
    precommit.check(checks.DoNotSubmit())

    # Language-specific checks
    precommit.check(checks.PythonFormat())
    precommit.check(checks.PythonLint(args=["--extend-ignore=E731"]))
    precommit.check(checks.PythonTypes(exclude=["precommit.py"]))
