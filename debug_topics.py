import os, requests, json
u, k = os.environ["ZOTERO_USER_ID"], os.environ["ZOTERO_API_KEY"]
b = f"https://api.zotero.org/users/{u}"; h = {"Zotero-API-Key": k, "Zotero-API-Version": "3"}
it = requests.get(f"{b}/items/PSXIX6IE", headers=h).json()
print("note item:", it["data"].get("collections"), it["data"].get("deleted"))
allnotes = requests.get(f"{b}/items", headers=h, params={"itemType": "note", "limit": 100}).json()
print("all notes:", [(i["key"], i["data"].get("collections"), i["data"]["note"][:50]) for i in allnotes if "search topics" in i["data"]["note"]])
proj = it["data"]["collections"][0]
rows = requests.get(f"{b}/collections/{proj}/items", headers=h, params={"limit": 100}).json()
print("project items (any type):", len(rows), [(i["key"], i["data"]["itemType"]) for i in rows if i["data"]["itemType"] == "note"])
rows = requests.get(f"{b}/collections/{proj}/items", headers=h, params={"itemType": "note"}).json()
print("project, itemType=note:", len(rows))
rows = requests.get(f"{b}/collections/{proj}/items", headers=h, params={"itemType": "note", "limit": 100, "start": 0}).json()
print("project, itemType=note, limit/start:", len(rows))
