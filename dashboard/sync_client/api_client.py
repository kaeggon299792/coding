import requests

from config import API_TOKEN, CLIENT_NAME, SERVER_URL


def _headers():
    return {"Authorization": f"Bearer {API_TOKEN}", "X-Sync-Client": CLIENT_NAME}


def upload_folder_index(folders):
    response = requests.post(
        f"{SERVER_URL}/official-docs/api/archive-sync/folder-index",
        json={"client_name": CLIENT_NAME, "folders": folders},
        headers=_headers(),
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def verify_folder(document_id, status, **details):
    response = requests.post(
        f"{SERVER_URL}/official-docs/api/archive-sync/{document_id}/verify",
        json={"client_name": CLIENT_NAME, "folder_link_status": status, **details},
        headers=_headers(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()

