# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from datetime import datetime

from scheduled_refresh import SCHEDULED_JOBS, default_state, due_jobs, job_key


class ScheduledRefreshTest(unittest.TestCase):
    def test_schedule_includes_close_refresh_at_1500(self):
        schedule_times = [job["time"] for job in SCHEDULED_JOBS]

        self.assertEqual(schedule_times, ["09:25", "09:39", "14:00", "14:30", "15:00"])

    def test_schedule_refreshes_opening_levels(self):
        for job in SCHEDULED_JOBS:
            self.assertIn("opening-levels", job["commands"])

    def test_due_jobs_runs_missed_jobs_once_per_day(self):
        state = default_state()
        current = datetime(2026, 8, 25, 14, 1)

        jobs = due_jobs(state, current)

        self.assertEqual([job["time"] for job in jobs], ["09:25", "09:39", "14:00"])

        state["last_runs"][job_key(jobs[0])] = "2026-08-25"
        jobs_after_first_run = due_jobs(state, current)

        self.assertEqual([job["time"] for job in jobs_after_first_run], ["09:39", "14:00"])

    def test_auction_job_is_due_after_0925(self):
        state = default_state()
        current = datetime(2026, 8, 25, 9, 26)

        jobs = due_jobs(state, current)

        self.assertEqual([job["time"] for job in jobs], ["09:25"])

    def test_due_jobs_skips_weekend(self):
        state = default_state()
        saturday = datetime(2026, 8, 29, 15, 30)

        self.assertEqual(due_jobs(state, saturday), [])


if __name__ == "__main__":
    unittest.main()
