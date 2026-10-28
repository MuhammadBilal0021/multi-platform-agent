import os
import json
import secrets
import hashlib

def is_user_allowed(user_id: str) -> bool:
    allowed_users_str = os.environ.get("ALLOWED_USERS", "")
    if not allowed_users_str:
        return False
    allowed = [u.strip() for u in allowed_users_str.split(",") if u.strip()]
    return user_id in allowed

def is_tool_allowed(tool_name: str) -> bool:
    allowed_tools_str = os.environ.get("ALLOWED_TOOLS", "")
    if not allowed_tools_str:
        return False
    allowed = [t.strip() for t in allowed_tools_str.split(",") if t.strip()]
    return tool_name in allowed

def is_tool_destructive(tool_name: str) -> bool:
    destructive_tools_str = os.environ.get("DESTRUCTIVE_TOOLS", "")
    if not destructive_tools_str:
        return False
    destructive = [t.strip() for t in destructive_tools_str.split(",") if t.strip()]
    return tool_name in destructive

def generate_nonce() -> str:
    return secrets.token_hex(16)

def canonical_json(args: dict) -> str:
    if not isinstance(args, dict):
        args = {}
    return json.dumps(args, sort_keys=True, separators=(",", ":"))

def hash_tool_args(args: dict) -> str:
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()

def get_tool_signature(tool_name: str, args: dict) -> str:
    return f"{tool_name}:{hash_tool_args(args)}"
