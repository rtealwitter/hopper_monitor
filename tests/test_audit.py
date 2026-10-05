"""Regression cases from the October 2026 monitor audit."""
import io
import os
import fcntl
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sample_gpu
import sample_queue
from render_readme import compute_headline, compute_open_times, parse_ts, render

T0 = "2026-10-02T10:00:00-07:00"
T1 = "2026-10-02T10:30:00-07:00"


def totals(ts):
    return dict(kind="totals", ts=ts, cpus_total=16, gpus_total=4)


def job(ts=T0, **kwargs):
    row = dict(ts=ts, job_id="7", state="RUNNING", gpus=4,
               gpus_scope="job", cpus=4, node="gpu01", user="user-test",
               lab="test-lab", wait_seconds=0, priority=None,
               age=None, fairshare=None, jobsize=None)
    row.update(kwargs)
    return row


class AllocationAuditTests(unittest.TestCase):
    def test_idle_snapshots_contribute_zero_to_allocation_average(self):
        rows = [job(), totals(T0), totals(T1)]
        result = compute_headline([], [], rows)
        self.assertEqual(result["pct_gpu_alloc"], 50)
        self.assertEqual(result["n_queue_snapshots"], 2)
        self.assertEqual(compute_open_times(rows)["best_hour_pct"], 50)

    def test_direct_statistics_normalize_and_deduplicate_legacy_rows(self):
        legacy = job(gpus_scope="node", node="gpu[01-02]", gpus=2)
        rows = [legacy, dict(legacy), totals(T0)]
        result = compute_headline([], [], rows)
        self.assertEqual(result["pct_gpu_alloc"], 100)
        self.assertEqual(result["table_rows"][0]["gpu_hours"], 2)
        self.assertEqual(legacy["gpus"], 2)
        self.assertEqual(compute_open_times(rows)["best_hour_pct"], 100)

    def test_missing_gpu_telemetry_does_not_erase_known_allocation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with patch("render_readme.usage_chart") as chart:
                render([], [], [job(), totals(T0), totals(T1)], path,
                       path / "README.md", parse_ts(T0),
                       parse_ts("2026-10-02T11:00:00-07:00"), "", False)
            gpu = next(call for call in chart.call_args_list
                       if call.args[2] == "GPUs")
            self.assertEqual(gpu.args[3], [parse_ts(T0), parse_ts(T1)])
            utilized, idle = gpu.args[4]["test-lab"]
            self.assertEqual(utilized, [0, 0])
            self.assertEqual(idle, [4, 0])

    def test_empty_queue_with_capacity_is_a_valid_report(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            render([], [], [totals(T0), totals(T1)], path,
                   path / "README.md", parse_ts(T0),
                   parse_ts("2026-10-02T11:00:00-07:00"), "", False)
            self.assertNotIn("No samples between", (path / "README.md").read_text())
            self.assertTrue((path / "gpu_alloc_util.png").exists())

    def test_missing_telemetry_is_not_extrapolated_as_idle_time(self):
        rows = [job(), totals(T0), job(T1), totals(T1)]
        gpu = [dict(ts=T0, node="gpu01", gpu_idx=0, job="7",
                    user="user-test", lab="test-lab", util_gpu=0)]
        result = compute_headline(gpu, [], rows)
        user = result["table_rows"][0]
        self.assertEqual(user["gpu_hours"], 4)
        self.assertEqual(user["measured_gpu_hours"], 0.5)
        self.assertEqual(user["idle_gpu_hours"], 0.5)

    def test_cpu_counter_reset_is_not_negative_utilization(self):
        rows = [job(), totals(T0), job(T1), totals(T1),
                dict(kind="job_id_map", ts=T1, raw_id="7", job_id="7")]
        cpu = [dict(ts=T0, node="gpu01", job_id="7", cpu_usage_usec=200),
               dict(ts=T1, node="gpu01", job_id="7", cpu_usage_usec=100)]
        self.assertEqual(compute_headline([], cpu, rows)["pct_cpu_util_when_alloc"], 0)


class SamplerAuditTests(unittest.TestCase):
    def test_mixed_bindings_ignore_non_gpu_indices_and_include_all_gpu_types(self):
        payload = dict(jobs=[dict(job_id=7, job_state=["RUNNING"], nodes="gpu01",
                       gres_detail=["mps:100(IDX:3),gpu:a100:1(IDX:0),gpu:l40s:1(IDX:1)"])])
        self.assertEqual(list(sample_queue.gpu_bindings(json.dumps(payload))),
                         [("7", "gpu01", 0), ("7", "gpu01", 1)])

    def test_mixed_capacity_uses_gpu_counts_only(self):
        def command(cmd):
            if cmd[0] == "sinfo":
                return "2|0/32/0/32|gpu:a100:2,gpu:l40s:4,mps:100"
            if cmd[:3] == ["scontrol", "show", "job"]:
                return '{"jobs": []}'
            return ""
        output = io.StringIO()
        with patch("sample_queue.run", side_effect=command), \
             patch("sys.argv", ["sample_queue.py", T0, "named", "salt"]), \
             patch("sys.stdout", output):
            sample_queue.main()
        row = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(row["gpus_total"], 12)
        self.assertEqual(row["cpus_total"], 32)

    def test_failed_slurm_command_is_not_an_empty_success(self):
        with self.assertRaises(subprocess.CalledProcessError):
            sample_queue.run([sys.executable, "-c", "raise SystemExit(1)"])

    def test_slurm_commands_have_a_timeout(self):
        with patch("sample_queue.subprocess.run") as command:
            sample_queue.run(["squeue"])
        self.assertEqual(command.call_args.kwargs["timeout"], 60)
        self.assertTrue(command.call_args.kwargs["check"])

    def gpu_sample(self, sample):
        output = io.StringIO()
        with patch("sys.argv", ["sample_gpu.py", T0, "gpu01", "anon_users", "salt"]), \
             patch("sys.stdin", io.StringIO(sample)), patch("sys.stdout", output):
            sample_gpu.main()
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_unknown_explicit_uuid_cannot_be_guessed_by_memory(self):
        rows = self.gpu_sample("""--GPU--
0, GPU-a, 50, 0, 100, 1000
--PROC--
GPU-missing, 101, 100
--CGROUP--
PIDMAP 101 alice job_7 test-lab
""")
        self.assertIsNone(rows[0]["job"])
        self.assertIsNone(rows[0]["user"])

    def test_missing_pid_fields_keep_lab_in_correct_column(self):
        rows = self.gpu_sample("""--GPU--
0, GPU-a, 50, 0, 100, 1000
--PROC--
GPU-a, 101, 100
--CGROUP--
PIDMAP 101 alice - test-lab
""")
        self.assertIsNone(rows[0]["job"])
        self.assertEqual(rows[0]["lab"], "test-lab")
        self.assertTrue(rows[0]["user"].startswith("user-"))
        self.assertNotIn("alice", json.dumps(rows))


class RunnerAuditTests(unittest.TestCase):
    def fixture(self, temp):
        root = Path(temp)
        (root / "config").write_text("MODE=anon_users\nINTERVAL_MIN=30\nSALT=test\n")
        script = (ROOT / "run.sh").read_text().replace('DIR="$HOME/hopper_monitor"',
                                                    f'DIR="{root}"')
        (root / "run.sh").write_text(script)
        return root

    def test_partial_queue_failure_does_not_append_or_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\necho partial\nexit 1\n")
            fake_python.chmod(0o755)
            result = subprocess.run(["bash", str(root / "run.sh")],
                                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / "data").exists())
            self.assertIn("queue sampling FAILED", (root / "monitor.log").read_text())

    def test_node_discovery_expands_hostlists_and_deduplicates_partitions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp)
            # Stop after discovery so this integration test never SSHs or submits jobs.
            script = (root / "run.sh").read_text().split('if [ -z "$GPU_NODES" ]; then')[0]
            script += 'printf "%s\\n" "$GPU_NODES"\n'
            (root / "run.sh").write_text(script)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            commands = {
                "python3": "#!/bin/sh\necho /dev/null\n",
                "squeue": "#!/bin/sh\nprintf 'gpu[01-02]\\nhimem01\\ngpu02\\n'\n",
                "scontrol": "#!/bin/sh\ncase \"$3\" in gpu\\[01-02\\]) printf 'gpu01\\ngpu02\\n';; *) echo \"$3\";; esac\n",
                "sinfo": "#!/bin/sh\nprintf 'gpu01|gpu:l40s:4\\ngpu02|gpu:l40s:4\\ngpu01|gpu:l40s:4\\nhimem01|(null)\\n'\n",
            }
            for name, source in commands.items():
                path = fake_bin / name
                path.write_text(source)
                path.chmod(0o755)
            result = subprocess.run(["bash", str(root / "run.sh")],
                                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["gpu01", "gpu02"])

    def test_overlapping_runner_skips_without_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp)
            with (root / ".run.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = subprocess.run(["bash", str(root / "run.sh")],
                                        capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((root / "data").exists())
            self.assertIn("previous run still in progress", (root / "monitor.log").read_text())

    def test_failed_ssh_discards_partial_gpu_and_cpu_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp)
            (root / "data").mkdir()
            for name in ("sample_gpu.py", "sample_cpu.py", "data_store.py", "anon.py"):
                shutil.copy(ROOT / name, root / name)
            (root / "sample_queue.py").write_text('print(\'{"kind":"totals"}\')\n')
            fake_bin = root / "bin"
            fake_bin.mkdir()
            commands = {
                "squeue": "#!/bin/sh\necho gpu01\n",
                "scontrol": "#!/bin/sh\necho gpu01\n",
                "sinfo": "#!/bin/sh\necho 'gpu01|gpu:l40s:4'\n",
                "ssh": "#!/bin/sh\nprintf '%s\\n' '--GPU--' '0, GPU-a, 80, 0, 100, 1000' 'CPUJOB 7 1000'\nexit 1\n",
                "sbatch": "#!/bin/sh\nexit 1\n",  # stop before publishing
            }
            for name, source in commands.items():
                path = fake_bin / name
                path.write_text(source)
                path.chmod(0o755)
            result = subprocess.run(["bash", str(root / "run.sh")],
                                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            for stream in ("gpu", "cpu"):
                parts = (root / "data" / f"{stream}_samples").glob("*.jsonl")
                self.assertFalse(any(p.stat().st_size for p in parts))
            self.assertEqual((root / "monitor.log").read_text().count("discarded"), 2)


if __name__ == "__main__":
    unittest.main()
