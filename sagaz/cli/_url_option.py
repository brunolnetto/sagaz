"""Options whose former spellings still work but are not shown in ``--help`` (#572).

Every option that takes a data source's URL is named ``--<thing>-url`` and reads a
``SAGAZ_*_URL`` variable. Options renamed for that keep their former spelling as a
hidden alias::

    @click.option("--saga-log-url", "--saga-log", "saga_log", cls=RenamedOption, ...)

The first name is the one ``--help`` shows; the others are accepted and not listed.
"""

from __future__ import annotations

import click


class RenamedOption(click.Option):
    """A ``click.Option`` that lists only its first name in the help text."""

    def get_help_record(self, ctx: click.Context) -> tuple[str, str] | None:
        shown, self.opts = self.opts, self.opts[:1]
        try:
            return super().get_help_record(ctx)
        finally:
            self.opts = shown
