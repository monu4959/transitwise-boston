"""Load credentials from AWS Secrets Manager into the environment.

On AWS the MBTA and Snowflake credentials live in one Secrets Manager secret (a JSON object of
setting name -> value, e.g. {"MBTA_KEY": "...", "SNOWFLAKE_PRIVATE_KEY": "..."}). Setting
TRANSITWISE_SECRET_ID turns this on; locally it is unset and .env is used as before.
Values already in the environment win, so a local override still works.
"""
import json
import os


def load_secrets():
    """Copy the secrets' settings into os.environ. TRANSITWISE_SECRET_ID may list several secrets,
    comma-separated (e.g. app credentials and the OTP token, kept apart so each reader gets only
    what it needs). Returns the names loaded (never the values)."""
    ids = [s.strip() for s in (os.getenv("TRANSITWISE_SECRET_ID") or "").split(",") if s.strip()]
    if not ids:
        return []
    import boto3
    client = boto3.client("secretsmanager")
    loaded = []
    for secret_id in ids:
        values = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
        if not isinstance(values, dict):
            raise RuntimeError(f"Secret {secret_id} must be a JSON object of setting name -> value")
        for name, value in values.items():
            if isinstance(value, str) and value and not (os.getenv(name) or "").strip():
                os.environ[name] = value
                loaded.append(name)
    return loaded
