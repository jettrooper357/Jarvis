"""User-manageable preset and skill library helpers."""

from __future__ import annotations

import importlib.resources
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.skills.loader import discover_skills, load_skill

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_name(kind: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{kind} name is required")
    if not _SAFE_NAME_RE.fullmatch(cleaned):
        raise ValueError(
            f"{kind} name must use only letters, numbers, dot, underscore, or hyphen"
        )
    return cleaned


def user_templates_dir() -> Path:
    return Path("~/.openjarvis/templates").expanduser()


def user_skills_dir() -> Path:
    try:
        from openjarvis.core.config import load_config

        cfg = load_config()
        configured = str(getattr(cfg.skills, "skills_dir", "") or "").strip()
        if configured:
            return Path(configured).expanduser()
    except Exception:
        pass
    return Path("~/.openjarvis/skills").expanduser()


def workspace_skills_dir() -> Path:
    return Path("./skills")


def builtin_templates_dir() -> Path:
    return Path(importlib.resources.files("openjarvis.agents") / "templates")


def builtin_skills_dir() -> Path:
    return Path(importlib.resources.files("openjarvis.skills") / "data")


def parse_template_content(content: str) -> Dict[str, Any]:
    try:
        data = tomllib.loads(content)
    except Exception as exc:
        raise ValueError(f"Invalid template TOML: {exc}") from exc
    template = data.get("template")
    if not isinstance(template, dict):
        raise ValueError("Template file must contain a [template] table")
    template_id = _validate_name("Template id", str(template.get("id", "")))
    template["id"] = template_id
    template["name"] = str(template.get("name", template_id) or template_id)
    template["description"] = str(template.get("description", "") or "")
    template["agent_type"] = str(
        template.get("agent_type", "monitor_operative") or "monitor_operative"
    )
    return template


def _template_summary(template: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    return {
        "id": str(template.get("id", "") or ""),
        "name": str(template.get("name", "") or template.get("id", "") or ""),
        "description": str(template.get("description", "") or ""),
        "agent_type": str(
            template.get("agent_type", "monitor_operative") or "monitor_operative"
        ),
        "source": source,
        "editable": source == "user",
    }


def list_templates() -> List[Dict[str, Any]]:
    templates: Dict[str, Dict[str, Any]] = {}

    for root, source in (
        (builtin_templates_dir(), "built-in"),
        (user_templates_dir(), "user"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.toml")):
            try:
                template = parse_template_content(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            templates[str(template["id"])] = {
                **template,
                "source": source,
                "editable": source == "user",
            }

    return sorted(templates.values(), key=lambda item: str(item.get("name", "")))


def get_template_document(template_id: str) -> Dict[str, Any]:
    template_id = _validate_name("Template id", template_id)
    for root, source in (
        (user_templates_dir(), "user"),
        (builtin_templates_dir(), "built-in"),
    ):
        path = root / f"{template_id}.toml"
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        template = parse_template_content(content)
        return {
            **_template_summary(template, source=source),
            "content": content,
        }
    raise FileNotFoundError(f"Template not found: {template_id}")


def save_template_document(content: str) -> Dict[str, Any]:
    template = parse_template_content(content)
    root = user_templates_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{template['id']}.toml"
    normalized = content.strip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    return {
        **_template_summary(template, source="user"),
        "content": normalized,
    }


def delete_template(template_id: str) -> None:
    template_id = _validate_name("Template id", template_id)
    path = user_templates_dir() / f"{template_id}.toml"
    if not path.exists():
        raise FileNotFoundError(f"User template not found: {template_id}")
    path.unlink()


def parse_skill_content(content: str) -> Dict[str, Any]:
    try:
        data = tomllib.loads(content)
    except Exception as exc:
        raise ValueError(f"Invalid skill TOML: {exc}") from exc
    skill = data.get("skill")
    if not isinstance(skill, dict):
        raise ValueError("Skill file must contain a [skill] table")
    skill_name = _validate_name("Skill name", str(skill.get("name", "")))
    skill["name"] = skill_name
    skill["description"] = str(skill.get("description", "") or "")
    return skill


def _skill_summary(
    name: str,
    description: str,
    *,
    source: str,
    editable: bool,
) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "source": source,
        "editable": editable,
    }


def list_skills() -> List[Dict[str, Any]]:
    skills: Dict[str, Dict[str, Any]] = {}

    builtin_root = builtin_skills_dir()
    if builtin_root.exists():
        for manifest in discover_skills(builtin_root):
            skills[manifest.name] = _skill_summary(
                manifest.name,
                manifest.description,
                source="built-in",
                editable=False,
            )

    workspace_root = workspace_skills_dir()
    if workspace_root.exists():
        for manifest in discover_skills(workspace_root):
            skills[manifest.name] = _skill_summary(
                manifest.name,
                manifest.description,
                source="workspace",
                editable=False,
            )

    user_root = user_skills_dir()
    if user_root.exists():
        for manifest in discover_skills(user_root):
            skills[manifest.name] = _skill_summary(
                manifest.name,
                manifest.description,
                source="user",
                editable=True,
            )

    return sorted(skills.values(), key=lambda item: item["name"])


def get_skill_document(skill_name: str) -> Dict[str, Any]:
    skill_name = _validate_name("Skill name", skill_name)

    user_path = user_skills_dir() / skill_name / "skill.toml"
    if user_path.exists():
        content = user_path.read_text(encoding="utf-8")
        skill = parse_skill_content(content)
        return {
            **_skill_summary(
                skill["name"],
                str(skill.get("description", "") or ""),
                source="user",
                editable=True,
            ),
            "content": content,
        }

    builtin_path = builtin_skills_dir() / f"{skill_name}.toml"
    if builtin_path.exists():
        content = builtin_path.read_text(encoding="utf-8")
        skill = parse_skill_content(content)
        return {
            **_skill_summary(
                skill["name"],
                str(skill.get("description", "") or ""),
                source="built-in",
                editable=False,
            ),
            "content": content,
        }

    workspace_path = workspace_skills_dir() / skill_name / "skill.toml"
    if workspace_path.exists():
        content = workspace_path.read_text(encoding="utf-8")
        skill = parse_skill_content(content)
        return {
            **_skill_summary(
                skill["name"],
                str(skill.get("description", "") or ""),
                source="workspace",
                editable=False,
            ),
            "content": content,
        }

    raise FileNotFoundError(f"Skill not found: {skill_name}")


def save_skill_document(content: str) -> Dict[str, Any]:
    skill = parse_skill_content(content)
    root = user_skills_dir() / str(skill["name"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / "skill.toml"
    normalized = content.strip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    try:
        manifest = load_skill(path)
        description = manifest.description
        name = manifest.name
    except Exception:
        description = str(skill.get("description", "") or "")
        name = str(skill["name"])
    return {
        **_skill_summary(name, description, source="user", editable=True),
        "content": normalized,
    }


def delete_skill(skill_name: str) -> None:
    import shutil

    skill_name = _validate_name("Skill name", skill_name)
    path = user_skills_dir() / skill_name
    if not path.exists():
        raise FileNotFoundError(f"User skill not found: {skill_name}")
    shutil.rmtree(path)
