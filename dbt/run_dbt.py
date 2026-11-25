"""Run dbt with the project's Snowflake key-pair login.

dbt doesn't read .env, and the private key gets pasted into secrets in several shapes
(literal \n, one line, no BEGIN/END lines). This loads the settings the same way the app
does (agents/db.py) and hands dbt the key in memory. Nothing is written to disk, and dbt
scrubs DBT_ENV_SECRET_* values from its logs.

    python dbt/run_dbt.py build                 # local: DEV_STAGING / DEV_MARTS
    python dbt/run_dbt.py build --target prod   # GitHub Actions: STAGING / MARTS
"""
import base64
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from agents.db import _env, _private_key  # noqa: E402  (importing loads .env)

SETTINGS = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE",
            "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE"]


def main(args):
    for name in SETTINGS:                       # trimmed values; blanks fall back to defaults
        value = _env(name)
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
    missing = [n for n in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER") if n not in os.environ]
    if missing:
        sys.exit("Missing Snowflake settings: " + ", ".join(missing))
    key = _private_key()
    if key is None:
        sys.exit("No Snowflake key: set SNOWFLAKE_PRIVATE_KEY or SNOWFLAKE_PRIVATE_KEY_FILE.")
    os.environ["DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY"] = base64.b64encode(key).decode()
    os.environ.setdefault("DBT_PROJECT_DIR", str(HERE))
    os.environ.setdefault("DBT_PROFILES_DIR", str(HERE))

    from dbt.cli.main import dbtRunner
    result = dbtRunner().invoke(args)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
