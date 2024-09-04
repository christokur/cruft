#!/usr/bin/env python3
"""Jira components and versions."""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import pathlib
import sys
from pprint import pprint

import packaging.version
import requests
from requests.auth import HTTPBasicAuth
from toolbag.datastructures import jsonify
from toolbag.utils.helpers import to_boolean

INTERACTIVE = to_boolean(os.getenv("INTERACTIVE", "no"))
DEBUG = to_boolean(os.getenv("DEBUG", "no"))
VERBOSE = to_boolean(os.getenv("VERBOSE", "no"))


# --- functions --------------------------------------------------------------
def call_jira(
    api: str,
    username: str | None = None,
    password: str | None = None,
    method: str = "GET",
    data: str | None = None,
    raw: bool = False,
    exit_on_error: bool = True,
) -> dict | str | None:
    """Call Jira API."""
    username = username or os.getenv("JIRA_USERNAME", None)
    password = password or os.getenv("JIRA_API_KEY", None)
    instance_url = os.getenv("JIRA_INSTANCE_URL", "https://sandsb2b.atlassian.net")
    api_path = os.getenv("JIRA_API_PATH", "/rest/api/3")
    url = f"{instance_url}{api_path}{api}"
    auth = HTTPBasicAuth(username, password)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    response = requests.request(
        method,
        url,
        headers=headers,
        auth=auth,
        data=data,
        timeout=10,
    )
    if not raw:
        payload = response.text
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(response.text)
    else:
        payload = response
    if exit_on_error and not response.ok:
        print(f"Error: {response.status_code} - {response.reason}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)
        print(f"Method: {method}", file=sys.stderr)
        print(f"Data: {data}", file=sys.stderr)
        print(f"Response: {payload}", file=sys.stderr)
        err_exit(payload)
    return payload


def display(heading: str, obj: object) -> None:
    """Display object."""
    log(f"display({heading})", stacklevel=3)
    width = 80
    print(f"===[ {heading} ]{'=' * (width - len(heading) - 7)}")
    print(obj) if isinstance(obj, str) else pprint(obj, width=width)
    print(f"{'-' * width}")


def get_repo_name() -> tuple[str, str] | tuple[None, None]:
    """Get repository name."""
    # org = None
    repo = None
    org_repo = os.getenv("GITHUB_REPOSITORY", pathlib.Path.cwd().name)
    if org_repo:
        parts = org_repo.split("/")
        repo = parts[0]
        if len(parts) > 1:
            # org = parts[0]
            repo = parts[1]
    return org_repo, repo


def log(
    msg: str,
    level: str = "INFO",
    stacklevel: int = 2,
) -> None:
    """Log message."""
    from toolbag.utils.logging import LOGGER

    getattr(LOGGER, level.lower())(msg, stacklevel=stacklevel)


def err_exit(msg: str) -> None:
    """Exit with error message."""
    log(str(msg), level="ERROR", stacklevel=3)
    print(msg, file=sys.stderr) if isinstance(msg, str) else pprint(msg, stream=sys.stderr)
    sys.stderr.flush()
    # noinspection PyUnresolvedReferences
    frame = sys._getframe()
    sys.exit(frame.f_back.f_lineno % 255)


def check_component(
    project_key: str = "CITCI",
    username: str | None = None,
    password: str | None = None,
    user: dict | None = None,
) -> None:
    """Check component."""
    project_key = (
        project_key
        or os.getenv("JIRA_PROJECT_KEY", "CITCI")
        or (input("Enter your Jira project key: ") if INTERACTIVE else None)
    )
    components = call_jira(
        f"/project/{project_key}/components",
        username=username,
        password=password,
    )
    if not components:
        # noinspection PyUnresolvedReferences
        err_exit(f"No components found in '{project_key}'\n")
        return
    # noinspection PyTypeChecker
    cmp_map = {component["name"]: component for component in components}
    org_repo, repo = get_repo_name()
    if not repo:
        # noinspection PyUnresolvedReferences
        err_exit("No repository provided\n")
        display("Components", cmp_map) if DEBUG else None
    else:
        if not (cmp := cmp_map.get(repo, None)):
            print(f"Repository '{repo}' is not yet a component.\n")
            display(repo, {})
            user = user or call_jira("/myself", username=username, password=password)
            cmp = call_jira(
                "/component",
                username=username,
                password=password,
                method="POST",
                data=jsonify(
                    {
                        "assigneeType": "COMPONENT_LEAD",
                        "description": org_repo,
                        "isAssigneeTypeValid": True,
                        "leadAccountId": user["accountId"],
                        "name": repo,
                        "project": project_key,
                    },
                ),
            )
        print(f"Repository '{repo}' is a component.\n")
        display(repo, jsonify(cmp))


def create_version(
    version: str,
    versions: dict | None = None,
    org_repo: str | None = None,
    repo: str | None = None,
    project_key: str = "CITCI",
    project: dict | None = None,
    username: str | None = None,
    password: str | None = None,
    release_it: bool = False,
) -> tuple[dict | None, str | None]:
    """Create version."""
    project_key = (
        project_key
        or os.getenv("JIRA_PROJECT_KEY", "CITCI")
        or (input("Enter your Jira project key: ") if INTERACTIVE else None)
    )
    if not (repo and org_repo):
        org_repo, repo = get_repo_name()
    # display(repo, {})
    version_name = f"{repo}={version}"
    vversion_name = f"{repo}=v{version}"
    if not versions:
        versions_l = call_jira(
            f"/project/{project_key}/versions",
            username=username,
            password=password,
        )
        if not versions_l:
            # noinspection PyUnresolvedReferences
            err_exit(f"No versions found in '{project_key}'\n")
            return None, None
        # noinspection PyTypeChecker
        versions = {version["name"]: version for version in versions_l if version["name"].startswith(repo)}

    if not (ver := versions.get(version_name, None)) and (ver := versions.get(vversion_name, None)):
        version_name = vversion_name
    if not ver:
        print(f"Repository '{repo}' does not yet have version '{version_name}'.\n")
        project = project or call_jira(f"/project/{project_key}", username=username, password=password)
        data = {
            "archived": False,
            "description": f"{org_repo} v{version}",
            "name": version_name,
            "projectId": project["id"],
            "released": release_it,
        }
        ts = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if release_it:
            data["releaseDate"] = ts
        else:
            data["startDate"] = ts

        ver = call_jira(
            "/version",
            username=username,
            password=password,
            method="POST",
            data=jsonify(data),
        )
    return ver, version_name


def check_version(
    project_key: str = "CITCI",
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Check version."""
    project_key = (
        project_key
        or os.getenv("JIRA_PROJECT_KEY", "CITCI")
        or (input("Enter your Jira project key: ") if INTERACTIVE else None)
    )
    org_repo, repo = get_repo_name()
    if not repo:
        versions = call_jira(
            f"/project/{project_key}/versions",
            username=username,
            password=password,
        )
        if not versions:
            # noinspection PyUnresolvedReferences
            err_exit(f"No versions found in '{project_key}'\n")
            return
        # noinspection PyUnresolvedReferences
        err_exit("No repository provided\n")
        display("Versions", versions) if DEBUG else None
    else:
        workspace = pathlib.Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve().absolute()
        version_file = workspace / "VERSION"
        if not version_file.exists():
            # noinspection PyUnresolvedReferences
            err_exit(f"Version file '{version_file}' not found\n")
        version = (workspace / "VERSION").read_text().strip()

        ver, version_name = create_version(
            org_repo=org_repo,
            password=password,
            project_key=project_key,
            repo=repo,
            username=username,
            version=version,
            versions=None,
        )
        print(f"Repository '{repo}' has version '{version_name}'.\n")
        display(version_name, jsonify(ver))

        ver = packaging.version.parse(version)
        ver = packaging.version.Version(f"{ver.major}.{ver.minor}.{ver.micro+1}")
        ver, version_name = create_version(
            org_repo=org_repo,
            password=password,
            project_key=project_key,
            repo=repo,
            username=username,
            version=ver.public,
            versions=None,
        )
        print(f"Repository '{repo}' has version '{version_name}'.\n")
        display(version_name, jsonify(ver))


# --- main -------------------------------------------------------------------
def main() -> None:
    """Run."""
    try:
        from toolbag.utils.logging import setup_default_logger

        level = "WARNING"
        if VERBOSE:
            level = "INFO"
        if DEBUG:
            level = "DEBUG"
        setup_default_logger(level=level, debug=DEBUG, name=pathlib.Path(__file__).stem)
        # Some Authentication Methods
        username = os.getenv("JIRA_USERNAME", None) or (input("Enter your Jira username: ") if INTERACTIVE else None)
        password = os.getenv("JIRA_API_KEY", None) or (input("Enter your Jira API key: ") if INTERACTIVE else None)
        project_key = os.getenv("JIRA_PROJECT_KEY", "CITCI") or (
            input("Enter your Jira project key: ") if INTERACTIVE else None
        )

        attempts = int(os.getenv("ATTEMPTS", "3"))
        attempt = 1
        try:
            log("User")
            # Who has authenticated
            user = call_jira("/myself", username=username, password=password)
            display("User", user) if DEBUG else None

            log("check_component")
            check_component(user=user, project_key=project_key, username=username, password=password)

            log("check_version")
            check_version(project_key=project_key, username=username, password=password)
        except Exception as exc:
            if attempt > attempts:
                raise exc
            attempt += 1
            display(f"Exception on attempt {attempt}", str(exc))
    except Exception as exc:
        # TRACEBACK_PATTERN_MAIN
        # import os

        pytest = any(k for k, _ in os.environ.items() if k.startswith("PYTEST"))
        pycharm = any(k for k, _ in os.environ.items() if k.startswith("PYCHARM"))
        is_debug = not pytest and (pycharm or os.getenv("DEBUG") or "--debug" in sys.argv)
        if is_debug:  # pragma: no cover
            # import sys  # pragma: no cover
            import traceback  # pragma: no cover

            traceback.print_exception(exc.__class__, exc, exc.__traceback__, file=sys.stderr)  # pragma: no cover

        import contextlib

        with contextlib.suppress(Exception):
            from b2b_cli.handlers.b2b_jokes_handler import B2bJokesHandler

            if not getattr(B2bJokesHandler, "_telling", None):
                B2bJokesHandler.tell()
        sys.exit(310)


if __name__ == "__main__":
    main()
