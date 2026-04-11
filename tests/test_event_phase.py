"""Tests for services.event_phase — event lifecycle phase detection."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.event_phase import (
    EventPhase,
    EVENT_DURATION,
    get_event_phase,
    get_phase_ttl,
    should_block_request,
    is_event_expired,
    _parse_event_date,
    _MSK,
)


class TestParseEventDate(unittest.TestCase):

    def test_dd_mm_yy(self):
        dt = _parse_event_date("11.04.26")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.day, 11)
        self.assertEqual(dt.month, 4)

    def test_yyyy_mm_dd(self):
        dt = _parse_event_date("2026-04-11")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)

    def test_dd_mm_yyyy(self):
        dt = _parse_event_date("11.04.2026")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.month, 4)

    def test_empty_string(self):
        self.assertIsNone(_parse_event_date(""))

    def test_not_specified(self):
        self.assertIsNone(_parse_event_date("не указана"))

    def test_unparseable(self):
        self.assertIsNone(_parse_event_date("garbage text"))


class TestGetEventPhase(unittest.TestCase):

    def _mock_now(self, offset: timedelta):
        """Return a datetime relative to a fixed event start (2026-04-15 18:00 MSK)."""
        event_start = datetime(2026, 4, 15, 18, 0, 0, tzinfo=_MSK)
        return event_start + offset

    @patch("services.event_phase.datetime")
    def test_early_phase(self, mock_dt):
        # 2 days before event
        mock_dt.now.return_value = self._mock_now(-timedelta(days=2))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "football")
        self.assertEqual(phase, EventPhase.EARLY)

    @patch("services.event_phase.datetime")
    def test_pre_match_phase(self, mock_dt):
        # 6 hours before event
        mock_dt.now.return_value = self._mock_now(-timedelta(hours=6))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "football")
        self.assertEqual(phase, EventPhase.PRE_MATCH)

    @patch("services.event_phase.datetime")
    def test_live_phase(self, mock_dt):
        # 1 hour into event (football = 2h duration)
        mock_dt.now.return_value = self._mock_now(timedelta(hours=1))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "football")
        self.assertEqual(phase, EventPhase.LIVE)

    @patch("services.event_phase.datetime")
    def test_finished_phase(self, mock_dt):
        # 5 hours after start (football 2h + 3h after end = within 24h)
        mock_dt.now.return_value = self._mock_now(timedelta(hours=5))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "football")
        self.assertEqual(phase, EventPhase.FINISHED)

    @patch("services.event_phase.datetime")
    def test_expired_phase(self, mock_dt):
        # 48 hours after start (well past 24h after end)
        mock_dt.now.return_value = self._mock_now(timedelta(hours=48))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "football")
        self.assertEqual(phase, EventPhase.EXPIRED)

    def test_unparseable_date_returns_early(self):
        phase = get_event_phase("not a date", "football")
        self.assertEqual(phase, EventPhase.EARLY)

    def test_empty_date_returns_early(self):
        phase = get_event_phase("", "cs2")
        self.assertEqual(phase, EventPhase.EARLY)

    @patch("services.event_phase.datetime")
    def test_hockey_longer_duration(self, mock_dt):
        # 2.5h after start — hockey=3h so still LIVE
        mock_dt.now.return_value = self._mock_now(timedelta(hours=2, minutes=30))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "hockey")
        self.assertEqual(phase, EventPhase.LIVE)

    @patch("services.event_phase.datetime")
    def test_table_tennis_short_duration(self, mock_dt):
        # 1.5h after start — table_tennis=1h so FINISHED
        mock_dt.now.return_value = self._mock_now(timedelta(hours=1, minutes=30))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.2026", "table_tennis")
        self.assertEqual(phase, EventPhase.FINISHED)

    @patch("services.event_phase.datetime")
    def test_dd_mm_yy_format(self, mock_dt):
        mock_dt.now.return_value = self._mock_now(-timedelta(days=2))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("15.04.26", "football")
        self.assertEqual(phase, EventPhase.EARLY)

    @patch("services.event_phase.datetime")
    def test_yyyy_mm_dd_format(self, mock_dt):
        mock_dt.now.return_value = self._mock_now(-timedelta(days=2))
        mock_dt.strptime = datetime.strptime
        phase = get_event_phase("2026-04-15", "football")
        self.assertEqual(phase, EventPhase.EARLY)


class TestGetPhaseTTL(unittest.TestCase):

    def test_early_ttl(self):
        self.assertEqual(get_phase_ttl(EventPhase.EARLY), timedelta(days=7))

    def test_pre_match_ttl(self):
        self.assertEqual(get_phase_ttl(EventPhase.PRE_MATCH), timedelta(hours=2))

    def test_live_ttl(self):
        self.assertEqual(get_phase_ttl(EventPhase.LIVE), timedelta(0))

    def test_finished_ttl(self):
        self.assertEqual(get_phase_ttl(EventPhase.FINISHED), timedelta(hours=48))

    def test_expired_ttl(self):
        self.assertEqual(get_phase_ttl(EventPhase.EXPIRED), timedelta(0))


class TestShouldBlockRequest(unittest.TestCase):

    def test_early_not_blocked(self):
        self.assertFalse(should_block_request(EventPhase.EARLY))

    def test_pre_match_not_blocked(self):
        self.assertFalse(should_block_request(EventPhase.PRE_MATCH))

    def test_live_not_blocked(self):
        self.assertFalse(should_block_request(EventPhase.LIVE))

    def test_finished_not_blocked(self):
        self.assertFalse(should_block_request(EventPhase.FINISHED))

    def test_expired_blocked(self):
        self.assertTrue(should_block_request(EventPhase.EXPIRED))


class TestIsEventExpired(unittest.TestCase):

    def test_only_expired_is_true(self):
        self.assertTrue(is_event_expired(EventPhase.EXPIRED))

    def test_finished_is_false(self):
        self.assertFalse(is_event_expired(EventPhase.FINISHED))

    def test_live_is_false(self):
        self.assertFalse(is_event_expired(EventPhase.LIVE))


class TestEventDuration(unittest.TestCase):

    def test_all_disciplines_have_positive_duration(self):
        for disc, dur in EVENT_DURATION.items():
            self.assertGreater(dur.total_seconds(), 0, f"{disc} duration must be positive")

    def test_known_disciplines_present(self):
        expected = {"football", "hockey", "basketball", "tennis", "cs2", "mma", "boxing"}
        self.assertTrue(expected.issubset(EVENT_DURATION.keys()))


if __name__ == "__main__":
    unittest.main()
