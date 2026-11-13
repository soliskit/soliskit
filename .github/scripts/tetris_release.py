"""Proposed receiver. Data validation only until explicitly invoked by its workflow."""

import hashlib
import json
import os
import pathlib
import re
import stat
import urllib.request
import zipfile

API = "https://api.github.com"
TETRIS = "soliskit/tetris-js"
SITE = "soliskit/soliskit.github.io"
FILES = {
    "index.html",
    "sw.js",
    "manifest.webmanifest",
    "icons/icon.svg",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/apple-touch-icon.png",
    "tetris_preview.png",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def revision(value):
    require(bool(re.fullmatch("[0-9a-f]{40}", value)), "invalid revision")
    return value


def run_number(value):
    require(bool(re.fullmatch("[1-9][0-9]*", str(value))), "invalid run number")
    return str(value)


def api(route):
    require(route.startswith("/repos/"), "invalid API route")
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(API + route, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    require(len(raw) <= 2 * 1024 * 1024, "oversized API response")
    return json.loads(raw)


def validate_tetris_run(run, jobs, source, number):
    require(str(run["id"]) == number, "run number mismatch")
    require(run["repository"]["full_name"] == TETRIS, "wrong repository")
    require(run["head_repository"]["full_name"] == TETRIS, "wrong head repository")
    require(run["event"] == "push", "not a main push")
    require(run["head_branch"] == "main", "not main")
    require(run["head_sha"] == source, "wrong source revision")
    require(run["path"] == ".github/workflows/pages.yml", "wrong workflow")
    require(run["status"] == "completed", "run not complete")
    require(run["conclusion"] == "success", "run not successful")
    require(run["run_attempt"] == 1, "rerun not accepted")
    for name in ("test", "Suites ran"):
        matches = [job for job in jobs if job["name"] == name]
        require(len(matches) == 1, "required gate missing or ambiguous")
        require(matches[0]["conclusion"] == "success", "required gate failed")


def trusted_tetris(source, number):
    source = revision(source)
    number = run_number(number)
    route = f"/repos/{TETRIS}/actions/runs/{number}"
    run = api(route)
    listing = api(route + "/jobs?per_page=100&filter=latest")
    require(listing["total_count"] <= 100, "job list exceeds review envelope")
    validate_tetris_run(run, listing["jobs"], source, number)
    return run


def output(values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as stream:
        for key, value in values.items():
            require("\n" not in str(value), "unsafe workflow output")
            stream.write(f"{key}={value}\n")


def resolve():
    source = os.environ.get("REQUEST_SOURCE", "")
    number = os.environ.get("REQUEST_RUN", "")
    if not source and not number:
        runs = api(
            f"/repos/{TETRIS}/actions/workflows/pages.yml/runs?event=push&branch=main&status=success&per_page=1"
        )
        require(len(runs["workflow_runs"]) == 1, "no successful main run")
        source = runs["workflow_runs"][0]["head_sha"]
        number = str(runs["workflow_runs"][0]["id"])
    run = trusted_tetris(source, number)
    output({"source": source, "tetris_run": number})
    pathlib.Path("tetris-request.json").write_text(
        json.dumps({"source": source, "tetrisRun": number, "runUrl": run["html_url"]})
        + "\n"
    )


def package():
    root = pathlib.Path("tetris-source")
    evidence = pathlib.Path(os.environ["QUALIFICATION_EVIDENCE"])
    require(
        not (evidence / "QUALIFICATION_INVALIDATED.json").exists(),
        "qualification invalidated",
    )
    native = json.loads((evidence / "supervisor.json").read_text())
    require(
        native["verdict"]
        == "NATIVE_SOURCE_AND_BROWSER_RECEIPTS_ONLY_PENDING_RECONSTRUCTION_AND_PIXELS",
        "native qualification incomplete",
    )
    require(not native["errors"], "native qualification errors")
    require(native["sourceMode"] == "main", "not main qualification")
    require(native["hostRepository"] == SITE, "wrong qualification host")
    require(native["hostHead"] == os.environ["GITHUB_SHA"], "host revision changed")
    require(str(native["run"]) == os.environ["GITHUB_RUN_ID"], "host run changed")
    reports = json.loads((evidence / "validated-browser-receipts.json").read_text())
    require(
        reports["suites"]
        == {
            "source": {
                "planned": 450,
                "passed": 419,
                "expectedFailed": 1,
                "expected": 420,
                "skipped": 30,
            },
            "delivery": {
                "planned": 42,
                "passed": 42,
                "expectedFailed": 0,
                "expected": 42,
                "skipped": 0,
            },
        },
        "browser census mismatch",
    )
    require(len(reports["screenshots"]) == 12, "screenshot census mismatch")
    before = json.loads((evidence / "before-browser-product-binding.json").read_text())
    after = json.loads((evidence / "after-browser-product-binding.json").read_text())
    require(before == after, "built files changed while tested")
    actual = {}
    for file in (root / "dist").rglob("*"):
        require(not file.is_symlink(), "symlink output")
        if file.is_dir():
            continue
        require(file.is_file(), "nonregular output")
        actual[file.relative_to(root / "dist").as_posix()] = sha(file.read_bytes())
    require(set(actual) == FILES, "unexpected distribution inventory")
    require(actual == after["distOutputs"], "distribution differs from tested bytes")
    request = json.loads(pathlib.Path("tetris-request.json").read_text())
    require(native["head"] == request["source"], "tested source mismatch")
    target = pathlib.Path("qualified-tetris")
    target.mkdir()
    import shutil

    shutil.copytree(root / "dist", target / "dist")
    shutil.copytree(evidence / "delivery", target / "delivery-proof")
    manifest = {
        "schema": 1,
        "source": native["head"],
        "tetrisRun": request["tetrisRun"],
        "siteRun": os.environ["GITHUB_RUN_ID"],
        "siteHead": os.environ["GITHUB_SHA"],
        "siteRepository": SITE,
        "files": actual,
        "suites": reports["suites"],
        "screenshots": reports["screenshots"],
        "pixelInspection": "PENDING_EXTERNAL_REVIEW",
    }
    (target / "qualification.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in ("inputs.json", "release.json"):
        shutil.copyfile(root / ".release-evidence" / name, target / name)


def validate_site_run(run, number):
    require(str(run["id"]) == number, "site run mismatch")
    require(run["repository"]["full_name"] == SITE, "wrong site repository")
    require(run["head_repository"]["full_name"] == SITE, "wrong site head repository")
    require(run["path"] == ".github/workflows/pages.yml", "wrong site workflow")
    require(run["head_branch"] == "main", "site run not main")
    require(
        run["head_sha"] == os.environ["GITHUB_SHA"], "site source changed; requalify"
    )
    require(run["event"] == "workflow_dispatch", "not an explicit qualification")
    require(
        run["status"] == "completed" and run["conclusion"] == "success",
        "site qualification not successful",
    )
    require(run["run_attempt"] == 1, "site rerun not accepted")


def select_artifact():
    number = run_number(os.environ["SITE_QUALIFICATION_RUN"])
    run = api(f"/repos/{SITE}/actions/runs/{number}")
    validate_site_run(run, number)
    gates = api(f"/repos/{SITE}/actions/runs/{number}/jobs?per_page=100&filter=latest")
    require(gates["total_count"] <= 100, "site job envelope exceeded")
    for name in ("receiver-checks", "qualify"):
        matching = [job for job in gates["jobs"] if job["name"] == name]
        require(
            len(matching) == 1 and matching[0]["conclusion"] == "success",
            "site required gate missing or unsuccessful",
        )
    listing = api(f"/repos/{SITE}/actions/runs/{number}/artifacts?per_page=100")
    require(listing["total_count"] <= 100, "artifact census exceeds envelope")
    name = "qualified-tetris-" + number
    found = [item for item in listing["artifacts"] if item["name"] == name]
    require(
        len(found) == 1 and not found[0]["expired"],
        "artifact absent, expired or ambiguous",
    )
    item = found[0]
    require(
        bool(re.fullmatch("sha256:[0-9a-f]{64}", item["digest"] or "")),
        "missing platform digest",
    )
    output({"artifact": item["id"], "digest": item["digest"]})


def unpack():
    archive = pathlib.Path("artifact.zip")
    require(archive.stat().st_size <= 16 * 1024 * 1024, "archive over cap")
    require(
        "sha256:" + sha(archive.read_bytes()) == os.environ["ARTIFACT_DIGEST"],
        "platform digest mismatch",
    )
    root = pathlib.Path("accepted-tetris")
    root.mkdir()
    with zipfile.ZipFile(archive) as source:
        names = set()
        total = 0
        for entry in source.infolist():
            parts = pathlib.PurePosixPath(entry.filename).parts
            require(
                parts
                and not entry.filename.startswith("/")
                and not {".", ".."}.intersection(entry.filename.split("/"))
                and "\\" not in entry.filename,
                "unsafe archive path",
            )
            require(entry.filename not in names, "duplicate archive path")
            names.add(entry.filename)
            allowed = (
                entry.filename
                in {
                    "qualification.json",
                    "inputs.json",
                    "release.json",
                    "delivery-proof/report.json",
                }
                or entry.filename in {"dist/" + file for file in FILES}
                or bool(
                    re.fullmatch(
                        r"delivery-proof/[0-9a-f]{64}\.(png|bin)", entry.filename
                    )
                )
            )
            require(entry.is_dir() or allowed, "unexpected archive entry")
            require(not stat.S_ISLNK(entry.external_attr >> 16), "archive symlink")
            if entry.is_dir():
                continue
            total += entry.file_size
            require(
                entry.file_size <= 8 * 1024 * 1024
                and total <= 16 * 1024 * 1024
                and len(names) <= 512,
                "archive expansion cap exceeded",
            )
            file = root / entry.filename
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(source.read(entry))
    manifest = json.loads((root / "qualification.json").read_text())
    require(manifest["siteRepository"] == SITE, "wrong manifest host")
    require(manifest["siteHead"] == os.environ["GITHUB_SHA"], "wrong site source")
    require(
        manifest["siteRun"] == os.environ["SITE_QUALIFICATION_RUN"],
        "wrong qualified run",
    )
    require(set(manifest["files"]) == FILES, "unexpected file list")
    trusted_tetris(manifest["source"], manifest["tetrisRun"])
    require(
        api(f"/repos/{TETRIS}/commits/main")["sha"] == manifest["source"],
        "Tetris main moved; requalify",
    )
    actual = {
        p.relative_to(root / "dist").as_posix(): sha(p.read_bytes())
        for p in (root / "dist").rglob("*")
        if p.is_file()
    }
    require(actual == manifest["files"], "accepted files changed")
    require(
        os.environ["PIXELS_REVIEWED"] == os.environ["SITE_QUALIFICATION_RUN"],
        "pixel review acknowledgment must name this exact site run",
    )


def compose():
    import shutil

    root = pathlib.Path("accepted-tetris")
    manifest = json.loads((root / "qualification.json").read_text())
    require(
        api(f"/repos/{TETRIS}/commits/main")["sha"] == manifest["source"],
        "Tetris main moved before composition; requalify",
    )
    target = pathlib.Path("site/tetris")
    require(not target.exists(), "unexpected existing Tetris destination")
    shutil.copytree(root / "dist", target)
    actual = {
        p.relative_to(target).as_posix(): sha(p.read_bytes())
        for p in target.rglob("*")
        if p.is_file()
    }
    require(actual == manifest["files"], "site composition changed output bytes")


if __name__ == "__main__":
    import sys

    actions = {
        "resolve": resolve,
        "package": package,
        "select-artifact": select_artifact,
        "unpack": unpack,
        "compose": compose,
    }
    require(
        len(sys.argv) == 2 and sys.argv[1] in actions,
        "explicit receiver action required",
    )
    actions[sys.argv[1]]()
