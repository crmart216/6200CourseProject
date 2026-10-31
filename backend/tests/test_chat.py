from uuid import uuid4

BASE = "/api/v1"


def user(client, name="alice"):
    response = client.post(f"{BASE}/users", json={"username": name, "display_name": name.title()})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def group(client, creator):
    response = client.post(f"{BASE}/groups", json={"name": "Study group", "created_by": creator})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_chat_lifecycle(client):
    alice, bob = user(client), user(client, "bob")
    gid = group(client, alice)
    path = f"{BASE}/groups/{gid}"
    assert client.get(path + "/members").json()[0]["user_id"] == alice
    assert (
        client.post(path + "/messages", json={"sender_id": bob, "content": "Hi"}).status_code == 409
    )
    assert client.post(path + "/members", json={"user_id": bob}).status_code == 201
    message = client.post(path + "/messages", json={"sender_id": bob, "content": "Hi"})
    assert message.status_code == 201
    mid = message.json()["id"]
    assert len(client.get(path + "/messages").json()) == 1
    edited = client.put(path + f"/messages/{mid}", json={"content": "Hello"})
    assert edited.json()["content"] == "Hello"
    assert edited.json()["updated_at"] is not None
    assert client.delete(path + f"/members/{bob}").status_code == 204
    assert client.get(path + f"/messages/{mid}").status_code == 200
    assert (
        client.post(path + "/messages", json={"sender_id": bob, "content": "Again"}).status_code
        == 409
    )
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(path + f"/messages/{mid}").status_code == 404


def test_conflict_and_rollback(client):
    uid = user(client)
    assert (
        client.post(
            f"{BASE}/users", json={"username": "alice", "display_name": "Other"}
        ).status_code
        == 409
    )
    gid = group(client, uid)
    path = f"{BASE}/groups/{gid}"
    assert client.post(path + "/members", json={"user_id": uid}).status_code == 409
    assert len(client.get(path + "/members").json()) == 1
    assert (
        client.post(
            f"{BASE}/groups", json={"name": "Missing", "created_by": str(uuid4())}
        ).status_code
        == 404
    )
    assert len(client.get(f"{BASE}/groups").json()) == 1


def test_validation_and_group_scope(client):
    uid = user(client)
    gid, other = group(client, uid), group(client, uid)
    path = f"{BASE}/groups/{gid}/messages"
    assert client.post(path, json={"sender_id": uid, "content": "   "}).status_code == 422
    assert client.get(path + "?limit=101").status_code == 422
    assert client.get(path + "?offset=-1").status_code == 422
    mid = client.post(path, json={"sender_id": uid, "content": "First"}).json()["id"]
    wrong = f"{BASE}/groups/{other}/messages/{mid}"
    assert client.get(wrong).status_code == 404
    assert client.put(wrong, json={"content": "Wrong"}).status_code == 404
    assert client.delete(wrong).status_code == 404
    assert client.delete(path + f"/{mid}").status_code == 204
    assert client.get(path).json() == []


def test_lists_updates_and_docs(client):
    uid = user(client)
    gid = group(client, uid)
    path = f"{BASE}/groups/{gid}"
    assert client.get(f"{BASE}/users/{uid}").status_code == 200
    assert len(client.get(f"{BASE}/users?limit=1").json()) == 1
    assert (
        client.put(path, json={"name": "Updated", "description": "New"}).json()["name"] == "Updated"
    )
    assert len(client.get(f"{BASE}/groups?user_id={uid}").json()) == 1
    for content in ["A", "B", "C"]:
        assert (
            client.post(path + "/messages", json={"sender_id": uid, "content": content}).status_code
            == 201
        )
    assert len(client.get(path + "/messages?limit=2").json()) == 2
    assert len(client.get(path + "/messages?limit=2&offset=2").json()) == 1
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["paths"]["/api/v1/groups/{group_id}/messages"][
        "post"
    ]["responses"]["201"]
