"""Proposed receiver boundaries. Not executed during source preparation."""

import copy
import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch

PATH = pathlib.Path(__file__).parents[1] / "scripts/tetris_release.py"
SPEC = importlib.util.spec_from_file_location("receiver", PATH)
receiver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receiver)


def good_run():
    return {
        "id": 123,
        "repository": {"full_name": receiver.TETRIS},
        "head_repository": {"full_name": receiver.TETRIS},
        "event": "push",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "path": ".github/workflows/pages.yml",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }


def good_jobs():
    return [{"name": name, "conclusion": "success"} for name in ("test", "Suites ran")]


class ReceiverChecks(unittest.TestCase):
    def test_exact_successful_main_identity(self):
        receiver.validate_tetris_run(good_run(), good_jobs(), "a" * 40, "123")

    def test_wrong_repository_and_head_repository(self):
        for key in ("repository", "head_repository"):
            run = good_run()
            run[key] = {"full_name": "outside/repository"}
            with self.assertRaises(ValueError):
                receiver.validate_tetris_run(run, good_jobs(), "a" * 40, "123")

    def test_wrong_branch_event_source_workflow_and_attempt(self):
        for key, value in (
            ("head_branch", "feature"),
            ("event", "pull_request"),
            ("head_sha", "b" * 40),
            ("path", ".github/workflows/other.yml"),
            ("run_attempt", 2),
            ("id", 456),
            ("status", "in_progress"),
            ("conclusion", "failure"),
        ):
            run = good_run()
            run[key] = value
            with self.assertRaises(ValueError):
                receiver.validate_tetris_run(run, good_jobs(), "a" * 40, "123")

    def test_failed_skipped_missing_and_duplicate_gate(self):
        for conclusion in ("failure", "skipped", "cancelled", None):
            jobs = good_jobs()
            jobs[1]["conclusion"] = conclusion
            with self.assertRaises(ValueError):
                receiver.validate_tetris_run(good_run(), jobs, "a" * 40, "123")
        for jobs in (good_jobs()[:1], good_jobs() + good_jobs()):
            with self.assertRaises(ValueError):
                receiver.validate_tetris_run(good_run(), jobs, "a" * 40, "123")

    def test_parameter_syntax(self):
        for value in ("../main", "a" * 39, "A" * 40, "a" * 40 + "\n"):
            with self.assertRaises(ValueError):
                receiver.revision(value)
        for value in ("0", "-1", "123\n", "1; echo unsafe"):
            with self.assertRaises(ValueError):
                receiver.run_number(value)

    def test_site_run_is_exact_current_website_source(self):
        run = good_run()
        run.update(
            {
                "repository": {"full_name": receiver.SITE},
                "head_repository": {"full_name": receiver.SITE},
                "event": "workflow_dispatch",
            }
        )
        with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}):
            receiver.validate_site_run(run, "123")
            changed = copy.deepcopy(run)
            changed["head_sha"] = "b" * 40
            with self.assertRaises(ValueError):
                receiver.validate_site_run(changed, "123")

    def test_site_push_cannot_impersonate_inspected_qualification(self):
        run = good_run()
        run.update(
            {
                "repository": {"full_name": receiver.SITE},
                "head_repository": {"full_name": receiver.SITE},
            }
        )
        with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}):
            with self.assertRaises(ValueError):
                receiver.validate_site_run(run, "123")

    def test_missing_expired_ambiguous_or_undigested_artifact(self):
        site = good_run()
        site.update(
            {
                "repository": {"full_name": receiver.SITE},
                "head_repository": {"full_name": receiver.SITE},
                "event": "workflow_dispatch",
            }
        )
        artifact = {
            "id": 44,
            "name": "qualified-tetris-123",
            "expired": False,
            "digest": "sha256:" + "b" * 64,
        }
        cases = [
            [],
            [dict(artifact, expired=True)],
            [artifact, artifact],
            [dict(artifact, digest=None)],
        ]
        for artifacts in cases:
            responses = [
                site,
                {
                    "total_count": 2,
                    "jobs": [
                        {"name": name, "conclusion": "success"}
                        for name in ("receiver-checks", "qualify")
                    ],
                },
                {"total_count": len(artifacts), "artifacts": artifacts},
            ]
            with patch.dict(
                os.environ, {"GITHUB_SHA": "a" * 40, "SITE_QUALIFICATION_RUN": "123"}
            ):
                with patch.object(receiver, "api", side_effect=responses):
                    with self.assertRaises(ValueError):
                        receiver.select_artifact()

    def test_unsafe_or_unexpected_archive_path(self):
        import hashlib
        import tempfile
        import zipfile

        for name in ("../escape", "/absolute", "./relative", "dist/unknown.js"):
            with tempfile.TemporaryDirectory() as folder:
                old = os.getcwd()
                try:
                    os.chdir(folder)
                    with zipfile.ZipFile("artifact.zip", "w") as archive:
                        archive.writestr(name, b"unexpected")
                    digest = hashlib.sha256(
                        pathlib.Path("artifact.zip").read_bytes()
                    ).hexdigest()
                    with patch.dict(
                        os.environ, {"ARTIFACT_DIGEST": "sha256:" + digest}
                    ):
                        with self.assertRaises(ValueError):
                            receiver.unpack()
                finally:
                    os.chdir(old)

    def test_changed_archive_digest(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            old = os.getcwd()
            try:
                os.chdir(folder)
                pathlib.Path("artifact.zip").write_bytes(b"changed")
                with patch.dict(os.environ, {"ARTIFACT_DIGEST": "sha256:" + "0" * 64}):
                    with self.assertRaises(ValueError):
                        receiver.unpack()
            finally:
                os.chdir(old)

    def test_changed_distribution_and_missing_pixel_review(self):
        import hashlib
        import json
        import tempfile
        import zipfile

        for changed, reviewed in ((True, "123"), (False, "456")):
            with tempfile.TemporaryDirectory() as folder:
                old = os.getcwd()
                try:
                    os.chdir(folder)
                    files = {
                        name: hashlib.sha256(b"checked").hexdigest()
                        for name in receiver.FILES
                    }
                    manifest = {
                        "siteRepository": receiver.SITE,
                        "siteHead": "a" * 40,
                        "siteRun": "123",
                        "source": "b" * 40,
                        "tetrisRun": "999",
                        "files": files,
                    }
                    with zipfile.ZipFile("artifact.zip", "w") as archive:
                        archive.writestr("qualification.json", json.dumps(manifest))
                        for name in receiver.FILES:
                            archive.writestr(
                                "dist/" + name,
                                b"changed"
                                if changed and name == "index.html"
                                else b"checked",
                            )
                    digest = hashlib.sha256(
                        pathlib.Path("artifact.zip").read_bytes()
                    ).hexdigest()
                    with patch.dict(
                        os.environ,
                        {
                            "ARTIFACT_DIGEST": "sha256:" + digest,
                            "GITHUB_SHA": "a" * 40,
                            "SITE_QUALIFICATION_RUN": "123",
                            "PIXELS_REVIEWED": reviewed,
                        },
                    ):
                        with (
                            patch.object(receiver, "trusted_tetris"),
                            patch.object(
                                receiver, "api", return_value={"sha": "b" * 40}
                            ),
                        ):
                            with self.assertRaises(ValueError):
                                receiver.unpack()
                finally:
                    os.chdir(old)

    def test_existing_destination_cannot_be_silently_overwritten(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            old = os.getcwd()
            try:
                os.chdir(folder)
                pathlib.Path("accepted-tetris").mkdir()
                pathlib.Path("accepted-tetris/qualification.json").write_text(
                    json.dumps({"files": {}, "source": "b" * 40})
                )
                pathlib.Path("site/tetris").mkdir(parents=True)
                with patch.object(receiver, "api", return_value={"sha": "b" * 40}):
                    with self.assertRaises(ValueError):
                        receiver.compose()
            finally:
                os.chdir(old)

    def test_tetris_main_moved_before_composition(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            old = os.getcwd()
            try:
                os.chdir(folder)
                pathlib.Path("accepted-tetris").mkdir()
                pathlib.Path("accepted-tetris/qualification.json").write_text(
                    json.dumps({"files": {}, "source": "b" * 40})
                )
                with patch.object(receiver, "api", return_value={"sha": "c" * 40}):
                    with self.assertRaises(ValueError):
                        receiver.compose()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
