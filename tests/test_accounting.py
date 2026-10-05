"""Ownership, chart labeling, and failure cases from the October 5 audit."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accounting import attribute_gpus, cpu_rates, parse_ts
from render_readme import (LAB_PALETTE, UNATTRIB_FILL, compute_headline,
                           interval_hours, lab_palette, render, usage_chart)
import sample_gpu
import sample_queue
from test_audit import T0, T1, job, totals


def reading(**kwargs):
    row = dict(ts=T0, node='gpu01', gpu_idx=0, util_gpu=80,
               job=None, user=None, lab=None)
    row.update(kwargs)
    return row


class OwnershipTests(unittest.TestCase):
    def test_raw_array_cgroup_id_recovers_missing_lab_and_deduplicates(self):
        gpu = reading(job='job_42')
        queue = [job(job_id='7_2'), dict(kind='job_id_map', ts=T0,
                                       raw_id='42', job_id='7_2')]
        rows, recovered = attribute_gpus([gpu, dict(gpu)], queue)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['job'], '7_2')
        self.assertEqual(rows[0]['lab'], 'test-lab')
        self.assertEqual(recovered, 1)
        self.assertIsNone(gpu['lab'])

    def test_binding_repairs_partial_or_stale_process_ownership(self):
        bind = dict(kind='gpu_bind', ts=T0, node='gpu01', gpu_idx=0, job_id='7')
        rows, _ = attribute_gpus([reading(job='job_42', lab='stale-lab')], [job(), bind])
        self.assertEqual(rows[0]['lab'], 'test-lab')
        self.assertEqual(rows[0]['job'], '7')

    def test_never_borrows_another_snapshots_owner(self):
        bind = dict(kind='gpu_bind', ts=T1, node='gpu01', gpu_idx=0, job_id='7')
        rows, recovered = attribute_gpus([reading()], [job(T1), bind])
        self.assertIsNone(rows[0]['lab'])
        self.assertEqual(recovered, 0)

    def test_shared_device_usage_is_not_arbitrarily_charged_to_one_owner(self):
        gpu = [reading(job='7', lab='first-lab'), reading(job='8', lab='second-lab')]
        rows, recovered = attribute_gpus(gpu, [])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['lab'])
        self.assertEqual(rows[0]['util_gpu'], 80)
        self.assertEqual(recovered, 0)

    def test_cpu_non_array_ids_do_not_require_a_mapping_and_duplicates_do_not_count(self):
        cpu = [dict(ts=ts, node='gpu01', job_id='7', cpu_usage_usec=usage)
               for ts, usage in [(T0, 0), (T1, 1800_000_000)]]
        self.assertEqual(cpu_rates(cpu + cpu, [job(), job(T1)])[(T1, '7')], 1)

    def test_cpu_average_is_weighted_by_cores(self):
        queue = [job(T1, cpus=1), job(T1, job_id='8', cpus=9), totals(T1)]
        result = compute_headline([], [], queue, usage=([], {(T1, '7'): 1, (T1, '8'): 0}))
        self.assertEqual(result['pct_cpu_util_when_alloc'], 10)

    def test_cpu_window_keeps_preceding_counter_and_chart_matches_headline(self):
        cpu = [dict(ts=ts, node='gpu01', job_id='7', cpu_usage_usec=usage)
               for ts, usage in [(T0, 0), (T1, 3600_000_000)]]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with patch('render_readme.usage_chart') as chart:
                render([], cpu, [job(), totals(T0), job(T1), totals(T1)], path,
                       path/'README.md', parse_ts(T1), parse_ts('2026-10-02T11:00:00-07:00'), '', False)
            cpu_chart = next(c for c in chart.call_args_list if c.args[2] == 'CPUs')
            self.assertEqual(cpu_chart.args[4]['test-lab'][0], [2])
            self.assertIn('**50.0%** average cgroup CPU', (path/'README.md').read_text())

    def test_collection_outages_do_not_become_measured_gpu_hours(self):
        later = parse_ts('2026-10-02T16:30:00-07:00')
        self.assertEqual(interval_hours([parse_ts(T0), later])[parse_ts(T0)], 0.5)


class ChartTests(unittest.TestCase):
    def test_roundoff_cannot_create_a_phantom_unattributed_band(self):
        gpu = [reading(gpu_idx=i, job=str(40+i%3), lab=f'lab-{i%3}', util_gpu=10)
               for i in range(30)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with patch('render_readme.usage_chart') as chart:
                render(gpu, [], [totals(T0)], path, path/'README.md',
                       parse_ts(T0), parse_ts(T1), '', False)
            gpu_chart = next(c for c in chart.call_args_list if c.args[2] == 'GPUs')
            self.assertEqual(gpu_chart.kwargs['unattrib_y'], [0])

    def test_every_known_lab_has_a_distinct_non_gray_color(self):
        colors = lab_palette(LAB_PALETTE)
        self.assertEqual(len(set(colors.values())), len(colors))
        self.assertNotIn(UNATTRIB_FILL, colors.values())
        self.assertEqual(lab_palette(['zhuang-lab'])['zhuang-lab'], colors['zhuang-lab'])
        self.assertEqual(lab_palette(['new-lab'])['new-lab'],
                         lab_palette(['new-lab', 'zhuang-lab'])['new-lab'])

    def test_zero_unattributed_band_is_absent_but_real_unknown_is_labeled(self):
        import matplotlib.pyplot as plt
        for unknown in (0, 1):
            with tempfile.TemporaryDirectory() as temp, patch('render_readme.plt.close'):
                usage_chart(Path(temp)/'chart.png', 'GPU', 'GPUs', [parse_ts(T0)],
                            {'zhuang-lab': ([1], [2]), 'empty-lab': ([0], [0])},
                            lab_palette(['zhuang-lab', 'empty-lab']), unattrib_y=[unknown])
                labels = [t.get_text() for t in plt.gca().get_legend().get_texts()]
            plt.close('all')
            self.assertIn('zhuang-lab', labels)
            self.assertNotIn('Other', labels)
            self.assertNotIn('empty-lab', labels)
            self.assertEqual('usage, unattributed' in labels, bool(unknown))

    def test_missing_lab_does_not_crash_render(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            render([], [], [job(lab=None), totals(T0)], path, path/'README.md',
                   parse_ts(T0), parse_ts(T1), '', False)
            self.assertTrue((path/'gpu_alloc_util.png').exists())


class CollectionTests(unittest.TestCase):
    def test_invalid_slurm_json_is_not_an_empty_snapshot(self):
        with self.assertRaises(json.JSONDecodeError):
            list(sample_queue.gpu_bindings('{truncated'))
        with self.assertRaises(KeyError):
            list(sample_queue.job_id_map('{}'))

    def test_process_memory_is_not_required_to_join_uuid(self):
        sample = '--GPU--\n0, GPU-a, 80, 0, 100, 1000\n--PROC--\nGPU-a, 1, [N/A]\n--CGROUP--\nPIDMAP 1 alice job_7 test-lab\n'
        output = io.StringIO()
        with patch('sys.argv', ['sample_gpu.py', T0, 'gpu01', 'anon_users', 'salt']), \
             patch('sys.stdin', io.StringIO(sample)), patch('sys.stdout', output):
            sample_gpu.main()
        self.assertEqual(json.loads(output.getvalue())['job'], 'job_7')

    def test_legacy_multi_gpu_process_is_not_guessed_by_memory(self):
        sample = '--GPU--\n0, 80, 0, 100, 1000\n1, 80, 0, 200, 1000\n--PROC--\n1, 100\n--CGROUP--\nPIDMAP 1 alice job_7 test-lab\n'
        output = io.StringIO()
        with patch('sys.argv', ['sample_gpu.py', T0, 'gpu01', 'named', 'salt']), \
             patch('sys.stdin', io.StringIO(sample)), patch('sys.stdout', output):
            sample_gpu.main()
        self.assertTrue(all(json.loads(line)['job'] is None for line in output.getvalue().splitlines()))


if __name__ == '__main__':
    unittest.main()
