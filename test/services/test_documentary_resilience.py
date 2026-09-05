import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.documentary import images, pipeline, research


class TestBoundedSourceCollection(unittest.TestCase):
    """A slow network must not turn research into an open-ended stall."""

    def _candidates(self, count: int) -> list[dict]:
        return [
            {"url": f"https://example.com/{i}", "title": "", "position": i}
            for i in range(count)
        ]

    def test_stops_after_the_attempt_cap(self):
        stats: dict = {}
        with (
            patch.object(
                research, "gather_candidates", return_value=self._candidates(140)
            ),
            patch.object(research, "fetch_source", return_value=None) as fetch,
            patch.object(research.logger, "warning"),
        ):
            sources = research.collect_sources(["q"], stats=stats)

        self.assertEqual(sources, [])
        self.assertEqual(fetch.call_count, research.MAX_FETCH_ATTEMPTS)
        self.assertEqual(stats["fetch_attempts"], research.MAX_FETCH_ATTEMPTS)

    def test_stops_when_the_time_budget_is_spent(self):
        # Deadline is set from the first reading; the next one is already past it.
        clock = iter([0.0, 1e6])
        with (
            patch.object(
                research, "gather_candidates", return_value=self._candidates(140)
            ),
            patch.object(research, "fetch_source", return_value=None) as fetch,
            patch.object(research.time, "monotonic", lambda: next(clock)),
            patch.object(research.logger, "warning"),
        ):
            research.collect_sources(["q"])

        self.assertEqual(fetch.call_count, 0)

    def test_collects_until_max_sources(self):
        source = {"url": "u", "title": "t", "domain": "d", "text": "x" * 400}
        with (
            patch.object(
                research, "gather_candidates", return_value=self._candidates(140)
            ),
            patch.object(research, "fetch_source", return_value=source),
        ):
            sources = research.collect_sources(["q"])

        self.assertEqual(len(sources), research.MAX_SOURCES)


class TestDroppedSearchReporting(unittest.TestCase):
    def test_failed_searches_are_counted_and_warned_about(self):
        stats: dict = {}
        with (
            patch.object(
                research.requests, "get", side_effect=OSError("read timed out")
            ),
            patch.object(research.logger, "warning"),
        ):
            results = research._serpapi_search("q", "google", stats)

        self.assertEqual(results, [])
        self.assertEqual(stats["searches_failed"], 1)

        warnings = research._research_warnings(
            {"searches": 14, "searches_failed": 7}, []
        )
        self.assertTrue(any("7 of 14" in w for w in warnings))

    def test_a_clean_run_reports_no_warnings(self):
        sources = [{}] * research.MAX_SOURCES
        stats = {"searches": 14, "searches_failed": 0, "fetch_attempts": 9}
        self.assertEqual(research._research_warnings(stats, sources), [])


class TestProviderCircuitBreaker(unittest.TestCase):
    """A provider that keeps timing out gets dropped, not retried per cue."""

    def setUp(self):
        images.reset_provider_health()

    def tearDown(self):
        images.reset_provider_health()

    def test_provider_is_dropped_after_repeated_failures(self):
        with patch.object(images.logger, "warning"):
            for _ in range(images.PROVIDER_FAILURE_LIMIT):
                self.assertTrue(images._provider_enabled("openverse"))
                images._note_provider_failure("openverse")
        self.assertFalse(images._provider_enabled("openverse"))

    def test_a_success_clears_the_failure_streak(self):
        with patch.object(images.logger, "warning"):
            images._note_provider_failure("openverse")
            images._note_provider_failure("openverse")
        images._note_provider_success("openverse")
        self.assertEqual(images._provider_failures.get("openverse", 0), 0)

    def test_disabled_providers_are_not_searched(self):
        with patch.object(images.logger, "warning"):
            for _ in range(images.PROVIDER_FAILURE_LIMIT):
                images._note_provider_failure("openverse")
        with (
            patch.object(images, "search_wikimedia", return_value=[]) as wikimedia,
            patch.object(images, "search_openverse", return_value=[]) as openverse,
            patch.object(images, "search_pexels_photos", return_value=[]),
            patch.object(images, "search_pixabay_photos", return_value=[]),
        ):
            images.gather_candidates_for_cue(
                "pid", "s0p0", {"archival": "a", "stock": "s"}
            )

        wikimedia.assert_called_once()
        openverse.assert_not_called()


class TestOpenverseAuth(unittest.TestCase):
    def setUp(self):
        images._openverse_token = ("", 0.0)

    def tearDown(self):
        images._openverse_token = ("", 0.0)

    def test_no_credentials_means_anonymous_requests(self):
        with patch.dict(images.config.documentary, {}, clear=True):
            self.assertEqual(images._openverse_headers(), {})

    def test_token_is_fetched_once_and_reused(self):
        response = subprocess.CompletedProcess(args=[], returncode=0)
        response.raise_for_status = lambda: None
        response.json = lambda: {"access_token": "tok", "expires_in": 43200}
        credentials = {
            "openverse_client_id": "id",
            "openverse_client_secret": "secret",
        }
        with (
            patch.dict(images.config.documentary, credentials),
            patch.object(images.requests, "post", return_value=response) as post,
        ):
            first = images._openverse_headers()
            second = images._openverse_headers()

        self.assertEqual(first, {"Authorization": "Bearer tok"})
        self.assertEqual(second, first)
        post.assert_called_once()

    def test_expired_token_is_refetched(self):
        images._openverse_token = ("stale", time.time() - 1)
        response = subprocess.CompletedProcess(args=[], returncode=0)
        response.raise_for_status = lambda: None
        response.json = lambda: {"access_token": "fresh", "expires_in": 43200}
        credentials = {
            "openverse_client_id": "id",
            "openverse_client_secret": "secret",
        }
        with (
            patch.dict(images.config.documentary, credentials),
            patch.object(images.requests, "post", return_value=response),
        ):
            self.assertEqual(
                images._openverse_headers(), {"Authorization": "Bearer fresh"}
            )


class TestStageProgressReporting(unittest.TestCase):
    """Autopilot must report the stage it is in, not the one it started in."""

    def test_autopilot_reports_every_stage(self):
        project = {
            "project_id": "pid",
            "topic": "t",
            "auto_approve_factsheet": True,
            "auto_approve_script": True,
            "auto_approve_images": True,
        }
        seen: list[str] = []
        with (
            patch.object(pipeline.costs, "set_project"),
            patch.object(pipeline.store, "set_status"),
            patch.object(pipeline.store, "load_factsheet", return_value={"a": 1}),
            patch.object(pipeline.research, "run_research"),
            patch.object(pipeline.scriptwriter, "run_scriptwriting"),
            patch.object(pipeline.images, "run_image_sourcing"),
            patch.object(pipeline.render, "run_render"),
        ):
            pipeline.run_research_stage(project, seen.append)

        self.assertEqual(len(seen), 4)
        self.assertIn("Researching", seen[0])
        self.assertIn("script", seen[1])
        self.assertIn("Sourcing images", seen[2])
        self.assertIn("Rendering", seen[3])

    def test_a_broken_callback_does_not_break_the_run(self):
        def explode(_message: str) -> None:
            raise RuntimeError("UI is gone")

        with (
            patch.object(pipeline.costs, "set_project"),
            patch.object(pipeline.store, "set_status"),
            patch.object(pipeline.research, "run_research"),
            patch.object(pipeline.logger, "warning"),
        ):
            pipeline.run_research_stage({"project_id": "pid"}, explode)


if __name__ == "__main__":
    unittest.main()
