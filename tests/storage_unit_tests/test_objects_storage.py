# tests/storage_unit_tests/test_objects_storage.py
import pandas as pd
from pathlib import Path
import importlib, shutil

# ───✅ SNAPSHOT UPSERT TESTS ─────────────────────────────────────────────

def test_upsert_create_update_remove(tmp_path, monkeypatch):
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")

    # Point storage to tmp
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)

    # create
    df = pd.DataFrame([{
        "id":"00001","type":"support","left":10,"y":420.0,
        "status":"active","symbol":"SPY","timeframe":"15m"
    }])
    io.upsert_current_objects(df)
    cur = io.load_current_objects()
    assert len(cur)==1 and cur.iloc[0]["y"]==420.0

    # update
    df2 = pd.DataFrame([{"id":"00001","y":421.5}])
    io.upsert_current_objects(df2)
    cur = io.load_current_objects()
    assert float(cur.iloc[0]["y"])==421.5

    # remove
    df3 = pd.DataFrame([{"id":"00001","status":"removed"}])
    io.upsert_current_objects(df3)
    cur = io.load_current_objects()
    assert len(cur) == 0

# ───✅ TIMELINE APPEND / PARTITION TESTS ─────────────────────────────────

def test_append_timeline_partitions_by_day(tmp_path, monkeypatch):
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)

    day = "2025-09-12"
    ev = pd.DataFrame([{
        "step":1, "ts": f"{day}T14:30:00Z", "action":"create", "reason":"test",
        "object_id":"00001","type":"support","left":10,"y":420.0,
        "status":"active","symbol":"SPY","timeframe":"15m",
    }])
    out = io.append_timeline_events(ev)
    assert out.name == f"{day}.parquet"
    assert out.exists()

# ───✅ QUERY HELPERS TESTS ───────────────────────────────────────────────

def test_query_by_y_range_levels_and_zones(tmp_path, monkeypatch):
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)

    # seed snapshot: one level (y=525), one zone (top=530,bottom=520), one outside
    df = pd.DataFrame([
        {"id":"L1","type":"support","left":100,"y":525.0,"status":"active","symbol":"SPY","timeframe":"15m"},
        {"id":"Z1","type":"resistance","left":110,"top":530.0,"bottom":520.0,"status":"active","symbol":"SPY","timeframe":"15m"},
        {"id":"X1","type":"support","left":120,"y":505.0,"status":"active","symbol":"SPY","timeframe":"15m"},
    ])
    io.upsert_current_objects(df)

    got = io.query_current_by_y_range(520.0, 530.0, symbol="SPY", timeframe="15m")
    ids = set(got["id"].tolist())
    assert ids == {"L1","Z1"}  # X1 is outside (505)

def test_query_by_y_and_x_window(tmp_path, monkeypatch):
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)

    df = pd.DataFrame([
        {"id":"A","type":"support","left":100,"y":525.0,"status":"active","symbol":"SPY","timeframe":"15m"},
        {"id":"B","type":"support","left":150,"y":526.0,"status":"active","symbol":"SPY","timeframe":"15m"},
    ])
    io.upsert_current_objects(df)

    got = io.query_current_by_y_and_x(520.0, 530.0, gx_start=120, gx_end=200, symbol="SPY", timeframe="15m")
    ids = set(got["id"].tolist())
    assert ids == {"B"}  # A is left=100 (outside window)

# ───✅ PARQUET-ONLY WORKFLOW TESTS (NEW) ────────────────────────────────

def test_day_step_increments_and_resets(tmp_path, monkeypatch):
    # `day_step` sequences within and across days`, Verifies: first event of a day is step 1; subsequent events increment; a new day starts back at 1.
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")

    # point storage to temp
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)

    # Day 1: step 1 then 2
    day1 = "2025-09-15"
    ev1 = pd.DataFrame([{
        "day_step": 1, "ts": f"{day1}T14:30:00Z", "action":"create", "reason":"t1",
        "object_id":"00001","type":"support","left":10,"y":420.0,"status":"active","symbol":"SPY","timeframe":"15m",
    }])
    out1 = io.append_timeline_events(ev1)
    df1 = pd.read_parquet(out1)
    assert df1["day_step"].max() == 1

    ev2 = ev1.copy()
    ev2["day_step"] = 2
    ev2["ts"] = f"{day1}T14:45:00Z"
    io.append_timeline_events(ev2)
    df1b = pd.read_parquet(out1)
    assert df1b["day_step"].max() == 2

    # Day 2: starts at 1 again
    day2 = "2025-09-16"
    ev3 = ev1.copy()
    ev3["day_step"] = 1
    ev3["ts"] = f"{day2}T09:30:00Z"
    io.append_timeline_events(ev3)
    out2 = paths.TIMELINE_OBJECTS_DIR / day2[:7] / f"{day2}.parquet"
    df2 = pd.read_parquet(out2)
    assert df2["day_step"].max() == 1

def test_add_timeline_step_updates_snapshot(tmp_path, monkeypatch):
    # Snapshot mirroring via `add_timeline_step(...)`, Verifies: calling `add_timeline_step` writes the timeline and updates the snapshot.
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    objs = importlib.import_module("objects")

    # point storage to temp
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io)
    importlib.reload(objs)

    today = "2025-09-17"
    objs.add_timeline_step(
        [{"id":"00042","type":"support","left":123,"y":555.5,"status":"active"}],
        action="create",
        reason="unit-test",
        ts=f"{today}T10:00:00Z",
        write_snapshot=True,
    )

    # timeline has day_step
    tpath = paths.TIMELINE_OBJECTS_DIR / today[:7] / f"{today}.parquet"
    tl = pd.read_parquet(tpath)
    assert "day_step" in tl.columns and tl["day_step"].max() == 1

    # snapshot got upserted
    snap = io.load_current_objects()
    row = snap.set_index("id").loc["00042"]
    assert float(row["y"]) == 555.5 and row["status"] == "active"

def test_next_object_id_from_snapshot(tmp_path, monkeypatch):
    # ID sequencing from snapshot, Verifies: `_next_object_serial_from_parquet()` allocates consecutive IDs.
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    objs = importlib.import_module("objects")

    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io); importlib.reload(objs)

    # seed one object
    io.upsert_current_objects(pd.DataFrame([{
        "id":"00009","type":"support","left":1,"y":1.0,"status":"active","symbol":"SPY","timeframe":"15m"
    }]))

    nxt = objs._next_object_serial_from_parquet()
    assert nxt == 10  # 00010 is next

def test_remove_event_marks_snapshot_and_timeline(tmp_path, monkeypatch):
    import importlib, pandas as pd
    paths = importlib.import_module("paths")
    io = importlib.import_module("storage.objects.io")
    objs = importlib.import_module("objects")

    # point to temp storage
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io); importlib.reload(objs)

    # seed an active object
    io.upsert_current_objects(pd.DataFrame([{
        "id":"00999","type":"support","left":100,"y":400.0,"status":"active","symbol":"SPY","timeframe":"15m"
    }]))

    # remove it
    objs.log_object_removal([("00999","test removal")], reason="unit-test-removal")
    snap = io.load_current_objects().set_index("id")

    assert "00999" not in snap.index  # gone from snapshot
    # timeline wrote a row for today with action=remove
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tpath = paths.TIMELINE_OBJECTS_DIR / day[:7] / f"{day}.parquet"
    tl = pd.read_parquet(tpath)
    assert "remove" in set(tl["action"])

def test_snapshot_prunes_removed(tmp_storage):
    import importlib
    io = importlib.import_module("storage.objects.io")

    # seed two active, then mark one removed
    add = pd.DataFrame([
        {"id":"A","type":"support","left":1,"y":100.0,"status":"active","symbol":"SPY","timeframe":"15m"},
        {"id":"B","type":"resistance","left":2,"y":200.0,"status":"active","symbol":"SPY","timeframe":"15m"},
    ])
    io.upsert_current_objects(add)

    rm = pd.DataFrame([{"id":"A","status":"removed","symbol":"SPY","timeframe":"15m"}])
    io.upsert_current_objects(rm)

    cur = io.load_current_objects()
    ids = set(cur["id"].tolist())
    assert ids == {"B"}  # A is gone from snapshot

# ───✅ END-TO-END PIPELINE TEST ───────────────────────────────────────────

def test_eod_pipeline_writes_timeline_and_snapshot(tmp_path, monkeypatch):
    """
    End-to-end smoke test for the EOD objects path:
    - seeds a single 15m dayfile
    - runs process_end_of_day_15m_candles_for_objects()
    - verifies a timeline partition is written
    - verifies snapshot (current/objects.parquet) is updated
    """
    import importlib
    import pandas as pd

    # Modules
    paths = importlib.import_module("paths")
    io    = importlib.import_module("storage.objects.io")
    objs  = importlib.import_module("objects")

    # Point storage to tmp dirs
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "DATA_DIR", paths.STORAGE_DIR / "data")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")

    # Re-import modules after monkeypatch
    importlib.reload(io); importlib.reload(objs)

    # Seed one 15m day parquet (2 candles is enough to trigger your level/zone logic)
    day = "2025-09-02"
    tf_dir = paths.STORAGE_DIR / "data" / "15m"
    tf_dir.mkdir(parents=True, exist_ok=True)

    ts1 = int(pd.Timestamp("2025-09-02T13:30:00Z").value // 10**6)  # ms UTC
    ts2 = int(pd.Timestamp("2025-09-02T13:45:00Z").value // 10**6)

    df = pd.DataFrame([
        {"symbol":"SPY","timeframe":"15m","ts":ts1,"open":450.0,"high":451.0,"low":449.5,"close":450.5,"volume":100,"global_x":1000},
        {"symbol":"SPY","timeframe":"15m","ts":ts2,"open":450.5,"high":452.0,"low":450.0,"close":451.5,"volume":120,"global_x":1001},
    ])
    (tf_dir / f"{day}.parquet").parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(tf_dir / f"{day}.parquet", index=False)

    # Run the EOD pipeline
    objs.process_end_of_day_15m_candles_for_objects()

    # 1) Timeline partition got written (day_step present, at least one event)
    tpath = paths.TIMELINE_OBJECTS_DIR / day[:7] / f"{day}.parquet"
    assert tpath.exists(), "timeline dayfile not written"
    tl = pd.read_parquet(tpath)
    assert not tl.empty, "timeline dayfile has no rows"
    assert "day_step" in tl.columns
    assert int(tl["day_step"].min()) == 1

    # 2) Snapshot updated with at least one object (levels/zones)
    snap = io.load_current_objects()
    assert not snap.empty, "snapshot should have at least one object"
    # sanity on schema
    for col in ["id","type","symbol","timeframe","status"]:
        assert col in snap.columns

def test_eod_is_idempotent(tmp_path, monkeypatch):
    import importlib, pandas as pd, paths
    io   = importlib.import_module("storage.objects.io")
    objs = importlib.import_module("objects")

    # isolate storage
    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "DATA_DIR", paths.STORAGE_DIR / "data")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io); importlib.reload(objs)

    # seed one dayfile
    day = "2025-09-02"
    tf_dir = paths.STORAGE_DIR / "data" / "15m"
    tf_dir.mkdir(parents=True, exist_ok=True)
    ts = [int(pd.Timestamp("2025-09-02T13:30:00Z").value//10**6),
          int(pd.Timestamp("2025-09-02T13:45:00Z").value//10**6)]
    df = pd.DataFrame([
        {"symbol":"SPY","timeframe":"15m","ts":ts[0],"open":1,"high":2,"low":0.5,"close":1.5,"volume":1,"global_x":100},
        {"symbol":"SPY","timeframe":"15m","ts":ts[1],"open":1.6,"high":2.1,"low":1.0,"close":2.0,"volume":1,"global_x":101},
    ])
    df.to_parquet(tf_dir / f"{day}.parquet", index=False)

    # run twice
    objs.process_end_of_day_15m_candles_for_objects()
    objs.process_end_of_day_15m_candles_for_objects()

    # timeline still 1 “day” worth of events (no duplicates)
    tpath = paths.TIMELINE_OBJECTS_DIR / day[:7] / f"{day}.parquet"
    tl = pd.read_parquet(tpath)
    # all rows should have day_step starting at 1 and be unique by (day_step, object_id, action)
    assert tl["day_step"].min() == 1
    dedup = tl.drop_duplicates(subset=["day_step","object_id","action"])
    assert len(dedup) == len(tl)

    # snapshot has no dup ids
    snap = io.load_current_objects()
    assert snap["id"].is_unique

def test_eod_uses_min_global_x_as_offset(tmp_path, monkeypatch):
    import importlib, pandas as pd, paths
    io   = importlib.import_module("storage.objects.io")
    objs = importlib.import_module("objects")

    monkeypatch.setattr(paths, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(paths, "DATA_DIR", paths.STORAGE_DIR / "data")
    monkeypatch.setattr(paths, "OBJECTS_DIR", paths.STORAGE_DIR / "objects")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_DIR", paths.OBJECTS_DIR / "current")
    monkeypatch.setattr(paths, "TIMELINE_OBJECTS_DIR", paths.OBJECTS_DIR / "timeline")
    monkeypatch.setattr(paths, "CURRENT_OBJECTS_PATH", paths.CURRENT_OBJECTS_DIR / "objects.parquet")
    importlib.reload(io); importlib.reload(objs)

    day = "2025-09-03"
    tf_dir = paths.STORAGE_DIR / "data" / "15m"
    tf_dir.mkdir(parents=True, exist_ok=True)

    ts = [int(pd.Timestamp("2025-09-03T13:30:00Z").value//10**6),
          int(pd.Timestamp("2025-09-03T13:45:00Z").value//10**6)]
    df = pd.DataFrame([
        {"symbol":"SPY","timeframe":"15m","ts":ts[0],"open":10,"high":11,"low":9.5,"close":10.5,"volume":0,"global_x":34500},
        {"symbol":"SPY","timeframe":"15m","ts":ts[1],"open":10.6,"high":11.1,"low":10.0,"close":11.0,"volume":0,"global_x":34501},
    ])
    df.to_parquet(tf_dir / f"{day}.parquet", index=False)

    objs.process_end_of_day_15m_candles_for_objects()  # prints offset in log

    tpath = paths.TIMELINE_OBJECTS_DIR / day[:7] / f"{day}.parquet"
    tl = pd.read_parquet(tpath)
    assert not tl.empty
    # sanity: at least one event’s left/global_x should be >= 34500
    assert (tl["global_x"].dropna() >= 34500).any()
