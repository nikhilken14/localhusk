import keyring
from keyring.errors import KeyringError, NoKeyringError
SERVICE_NAME = "localhusk"

class SecretStoreError(RuntimeError): 
    pass

def store_secret(reference, secret):
    if not secret: raise SecretStoreError("Secret cannot be empty.")
    try:
        keyring.set_password(SERVICE_NAME, reference, secret)
        if keyring.get_password(SERVICE_NAME, reference) != secret: raise SecretStoreError("OS keyring verification failed.")
    except (NoKeyringError, KeyringError) as exc:
        raise SecretStoreError("No usable OS keyring is available; configure one before saving API keys.") from exc

    
def get_secret(reference):
    if not reference: return None
    try: return keyring.get_password(SERVICE_NAME, reference)
    except (NoKeyringError, KeyringError) as exc: raise SecretStoreError("Unable to access OS keyring.") from exc


def delete_secret(reference):
    if not reference: return
    try: keyring.delete_password(SERVICE_NAME, reference)
    except keyring.errors.PasswordDeleteError: pass
    except (NoKeyringError, KeyringError) as exc: raise SecretStoreError("Unable to delete OS keyring secret.") from exc
