import server, json

with server.app.test_client() as c:
    r = c.get("/api/sim?minutes=2&seed=42")
    data = json.loads(r.data.decode())
    print("API /api/sim:", r.status_code,
          "events=%d ticks=%d pos=%d" % (len(data["events"]), len(data["ticks"]), len(data["position_seq"])))
    print("raining frames:", sum(1 for p in data["position_seq"] if p["raining"]))

    r2 = c.get("/static/models/drone_nologo.glb")
    ok = r2.status_code == 200 and r2.data[0:4] == b"glTF"
    print("GLB /static/models/drone_nologo.glb:", r2.status_code, len(r2.data), "bytes, valid_glb=", ok)

    r3 = c.get("/")
    print("index.html:", r3.status_code, len(r3.data), "bytes")
    print("ALL OK" if (r.status_code == 200 and ok) else "FAIL")
