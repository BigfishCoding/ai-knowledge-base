import os
from dataclasses import dataclass
from typing import Optional

import requests

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 15


@dataclass
class RepoInfo:
    name: str
    full_name: str
    description: str
    stars: int
    forks: int
    language: Optional[str]
    url: str


def fetch_repo_info(owner: str, repo: str) -> RepoInfo:
    """获取 GitHub 仓库基本信息（Star 数、Fork 数、描述）。

    Args:
        owner: 仓库所有者（用户或组织名称）。
        repo: 仓库名称。

    Returns:
        RepoInfo 包含仓库的基本信息。

    Raises:
        requests.RequestException: API 请求失败或响应非 200。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    return RepoInfo(
        name=data["name"],
        full_name=data["full_name"],
        description=data.get("description") or "",
        stars=data["stargazers_count"],
        forks=data["forks_count"],
        language=data.get("language"),
        url=data["html_url"],
    )
