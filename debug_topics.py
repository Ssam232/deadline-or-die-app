import os, requests, json
u, k = os.environ["ZOTERO_USER_ID"], os.environ["ZOTERO_API_KEY"]
b = f"https://api.zotero.org/users/{u}"; h = {"Zotero-API-Key": k, "Zotero-API-Version": "3"}
r = requests.get(f"{b}/items", headers=h, params={"itemType": "note", "q": "search topics", "qmode": "everything", "limit": 10})
print("library notes matching:", r.status_code, [(i["key"], i["data"].get("collections"), i["data"].get("parentItem"), i["data"]["note"][:120]) for i in r.json()])
cols = {c["data"]["name"]: c["key"] for c in requests.get(f"{b}/collections", headers=h, params={"limit": 100}).json()}
print("project key:", cols.get("LCR HCR CVxR"))
r = requests.get(f"{b}/collections/{cols.get('LCR HCR CVxR')}/items", headers=h, params={"itemType": "note", "limit": 100})
print("project notes:", r.status_code, len(r.json()))
