"""Compare incremental history with the original whole-history accounting."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accounting import cpu_rates, parse_ts
from history import History
from render_readme import compute_headline, compute_open_times, lab_palette, load_jsonl
from test_audit import job, totals

T0 = "2026-10-02T10:00:00-07:00"
T1 = "2026-10-02T10:10:00-07:00"
T2 = "2026-10-02T11:30:00-07:00"
T3 = "2026-10-03T11:30:00-07:00"


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        self.history = History(self.root)
        self.addCleanup(self.history.close)

    def append(self, stream, rows):
        with (self.root / "data" / f"{stream}_samples.jsonl").open("a") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def snapshot(self, ts, count=0, *, capacity=True, gpu=True):
        rows = [job(ts, job_id="7_2", gpus_scope="node", node="gpu[01-02]", gpus=2),
                job(ts, job_id="8", user="another-user", lab=None, cpus=1, gpus=0),
                dict(kind="job_id_map", ts=ts, raw_id="42", job_id="7_2")]
        rows += [dict(kind="gpu_bind", ts=ts, node="gpu01", gpu_idx=0, job_id="7_2")]
        if capacity:
            rows.append(totals(ts))
        self.append("queue", rows + [dict(rows[0])])
        if gpu:
            self.append("gpu", [dict(ts=ts, node="gpu01", gpu_idx=0, util_gpu=40 + count,
                                     job=None, user=None, lab=None)])
        self.append("cpu", [dict(ts=ts, node="gpu01", job_id="42", cpu_usage_usec=count * 600_000_000),
                            dict(ts=ts, node="gpu02", job_id="42", cpu_usage_usec=count * 300_000_000),
                            dict(ts=ts, node="gpu01", job_id="8", cpu_usage_usec=0)])

    def assertNestedAlmostEqual(self, actual, expected):
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys())
            for key in expected:
                with self.subTest(key=key):
                    self.assertNestedAlmostEqual(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.assertNestedAlmostEqual(a, b)
        elif isinstance(expected, (int, float)):
            self.assertAlmostEqual(actual, expected, places=7)
        else:
            self.assertEqual(actual, expected)

    def assertParity(self):
        gpu, cpu, queue = [load_jsonl(self.root / "data" / f"{stream}_samples.jsonl")
                           for stream in ("gpu", "cpu", "queue")]
        self.assertNestedAlmostEqual(self.history.headline(lab_palette), compute_headline(gpu, cpu, queue))
        self.assertNestedAlmostEqual(self.history.open_times(), compute_open_times(queue))
        _, _, rates = self.history.window(parse_ts(T1), parse_ts(T3))
        expected = {key: value for key, value in cpu_rates(cpu, queue).items()
                    if parse_ts(T1) <= parse_ts(key[0]) < parse_ts(T3)}
        self.assertNestedAlmostEqual(rates, expected)

    def test_initial_build_and_appends_match_whole_history(self):
        self.snapshot(T0)
        self.history.update()
        self.assertParity()
        self.snapshot(T1, 1, capacity=False)
        self.history.update()
        self.assertParity()  # last interval changes from 30 to 10 minutes
        self.snapshot(T2, 5, gpu=False)
        self.history.update()
        self.assertParity()  # outage remains capped at 30 minutes
        self.snapshot(T3, 0)  # reset counters
        self.history.update()
        self.assertParity()

    def test_reopened_cache_and_no_new_samples_do_not_read_history(self):
        self.snapshot(T0)
        self.snapshot(T1, 1)
        self.history.update()
        self.history.close()
        self.history = History(self.root)
        self.addCleanup(self.history.close)
        with patch.object(self.history, "rows", side_effect=AssertionError("re-read history")):
            self.assertFalse(self.history.update())
        self.assertParity()

    def test_late_data_rebuilds_bounded_accounting(self):
        self.snapshot(T0)
        self.snapshot(T1, 1)
        self.snapshot(T2, 2)
        self.history.update()
        self.append("gpu", [dict(ts=T0, node="gpu02", gpu_idx=0, util_gpu=90,
                                 job="7_2", user="user-test", lab="test-lab")])
        self.history.update()
        self.assertParity()

    def test_append_replays_only_the_last_snapshot_and_new_data(self):
        self.snapshot(T0)
        self.snapshot(T1, 1)
        self.history.update()
        self.snapshot(T2, 2)
        with patch.object(self.history, "rows", wraps=self.history.rows) as rows:
            self.history.update()
        self.assertTrue(rows.call_args_list)
        self.assertTrue(all(call.args[1] >= parse_ts(T1).timestamp() for call in rows.call_args_list))
        self.assertParity()

    def test_extra_rows_at_last_timestamp_and_cpu_only_tail(self):
        self.snapshot(T0)
        self.history.update()
        self.append("cpu", [dict(ts=T1, node="gpu01", job_id="42", cpu_usage_usec=600_000_000)])
        self.history.update()
        self.assertParity()
        self.snapshot(T1, 1)
        self.history.update()
        self.assertParity()
        self.snapshot(T2, 2)
        self.history.update()
        self.assertParity()

    def test_empty_capacity_snapshots_and_capacity_change(self):
        self.append("queue", [totals(T0), job(T1), {**totals(T2), "gpus_total": 8}])
        self.history.update()
        self.assertParity()

    def test_rewrite_and_truncation_rebuild_cache(self):
        self.snapshot(T0)
        self.snapshot(T1, 1)
        self.history.update()
        path = self.root / "data" / "gpu_samples.jsonl"
        path.write_text("")
        self.history.update()
        self.assertParity()

    def test_incomplete_append_is_only_indexed_once_complete(self):
        self.snapshot(T0)
        self.history.update()
        path = self.root / "data" / "queue_samples.jsonl"
        line = json.dumps(totals(T1))
        with path.open("a") as f:
            f.write(line[:10])
        self.assertFalse(self.history.update())
        with path.open("a") as f:
            f.write(line[10:] + "\n")
        self.assertTrue(self.history.update())
        self.assertParity()

    def test_interrupted_update_rolls_back_offsets_and_totals(self):
        self.snapshot(T0)
        self.history.update()
        self.snapshot(T1, 1)
        with patch.object(self.history, "_accumulate", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.history.update()
        self.history.update()
        self.assertParity()

    def test_parts_and_chart_window_only_return_relevant_samples(self):
        for stream in ("gpu", "cpu", "queue"):
            (self.root / "data" / f"{stream}_samples").mkdir()
        self.snapshot(T0)
        for stream in ("gpu", "cpu", "queue"):
            path = self.root / "data" / f"{stream}_samples.jsonl"
            path.rename(path.with_suffix("") / "part-00000000.jsonl")
        self.history.update()
        self.snapshot(T1, 1)
        for stream in ("gpu", "cpu", "queue"):
            path = self.root / "data" / f"{stream}_samples.jsonl"
            path.rename(path.with_suffix("") / "part-00000001.jsonl")
        self.history.update()
        self.assertParity()
        gpu, queue, _ = self.history.window(parse_ts(T1), parse_ts(T2))
        self.assertTrue(gpu and queue)
        self.assertEqual({r["ts"] for r in gpu + queue}, {T1})


if __name__ == "__main__":
    unittest.main()
