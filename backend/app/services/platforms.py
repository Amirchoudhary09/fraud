"""Public platform registry: which domains belong to which platform, how to read a public username
from a profile URL, and whether the platform's public profiles are reachable through web search.

The list is a starting point, not a whitelist: URLs on unknown domains are classified as
"website" and can still become leads (personal sites, portfolios, forums).
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domains: tuple[str, ...]
    # regex on the URL path; group 1 = public username / handle
    profile_path: str | None
    # False = profiles are mostly login-walled or not indexed, so web search cannot reliably find them
    searchable: bool = True
    # never fetched directly (Terms of Service / login walls); evidence comes from search results only
    fetchable: bool = False


_H = r"@?([A-Za-z0-9_.\-]{2,64})"

PLATFORMS: tuple[Platform, ...] = (
    Platform("linkedin", "LinkedIn", ("linkedin.com",), r"^/in/([A-Za-z0-9_\-%]{2,100})"),
    Platform("github", "GitHub", ("github.com",), rf"^/{_H}/?$"),
    Platform("gitlab", "GitLab", ("gitlab.com",), rf"^/{_H}/?$"),
    Platform("x", "X / Twitter", ("x.com", "twitter.com"), rf"^/{_H}/?$"),
    Platform("instagram", "Instagram", ("instagram.com",), rf"^/{_H}/?$"),
    Platform("facebook", "Facebook", ("facebook.com", "fb.com"), rf"^/{_H}/?$"),
    Platform("threads", "Threads", ("threads.net", "threads.com"), rf"^/{_H}/?$"),
    Platform("youtube", "YouTube", ("youtube.com",), r"^/(?:@|c/|user/|channel/)([A-Za-z0-9_.\-]{2,64})"),
    Platform("tiktok", "TikTok", ("tiktok.com",), rf"^/@([A-Za-z0-9_.\-]{{2,64}})"),
    Platform("reddit", "Reddit", ("reddit.com",), r"^/(?:u|user)/([A-Za-z0-9_\-]{2,64})"),
    Platform("pinterest", "Pinterest", ("pinterest.com",), rf"^/{_H}/?$"),
    Platform("quora", "Quora", ("quora.com",), r"^/profile/([A-Za-z0-9_\-]{2,100})"),
    Platform("medium", "Medium", ("medium.com",), r"^/@([A-Za-z0-9_.\-]{2,64})"),
    Platform("devto", "Dev.to", ("dev.to",), rf"^/{_H}/?$"),
    Platform("stackoverflow", "Stack Overflow", ("stackoverflow.com",), r"^/users/\d+/([A-Za-z0-9_\-]{2,64})"),
    Platform("stackexchange", "Stack Exchange", ("stackexchange.com",), r"^/users/\d+/([A-Za-z0-9_\-]{2,64})"),
    Platform("kaggle", "Kaggle", ("kaggle.com",), rf"^/{_H}/?$"),
    Platform("huggingface", "Hugging Face", ("huggingface.co",), rf"^/{_H}/?$"),
    Platform("behance", "Behance", ("behance.net",), rf"^/{_H}/?$"),
    Platform("dribbble", "Dribbble", ("dribbble.com",), rf"^/{_H}/?$"),
    Platform("twitch", "Twitch", ("twitch.tv",), rf"^/{_H}/?$"),
    Platform("vimeo", "Vimeo", ("vimeo.com",), r"^/([A-Za-z][A-Za-z0-9_\-]{1,63})/?$"),
    Platform("spotify", "Spotify", ("open.spotify.com",), r"^/(?:user|artist)/([A-Za-z0-9]{2,64})"),
    Platform("soundcloud", "SoundCloud", ("soundcloud.com",), rf"^/{_H}/?$"),
    Platform("goodreads", "Goodreads", ("goodreads.com",), r"^/user/show/([A-Za-z0-9_\-]{2,100})"),
    Platform("producthunt", "Product Hunt", ("producthunt.com",), r"^/@([A-Za-z0-9_\-]{2,64})"),
    Platform("substack", "Substack", ("substack.com",), r"^/@([A-Za-z0-9_\-]{2,64})"),
    Platform("patreon", "Patreon", ("patreon.com",), rf"^/{_H}/?$"),
    Platform("kofi", "Ko-fi", ("ko-fi.com",), rf"^/{_H}/?$"),
    Platform("buymeacoffee", "Buy Me a Coffee", ("buymeacoffee.com",), rf"^/{_H}/?$"),
    Platform("linktree", "Linktree", ("linktr.ee",), rf"^/{_H}/?$", fetchable=True),
    Platform("aboutme", "about.me", ("about.me",), rf"^/{_H}/?$", fetchable=True),
    Platform("telegram", "Telegram (public)", ("t.me", "telegram.me"), rf"^/{_H}/?$", searchable=False),
    Platform("discord", "Discord (public)", ("discord.com", "discord.gg"), None, searchable=False),
    Platform("snapchat", "Snapchat (public)", ("snapchat.com",), r"^/add/([A-Za-z0-9_.\-]{2,64})", searchable=False),
)

BY_KEY = {p.key: p for p in PLATFORMS}
_RESERVED = {"home", "login", "signup", "explore", "search", "about", "help", "settings", "privacy", "terms",
             "watch", "results", "p", "reel", "status", "hashtag", "i", "share", "sharer", "pages", "groups",
             "events", "jobs", "company", "school", "feed", "topics", "trending", "notifications", "messages"}
# Where a public profile's own subdomain is the handle (e.g. name.substack.com, name.medium.com).
_SUBDOMAIN_PLATFORMS = {"substack.com": "substack", "medium.com": "medium", "github.io": "website",
                        "hashnode.dev": "website", "wordpress.com": "website", "blogspot.com": "website"}


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")


def classify_url(url: str) -> tuple[str, str | None]:
    """Returns (platform key, username or None). Unknown domains -> ("website", None)."""
    host, path = _host(url), urlsplit(url).path or "/"
    for suffix, key in _SUBDOMAIN_PLATFORMS.items():  # name.substack.com, name.github.io, ...
        if host.endswith("." + suffix):
            return key, host[: -len(suffix) - 1]
    for p in PLATFORMS:
        if any(host == d or host.endswith("." + d) for d in p.domains):
            if p.profile_path:
                m = re.match(p.profile_path, path)
                if m and m.group(1).lower() not in _RESERVED:
                    return p.key, m.group(1).lstrip("@")
            return p.key, None
    return "website", None


def is_social(platform_key: str) -> bool:
    return platform_key in BY_KEY and not BY_KEY[platform_key].fetchable


def fetchable_url(url: str) -> bool:
    """Only personal/portfolio sites and link-in-bio pages are fetched; social networks never are."""
    key, _ = classify_url(url)
    return key == "website" or (key in BY_KEY and BY_KEY[key].fetchable)


def site_groups(max_groups: int) -> list[tuple[list[str], str]]:
    """Searchable platforms bundled into site: groups (to save query budget). Returns (keys, 'site:a OR site:b')."""
    keys = [p.key for p in PLATFORMS if p.searchable]
    per = max(1, -(-len(keys) // max_groups))
    groups = [keys[i:i + per] for i in range(0, len(keys), per)]
    out = []
    for g in groups:
        sites = " OR ".join(f"site:{BY_KEY[k].domains[0]}" for k in g)
        out.append((g, f"({sites})"))
    return out
