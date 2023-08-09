from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import git
import git.refs
from cookiecutter.config import get_user_config
from cookiecutter.generate import generate_context
from cookiecutter.prompt import prompt_for_config
from cookiecutter.replay import dump as save_replay
from cookiecutter.replay import load as load_replay
from git import GitCommandError, Repo
from packaging import version

from cruft.exceptions import (
    InvalidCookiecutterReplay,
    InvalidCookiecutterRepository,
    UnableToFindCookiecutterTemplate,
)

CookiecutterContext = Dict[str, Any]
LATEST = ":latest:"
BRANCH = "branch:"


#################################
# Cookiecutter helper functions #
#################################


def resolve_template_url(url: str) -> str:
    parsed_url = urlparse(url)
    # If we are given a file URI, we should convert
    # relative paths to absolute paths. This is to
    # make sure that further operations like check/update
    # work properly in case the generated project directory
    # does not reside in the same relative path.
    if not parsed_url.scheme or parsed_url.scheme == "file":
        file_path = (Path(parsed_url.netloc) / Path(parsed_url.path)).absolute()
        # Below is to handle cases like "git@github.com"
        # which passes through to this block, but will obviously not
        # exist in the file system.
        # In this case we simply return the URL. If the user did
        # pass in a valid file path that does not exist, we do not need to
        # worry as we will never to be able to use it in check/update etc. anyway
        if file_path.exists():
            return str(file_path)
    return url


def get_cookiecutter_repo(
    cruft_state: dict,
    cookiecutter_template_dir: Path,
    **clone_kwargs,
) -> Repo:
    template_git_url = cruft_state.get("template", None)
    checkout = cruft_state.get("checkout", None)
    try:
        repo = Repo.clone_from(template_git_url, cookiecutter_template_dir, **clone_kwargs)
    except GitCommandError as error:
        raise InvalidCookiecutterRepository(
            template_git_url, f"Failed to clone the repo. {error.stderr.strip()}"
        )
    if checkout is not None:
        ref = checkout
        if checkout in LATEST:
            refs = [
                ref for ref in repo.refs if isinstance(ref, git.refs.TagReference)  # type: ignore
            ]
            if not refs:
                ref = "HEAD"
            else:
                latest = version.parse("0.0.0")
                for ref in refs:
                    ver = version.parse(re.sub(r"[^0-9.]", "", ref.name))
                    if ver > latest:
                        latest = ver
                vers = str(latest)
                if "0.0.0" == vers:
                    ref = "HEAD"
                else:
                    ref_l = [ref.name for ref in refs if vers in ref.name]
                    assert ref_l, f"No tag found for version: {vers}"
                    ref = ref_l[0]
        elif BRANCH in checkout:
            ref = checkout.replace(BRANCH, "")
        checkout = ref
        cruft_state["checkout"] = checkout
        try:
            repo.git.checkout(ref)
        except GitCommandError as error:
            raise InvalidCookiecutterRepository(
                template_git_url,
                f"Failed to check out the reference {checkout}. {error.stderr.strip()}",
            )
    return repo


def _validate_cookiecutter(cookiecutter_template_dir: Path):
    main_cookiecutter_directory: Optional[Path] = None

    for dir_item in cookiecutter_template_dir.glob("*cookiecutter.*"):
        if dir_item.is_dir() and "{{" in dir_item.name and "}}" in dir_item.name:
            main_cookiecutter_directory = dir_item
            break

    if not main_cookiecutter_directory:
        raise UnableToFindCookiecutterTemplate(cookiecutter_template_dir)


def generate_cookiecutter_context(
    template_git_url: str,
    cookiecutter_template_dir: Path,
    config_file: Optional[Path] = None,
    default_config: bool = False,
    extra_context: Optional[Dict[str, Any]] = None,
    no_input: bool = False,
    replay_file: Optional[Path] = None,
) -> CookiecutterContext:
    _validate_cookiecutter(cookiecutter_template_dir)

    context_file = cookiecutter_template_dir / "cookiecutter.json"
    config_dict = get_user_config(
        config_file=str(config_file) if config_file else None, default_config=default_config
    )
    replay_dir = None
    if replay_file:
        if replay_file.exists():
            replay_dir = replay_file.parent
            replay_path = replay_file
            replay_file = Path(replay_file.name)
        else:
            replay_dir = Path(config_dict["replay_dir"])
            replay_path = replay_dir / replay_file
            if replay_path.exists():
                replay_dir, replay_file = replay_path.parent, Path(replay_path.name)
            else:
                raise InvalidCookiecutterReplay(str(replay_path), "No replay file found.")
        if replay_path.exists():
            try:
                replay_context = load_replay(replay_dir, replay_file)
            except (TypeError, ValueError) as error:
                raise InvalidCookiecutterReplay(
                    str(replay_dir / replay_file), f"Failed to load the replay file. {error}"
                ) from error
            if isinstance(extra_context, dict):
                extra_context.update(replay_context["cookiecutter"])
            else:
                extra_context = replay_context["cookiecutter"]
        else:
            raise InvalidCookiecutterReplay(str(replay_path), "No replay file found.")

    # Don't pass entries prefixed by "_" = cookiecutter extensions, not direct user intent
    jinja2_env_vars = {}
    user_context = {}
    if extra_context:
        for key, value in extra_context.items():
            if key.startswith("_"):
                jinja2_env_vars[key] = value
            else:
                user_context[key] = value
    context = generate_context(
        context_file=context_file,
        default_context=config_dict["default_context"],
        extra_context=user_context,
    )

    # prompt the user to manually configure at the command line.
    # except when 'no-input' flag is set
    context["cookiecutter"] = prompt_for_config(context, no_input)
    context["cookiecutter"]["_template"] = template_git_url
    context["cookiecutter"].update(jinja2_env_vars)

    if not (replay_dir is None or replay_file is None):
        try:
            save_replay(
                replay_dir,
                replay_file,
                context,
            )
        except (TypeError, ValueError) as error:
            raise InvalidCookiecutterReplay(
                str(replay_file), f"Failed to load the replay file. {error}"
            ) from error

    return context


def get_extra_context_from_file(extra_context_file: Path) -> Dict[str, Any]:
    extra_context = {}
    if extra_context_file.exists():
        with open(extra_context_file, "r") as f:
            extra_context = json.load(f)
    return extra_context
