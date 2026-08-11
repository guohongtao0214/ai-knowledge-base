import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com/repos"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def fetch_repo_info(owner: str, repo: str) -> dict[str, Any]:
    """从 GitHub API 获取指定仓库的基本信息。

    Args:
        owner: 仓库所有者（用户名或组织名）。
        repo: 仓库名称。

    Returns:
        包含仓库基本信息的字典，字段包括：
            - full_name: 仓库全名
            - stars: Star 数量
            - forks: Fork 数量
            - description: 仓库描述
            - url: 仓库 HTML 地址

    Raises:
        ValueError: GitHub Token 未配置时抛出。
        urllib.error.URLError: 网络连接失败时抛出。
        urllib.error.HTTPError: API 返回非 2xx 状态码时抛出。
    """
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN 环境变量未设置，请先配置 GitHub Token")

    url = f"{GITHUB_API_BASE}/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-knowledge-base",
    }

    req = urllib.request.Request(url, headers=headers)

    logger.info(f"正在获取仓库信息: {owner}/{repo}")

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    repo_info = {
        "full_name": data.get("full_name", ""),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "description": data.get("description", ""),
        "url": data.get("html_url", ""),
    }

    logger.info(
        f"成功获取 {repo_info['full_name']}: "
        f"Stars={repo_info['stars']}, Forks={repo_info['forks']}"
    )

    return repo_info
