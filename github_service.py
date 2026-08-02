import os
import json
import logging
import asyncio
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"

# Auto-read .env if present
def _load_env_token() -> Optional[str]:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GITHUB_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            os.environ["GITHUB_TOKEN"] = val
                            return val
        except Exception as e:
            logger.warning(f"Failed to read .env file: {e}")
    return None

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

class GitHubService:
    def __init__(self, default_token: Optional[str] = None):
        self.default_token = default_token or _load_env_token()

    def get_token(self, override_token: Optional[str] = None) -> Optional[str]:
        return override_token or self.default_token or _load_env_token()

    def _get_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        t = self.get_token(token)
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "TelegramBot-CheapAiTools/1.0"
        }
        if t:
            if t.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {t}"
            else:
                headers["Authorization"] = f"token {t}"
        return headers

    def _sync_request(self, method: str, endpoint: str, token: Optional[str] = None, data: Optional[dict] = None, params: Optional[dict] = None) -> tuple[int, Any]:
        url = f"{GITHUB_API_URL}{endpoint}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        
        headers = self._get_headers(token)
        req_body = json.dumps(data).encode("utf-8") if data else None
        if data and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
            
        req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                err_json = json.loads(body)
            except Exception:
                err_json = {"message": body}
            return e.code, err_json
        except Exception as e:
            return 500, {"message": str(e)}

    async def _request(self, method: str, endpoint: str, token: Optional[str] = None, data: Optional[dict] = None, params: Optional[dict] = None) -> tuple[int, Any]:
        t = self.get_token(token)
        headers = self._get_headers(t)
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    res = await client.request(method, f"{GITHUB_API_URL}{endpoint}", headers=headers, json=data, params=params)
                    try:
                        resp_data = res.json()
                    except Exception:
                        resp_data = {"message": res.text}
                    return res.status_code, resp_data
                except Exception as e:
                    return 500, {"message": str(e)}
        else:
            return await asyncio.to_thread(self._sync_request, method, endpoint, t, data, params)

    async def verify_token(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Verify GitHub token by fetching authenticated user details."""
        t = self.get_token(token)
        if not t:
            return {"valid": False, "error": "No GitHub token provided."}

        status, data = await self._request("GET", "/user", token=t)
        if status == 200:
            return {
                "valid": True,
                "login": data.get("login"),
                "name": data.get("name") or data.get("login"),
                "avatar_url": data.get("avatar_url"),
                "html_url": data.get("html_url"),
                "public_repos": data.get("public_repos", 0),
                "total_private_repos": data.get("total_private_repos", 0),
                "bio": data.get("bio") or "No bio",
                "followers": data.get("followers", 0),
                "following": data.get("following", 0)
            }
        elif status == 401:
            return {"valid": False, "error": "Invalid or expired Personal Access Token."}
        else:
            msg = data.get("message", "Unknown error")
            return {"valid": False, "error": f"GitHub API error ({status}): {msg}"}

    async def get_user_profile(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Get profile info of the authenticated user or default token user."""
        return await self.verify_token(token)

    async def get_user_repos(self, token: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Fetch repositories of the user."""
        status, data = await self._request("GET", "/user/repos", token=token, params={"sort": "updated", "per_page": limit, "type": "all"})
        if status == 200 and isinstance(data, list):
            result = []
            for r in data:
                result.append({
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "private": r.get("private", False),
                    "html_url": r.get("html_url"),
                    "description": r.get("description") or "No description",
                    "stargazers_count": r.get("stargazers_count", 0),
                    "forks_count": r.get("forks_count", 0),
                    "language": r.get("language") or "N/A",
                    "updated_at": r.get("updated_at")
                })
            return {"success": True, "repos": result}
        else:
            msg = data.get("message", "Failed to fetch repositories.") if isinstance(data, dict) else "Error"
            return {"success": False, "error": f"GitHub ({status}): {msg}"}

    async def get_repo_issues(self, owner: str, repo: str, token: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """Fetch issues for a specific repository."""
        status, data = await self._request("GET", f"/repos/{owner}/{repo}/issues", token=token, params={"state": "all", "per_page": limit})
        if status == 200 and isinstance(data, list):
            result = []
            for i in data:
                result.append({
                    "number": i.get("number"),
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "html_url": i.get("html_url"),
                    "user": i.get("user", {}).get("login"),
                    "comments": i.get("comments", 0),
                    "is_pr": "pull_request" in i
                })
            return {"success": True, "issues": result}
        else:
            msg = data.get("message", "Failed to fetch issues.") if isinstance(data, dict) else "Error"
            return {"success": False, "error": f"GitHub ({status}): {msg}"}

    async def get_user_gists(self, token: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Fetch user Gists."""
        status, data = await self._request("GET", "/gists", token=token, params={"per_page": limit})
        if status == 200 and isinstance(data, list):
            result = []
            for g in data:
                files = list(g.get("files", {}).keys())
                result.append({
                    "id": g.get("id"),
                    "html_url": g.get("html_url"),
                    "description": g.get("description") or "No description",
                    "public": g.get("public", False),
                    "files": files
                })
            return {"success": True, "gists": result}
        else:
            msg = data.get("message", "Failed to fetch gists.") if isinstance(data, dict) else "Error"
            return {"success": False, "error": f"GitHub ({status}): {msg}"}

    async def create_gist(self, description: str, filename: str, content: str, public: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        """Create a GitHub Gist."""
        payload = {
            "description": description,
            "public": public,
            "files": {
                filename: {
                    "content": content
                }
            }
        }
        status, data = await self._request("POST", "/gists", token=token, data=payload)
        if status == 201:
            return {"success": True, "html_url": data.get("html_url"), "id": data.get("id")}
        else:
            msg = data.get("message", "Failed to create gist.") if isinstance(data, dict) else "Error"
            return {"success": False, "error": f"GitHub ({status}): {msg}"}

github_service = GitHubService()
