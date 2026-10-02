import json
import subprocess
import sys
import tempfile
import unittest
import io
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from render_readme import consume_idle_with_unattributed
from render_readme import load_jsonl
from data_store import migrate, sample_path, sample_files
from sample_queue import (display_job_id, expand_nodelist, gpu_bindings,
                          normalize_gpu_allocations, parse_gpus, main as sample_queue)


class SampleStorageTests(unittest.TestCase):
    def test_migration_preserves_bytes_order_and_bounded_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "queue_samples.jsonl"
            original = b'{"n":1}\n{"n":2}\n{"n":3}\n'
            path.write_bytes(original)
            migrate(path, limit=16)
            files = sample_files(path)
            self.assertFalse(path.exists())
            self.assertEqual(b"".join(p.read_bytes() for p in files), original)
            self.assertTrue(all(p.stat().st_size <= 16 for p in files))
            self.assertEqual(load_jsonl(path), [{"n": 1}, {"n": 2}, {"n": 3}])
            # Appending continues in the last part, then rolls over at the limit.
            active = sample_path(path, limit=16)
            with active.open("ab") as output:
                output.write(b'{"n":4}\n')
            next_part = sample_path(path, limit=16)
            self.assertNotEqual(active, next_part)
            next_part.write_bytes(b'{"n":5}\n')
            self.assertEqual([r["n"] for r in load_jsonl(path)], list(range(1, 6)))

    def test_completed_migration_takes_precedence_over_legacy_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gpu_samples.jsonl"
            path.write_text('{"n":1}\n')
            migrate(path)
            path.write_text('{"n":1}\n')  # interrupted legacy cleanup
            self.assertEqual(load_jsonl(path), [{"n": 1}])

    def test_oversized_record_leaves_original_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gpu_samples.jsonl"
            path.write_bytes(b"0123456789\n")
            with self.assertRaises(ValueError):
                migrate(path, limit=8)
            self.assertEqual(path.read_bytes(), b"0123456789\n")
            self.assertFalse(path.with_suffix("").exists())


class GpuSampleTests(unittest.TestCase):
    def test_uuid_maps_symmetric_tensor_parallel_processes_to_exact_cards(self):
        sample = """--GPU--
0, GPU-a, 81, 50, 44059, 46068
1, GPU-b, 85, 51, 44059, 46068
--PROC--
GPU-a, 101, 44050
GPU-b, 102, 44050
--CGROUP--
PIDMAP 101 alice job_7 witter-lab
PIDMAP 102 alice job_7 witter-lab
"""
        proc = subprocess.run(
            [sys.executable, str(ROOT / "sample_gpu.py"),
             "2026-08-27T11:00:00-07:00", "gpu15", "named", "salt"],
            input=sample, text=True, capture_output=True, check=True,
        )
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["gpu_idx"] for r in rows], [0, 1])
        self.assertEqual([r["gpu_uuid"] for r in rows], ["GPU-a", "GPU-b"])
        self.assertTrue(all(r["job"] == "job_7" for r in rows))


class SlurmBindingTests(unittest.TestCase):
    def test_eight_node_allocation_has_32_physical_gpus(self):
        job = {"job_id": 7, "job_state": ["RUNNING"],
               "nodes": "gpu[08-15]",
               "gres_detail": ["gpu:l40s:4(IDX:0-3)"] * 8}
        bindings = list(gpu_bindings(json.dumps({"jobs": [job]})))
        self.assertEqual(len(set(bindings)), 32)
        self.assertEqual({node for _, node, _ in bindings},
                         {f"gpu{i:02}" for i in range(8, 16)})

    def test_sampler_emits_job_total_with_and_without_bindings(self):
        job = {"job_id": 7, "job_state": ["RUNNING"],
               "nodes": "gpu[08-15]",
               "gres_detail": ["gpu:l40s:4(IDX:0-3)"] * 8}
        for jobs in ([job], []):
            def command(cmd):
                if cmd[0] == "squeue":
                    return "7|alice|RUNNING|32|gres/gpu:l40s:4|gpu[08-15]|N/A|N/A|None|8"
                if cmd[:4] == ["scontrol", "show", "job", "-dd"]:
                    return json.dumps({"jobs": jobs})
                if cmd[0] == "sinfo":
                    return "15|0/1920/0/1920|gpu:l40s:4"
                return ""
            output = io.StringIO()
            with patch("sample_queue.run", side_effect=command), \
                 patch("sys.argv", ["sample_queue.py", "ts", "named", "salt"]), \
                 patch("sys.stdout", output):
                sample_queue()
            row = json.loads(output.getvalue().splitlines()[0])
            self.assertEqual(row["gpus"], 32)
            self.assertEqual(row["gpus_scope"], "job")

    def test_legacy_correction_is_idempotent_and_keeps_raw_samples(self):
        rows = [{"ts": "t", "job_id": "7", "state": "RUNNING",
                 "gpus": 4, "node": "gpu[08-15]"},
                {"ts": "t", "job_id": "8", "state": "RUNNING",
                 "gpus": 1, "node": "gpu01"},
                {"ts": "t", "job_id": "9", "state": "PENDING",
                 "gpus": 1, "node": None}]
        fixed = normalize_gpu_allocations(rows)
        self.assertEqual([r["gpus"] for r in fixed], [32, 1, 1])
        self.assertEqual(rows[0]["gpus"], 4)
        self.assertEqual(normalize_gpu_allocations(fixed), fixed)
        self.assertEqual(normalize_gpu_allocations(rows + rows), fixed)

    def test_historical_bindings_override_uniform_node_assumption(self):
        rows = [{"ts": "t", "job_id": "7", "gpus": 4, "node": "gpu[01-02]"}]
        rows += [{"kind": "gpu_bind", "ts": "t", "job_id": "7",
                  "node": node, "gpu_idx": idx}
                 for node, idx in [("gpu01", 0), ("gpu02", 0), ("gpu02", 1)]]
        rows.append(dict(rows[-1]))  # repeated readings are not extra devices
        self.assertEqual(normalize_gpu_allocations(rows)[0]["gpus"], 3)

    def test_mixed_gres_does_not_count_other_resources(self):
        self.assertEqual(parse_gpus("gres/gpu:l40s:4,gres/mps:100"), 4)
        self.assertEqual(parse_gpus("gpu:a100:2,gpu:l40s:4"), 6)
        self.assertEqual(parse_gpus("gres/gpu:2"), 2)
        self.assertEqual(parse_gpus("N/A"), 0)

    def test_current_hopper_json_uses_top_level_nodes(self):
        payload = {"jobs": [{
            "job_id": 290094,
            "job_state": ["RUNNING"],
            "array_job_id": {"set": True, "number": 289497},
            "array_task_id": {"set": True, "number": 7},
            "het_job_id": {"set": True, "number": 0},
            "het_job_offset": {"set": True, "number": 0},
            "nodes": "gpu14",
            "gres_detail": ["gpu:l40s:4(IDX:0-3)"],
            "job_resources": {"allocated_nodes": None},
        }]}
        self.assertEqual(
            list(gpu_bindings(json.dumps(payload))),
            [("289497_7", "gpu14", 0), ("289497_7", "gpu14", 1),
             ("289497_7", "gpu14", 2), ("289497_7", "gpu14", 3)],
        )

    def test_heterogeneous_component_uses_squeue_identifier(self):
        job = {
            "job_id": 289763,
            "array_task_id": {"set": False, "number": 0},
            "het_job_id": {"set": True, "number": 289762},
            "het_job_offset": {"set": True, "number": 1},
        }
        self.assertEqual(display_job_id(job), "289762+1")

    def test_expand_nodelist(self):
        self.assertEqual(expand_nodelist("gpu[01-03,07]"),
                         ["gpu01", "gpu02", "gpu03", "gpu07"])
        self.assertEqual(expand_nodelist("gpu[01-02],gpu07"),
                         ["gpu01", "gpu02", "gpu07"])


class ChartAccountingTests(unittest.TestCase):
    def test_unattributed_busy_capacity_replaces_idle_not_allocation(self):
        series = {"witter-lab": ([13.85], [38.15])}
        fixed = consume_idle_with_unattributed(series, [23.94])
        stack_height = fixed["witter-lab"][0][0] + fixed["witter-lab"][1][0] + 23.94
        self.assertAlmostEqual(stack_height, 52.0)
        self.assertAlmostEqual(series["witter-lab"][1][0], 38.15)  # input untouched


if __name__ == "__main__":
    unittest.main()
