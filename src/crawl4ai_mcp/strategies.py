from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .models import SiteStrategy

logger = logging.getLogger(__name__)

GENERIC_STRATEGY = SiteStrategy(name="普通网页", domains=(), source="builtin")


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _resolve_snippets(raw_snippets, snippets: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for item in raw_snippets or []:
        text = str(item)
        if text.startswith("snippet:"):
            key = text[len("snippet:") :].strip()
            if key not in snippets:
                raise ValueError(f"Unknown snippet reference: {key}")
            resolved.append(snippets[key])
        else:
            resolved.append(text)
    return resolved


def _strategy_from_dict(data: dict, *, source: str, snippets: dict[str, str]) -> SiteStrategy:
    if not isinstance(data, dict):
        raise ValueError("Strategy document must be a mapping")
    name = data.get("name")
    domains = data.get("domains")
    if not name or not domains:
        raise ValueError("Strategy requires name and domains")
    return SiteStrategy(
        name=str(name),
        domains=_as_tuple(domains),
        css_selector=data.get("css_selector"),
        css_selector_fallbacks=_as_tuple(data.get("css_selector_fallbacks")),
        excluded_selector=data.get("excluded_selector"),
        wait_for=data.get("wait_for"),
        js_snippets=_resolve_snippets(data.get("js_snippets"), snippets),
        title_suffixes=_as_tuple(data.get("title_suffixes")),
        title_selector=data.get("title_selector"),
        author_selector=data.get("author_selector"),
        date_selector=data.get("date_selector"),
        source=source,
    )


def load_snippets(builtin_dir: Path) -> dict[str, str]:
    path = builtin_dir / "_snippets.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("_snippets.yaml must be a mapping")
    return {str(k): str(v) for k, v in data.items()}


def _iter_strategy_files(directory: Path):
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        yield path


def _load_dir(
    directory: Path,
    *,
    source: str,
    snippets: dict[str, str],
) -> list[SiteStrategy]:
    loaded: list[SiteStrategy] = []
    for path in _iter_strategy_files(directory) or ():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            loaded.append(_strategy_from_dict(data, source=source, snippets=snippets))
        except Exception as exc:  # tolerant v1: skip bad files
            logger.warning("Skipping strategy file %s: %s", path, exc)
    return loaded


def load_strategies(
    builtin_dir: Path,
    user_dir: Path | None,
    snippets: dict[str, str] | None = None,
) -> list[SiteStrategy]:
    builtin_dir = Path(builtin_dir)
    resolved_snippets = snippets if snippets is not None else load_snippets(builtin_dir)
    by_name: dict[str, SiteStrategy] = {}
    for strategy in _load_dir(builtin_dir, source="builtin", snippets=resolved_snippets):
        by_name[strategy.name.casefold()] = strategy
    if user_dir is not None:
        user_path = Path(user_dir)
        if user_path.is_dir():
            for strategy in _load_dir(user_path, source="user", snippets=resolved_snippets):
                by_name[strategy.name.casefold()] = strategy
        elif user_dir is not None:
            logger.warning("CONFIG user dir missing or not a directory: %s", user_path)
    return list(by_name.values())


def detect_strategy(strategies: list[SiteStrategy], url: str) -> SiteStrategy:
    for strategy in strategies:
        if strategy.source == "user" and strategy.matches(url):
            return strategy
    for strategy in strategies:
        if strategy.source != "user" and strategy.matches(url):
            return strategy
    return GENERIC_STRATEGY
