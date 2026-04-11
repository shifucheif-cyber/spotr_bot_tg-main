import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shutil

import pytest
import pytest_asyncio

# PostgreSQL available only when pg_ctl binary is on PATH
HAS_PG = shutil.which("pg_ctl") is not None

if HAS_PG:
    from pytest_postgresql import factories as pgf
    from pytest_postgresql.executor import PostgreSQLExecutor

    # On Windows, the default BASE_PROC_START_COMMAND uses single quotes
    # around values like 'stderr' and unix_socket_directories which PG
    # on Windows treats as literal parts of the value → FATAL.
    # Also, mirakuru uses os.killpg which doesn't exist on Windows.
    if os.name == "nt":
        PostgreSQLExecutor.BASE_PROC_START_COMMAND = (
            '{executable} start -D "{datadir}"'
            " -o \"-F -p {port}"
            " -c log_destination=stderr"
            " -c logging_collector=off"
            " {postgres_options}\""
            ' -l "{logfile}" {startparams}'
        )
        # Polyfill os.killpg for Windows (mirakuru calls it on teardown)
        def _killpg(pid, sig):
            try:
                os.kill(pid, sig)
            except (PermissionError, ProcessLookupError, OSError):
                pass

        os.killpg = _killpg

        postgresql_proc = pgf.postgresql_proc(unixsocketdir="")
    else:
        postgresql_proc = pgf.postgresql_proc()

    # function-scoped: creates a clean database per test
    postgresql = pgf.postgresql("postgresql_proc")


@pytest_asyncio.fixture()
async def pg_pool(request):
    """Create an asyncpg pool connected to a temporary PostgreSQL database.

    Injects the pool into ``services.user_store._pg_pool`` and calls
    ``init_user_store()`` so every test starts with a ready schema.
    Requires PostgreSQL binaries on PATH (``pg_ctl``).
    """
    if not HAS_PG:
        pytest.skip("PostgreSQL binaries not found (pg_ctl)")

    pg = request.getfixturevalue("postgresql")

    import asyncpg
    import services.user_store as mod

    dsn = (
        f"postgresql://{pg.info.user}@{pg.info.host}"
        f":{pg.info.port}/{pg.info.dbname}"
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    mod._pg_pool = pool

    await mod.init_user_store()

    yield pool

    await pool.close()
    mod._pg_pool = None
