from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from morning.models import ShiftIdentity, ShiftPolicy
from morning.shift import ShiftError, anchor_time_to_shift, reporting_window, resolve_shift, shift_window

TZ = "Africa/Johannesburg"
ZONE = ZoneInfo(TZ)


def _policy(morning: str = "06:00", afternoon: str = "14:00", night: str = "22:00") -> ShiftPolicy:
    return ShiftPolicy(
        timezone=TZ,
        morning_shift_start=morning,
        afternoon_shift_start=afternoon,
        night_shift_start=night,
        updated_at="now",
    )


class ShiftResolutionTests(unittest.TestCase):
    def test_mid_morning_is_morning_shift(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 10, 10, 0, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("morning", "2026-09-10"))

    def test_mid_afternoon_is_afternoon_shift(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 10, 18, 0, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("afternoon", "2026-09-10"))

    def test_late_evening_night_shift_reports_as_following_day(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 10, 23, 0, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("night", "2026-09-11"))

    def test_after_midnight_keeps_the_day_it_finishes(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 11, 0, 30, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("night", "2026-09-11"))

    def test_sunday_night_counts_for_monday(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 13, 22, 0, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("night", "2026-09-14"))

    def test_exact_boundaries_select_the_new_shift_and_correct_reporting_date(self) -> None:
        cases = [
            (datetime(2026, 9, 10, 6, 0, tzinfo=ZONE), "morning", "2026-09-10"),
            (datetime(2026, 9, 10, 14, 0, tzinfo=ZONE), "afternoon", "2026-09-10"),
            (datetime(2026, 9, 10, 22, 0, tzinfo=ZONE), "night", "2026-09-11"),
        ]
        for moment, expected_kind, expected_date in cases:
            identity = resolve_shift(_policy(), at=moment)
            self.assertEqual((identity.shift_kind, identity.shift_date), (expected_kind, expected_date))

    def test_just_before_morning_start_is_same_reporting_day_night(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 11, 5, 59, tzinfo=ZONE))
        self.assertEqual((identity.shift_kind, identity.shift_date), ("night", "2026-09-11"))

    def test_naive_datetime_is_policy_local(self) -> None:
        identity = resolve_shift(_policy(), at=datetime(2026, 9, 10, 15, 0))
        self.assertEqual(identity.shift_kind, "afternoon")

    def test_unknown_timezone_is_rejected(self) -> None:
        with self.assertRaises(ShiftError):
            resolve_shift(
                ShiftPolicy("Not/AZone", "06:00", "14:00", "22:00"),
                at=datetime(2026, 9, 10, 10, 0),
            )

    def test_duplicate_or_unordered_boundaries_are_rejected(self) -> None:
        for policy in (_policy(afternoon="06:00"), _policy(morning="14:00", afternoon="06:00")):
            with self.assertRaises(ShiftError):
                resolve_shift(policy, at=datetime(2026, 9, 10, 10, 0, tzinfo=ZONE))

    def test_shift_windows_round_trip(self) -> None:
        policy = _policy()
        moments = (
            datetime(2026, 9, 10, 6, 0, tzinfo=ZONE),
            datetime(2026, 9, 10, 13, 59, tzinfo=ZONE),
            datetime(2026, 9, 10, 14, 0, tzinfo=ZONE),
            datetime(2026, 9, 10, 21, 59, tzinfo=ZONE),
            datetime(2026, 9, 10, 22, 0, tzinfo=ZONE),
            datetime(2026, 9, 11, 5, 59, tzinfo=ZONE),
        )
        for moment in moments:
            identity = resolve_shift(policy, at=moment)
            start, end = shift_window(policy, identity)
            self.assertTrue(start <= moment < end)

    def test_reporting_window_runs_from_prior_night_start_to_current_night_start(self) -> None:
        start, end = reporting_window(_policy(), "2026-09-10")
        self.assertEqual(start, datetime(2026, 9, 9, 22, 0, tzinfo=ZONE))
        self.assertEqual(end, datetime(2026, 9, 10, 22, 0, tzinfo=ZONE))


class AnchorTimeToShiftTests(unittest.TestCase):
    def test_night_shift_times_anchor_across_midnight(self) -> None:
        identity = ShiftIdentity("2026-09-11", "night")
        first = anchor_time_to_shift(_policy(), identity, "22:15")
        second = anchor_time_to_shift(_policy(), identity, "00:15")
        third = anchor_time_to_shift(_policy(), identity, "05:30")
        self.assertEqual(first, datetime(2026, 9, 10, 22, 15, tzinfo=ZONE))
        self.assertEqual(second, datetime(2026, 9, 11, 0, 15, tzinfo=ZONE))
        self.assertEqual(third, datetime(2026, 9, 11, 5, 30, tzinfo=ZONE))
        self.assertLess(first, second)
        self.assertLess(second, third)

    def test_morning_and_afternoon_do_not_wrap(self) -> None:
        morning = anchor_time_to_shift(_policy(), ShiftIdentity("2026-09-10", "morning"), "08:00")
        afternoon = anchor_time_to_shift(_policy(), ShiftIdentity("2026-09-10", "afternoon"), "18:00")
        self.assertEqual(morning.date().isoformat(), "2026-09-10")
        self.assertEqual(afternoon.date().isoformat(), "2026-09-10")


if __name__ == "__main__":
    unittest.main()
