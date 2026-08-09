import unittest
from datetime import datetime, timezone

from gil_intelligence.probes.http import JsonHttpClient, parse_retry_after


class RetryAfterTests(unittest.TestCase):
    def test_numeric_retry_after(self) -> None:
        self.assertEqual(parse_retry_after("3"), 3.0)

    def test_http_date_retry_after(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_retry_after("Sun, 09 Aug 2026 12:00:05 GMT", now=now), 5.0)

    def test_invalid_retry_after(self) -> None:
        self.assertIsNone(parse_retry_after("not-a-date"))


class ClientValidationTests(unittest.TestCase):
    def test_rps_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            JsonHttpClient("https://example.test", requests_per_second=0)

    def test_throttle_enforces_configured_interval(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        client = JsonHttpClient(
            "https://example.test",
            requests_per_second=2,
            monotonic=monotonic,
            sleep=sleep,
        )
        client._throttle()
        client._throttle()

        self.assertEqual(sleeps, [0.5])
        self.assertEqual(client.request_attempt_count, 0)


if __name__ == "__main__":
    unittest.main()
