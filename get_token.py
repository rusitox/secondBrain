"""Obtiene y renueva tokens de Microsoft Graph para secondBrain.

Uso:
  python get_token.py          # Obtiene un nuevo token (device code flow)
  python get_token.py refresh  # Renueva usando el refresh token guardado
"""
import json
import sys
from pathlib import Path

from msal import PublicClientApplication, SerializableTokenCache

CLIENT_ID = "ccf80d14-0cbd-4bbf-aaa9-c16a642e7b62"
AUTHORITY = "https://login.microsoftonline.com/60edbaa6-3a8b-41a8-a697-c1646a63668b"
SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Chat.Read",
    "https://graph.microsoft.com/User.Read",
]
CACHE_FILE = Path.home() / ".secondbrain" / "msal_cache.json"


def _load_cache() -> SerializableTokenCache:
    cache = SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    return cache


def _save_cache(cache: SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(cache.serialize())


def get_token() -> str:
    cache = _load_cache()
    app = PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try silent refresh first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    # Device code flow
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        print("No hay sesión guardada. Corré sin argumentos para autenticarte.")
        sys.exit(1)

    flow = app.initiate_device_flow(scopes=SCOPES)
    print(flow["message"])
    print()

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        _save_cache(cache)
        print("Token obtenido y guardado. La próxima vez podés renovarlo sin autenticarte.")
        return result["access_token"]
    else:
        print("Error:", result.get("error_description"))
        sys.exit(1)


if __name__ == "__main__":
    token = get_token()
    print(token)
