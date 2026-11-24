"""Load credentials from AWS Secrets Manager into the environment.

On AWS the MBTA and Snowflake credentials live in one Secrets Manager secret (a JSON object of
setting name -> value, e.g. {"MBTA_KEY": "...", "SNOWFLAKE_PRIVATE_KEY": "..."}). Setting
TRANSITWISE_SECRET_ID turns this on; locally it is unset and .env is used as before.
Values already in the environment win, so a local override still works.
"""
import json
import os


def load_secrets():
    """Copy the secret's settings into os.environ. Returns the names loaded (never the values)."""
    secret_id = (os.getenv("TRANSITWISE_SECRET_ID") or "").strip()
    if not secret_id:
        return []
    import boto3
    resp = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    values = json.loads(resp["SecretString"])
    if not isinstance(values, dict):
        raise RuntimeError(f"Secret {secret_id} must be a JSON object of setting name -> value")
    loaded = []
    for name, value in values.items():
        if isinstance(value, str) and value and not (os.getenv(name) or "").strip():
            os.environ[name] = value
            loaded.append(name)
    return loaded
