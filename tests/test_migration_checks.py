"""Include the public migration_check entry point in the standard regression run.

``migration_checks`` is a top-level module rather than part of ``tests`` so it
stays the standalone public command.  This bridge only registers its cases with
``unittest discover`` so one verify run covers the unchanged regression suite
and the migration checks together.
"""
import unittest

import migration_checks as public

MigrationChecks = public.MigrationChecks

__all__ = ['MigrationChecks']

if __name__ == '__main__':
    unittest.main()
