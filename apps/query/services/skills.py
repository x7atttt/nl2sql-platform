# -*- coding: utf-8 -*-
"""技能插拔体系（借鉴 DB-GPT 生产主链路的 SKILL.md 文件约定）。

一个技能 = skills/ 目录下一个子目录 + SKILL.md：
    skills/<name>/SKILL.md
        --- YAML frontmatter: name / description ---
        正文即注入 prompt 的执行指令

插拔性：新建目录+SKILL.md 即被发现（注册表按目录 mtime 失效缓存，无需重启、
零代码接入）。v1 是纯指令技能——scripts/templates 执行能力不在本阶段。
"""
import logging
import os
import time
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 30  # 目录 mtime 未变则复用缓存；变了立即重扫（插拔生效延迟 ≤ 一次请求）


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    dir_name: str


_skills_cache: list[Skill] | None = None
_cache_dir_mtime: float = 0.0
_cache_at: float = 0.0


def skills_dir() -> str:
    return str(getattr(settings, 'SKILLS_DIR', None) or
               os.path.join(str(settings.BASE_DIR), 'skills'))


def _parse_skill_md(path: str) -> Skill | None:
    """解析 SKILL.md：YAML frontmatter（name/description）+ 正文指令。"""
    import yaml
    try:
        text = open(path, encoding='utf-8').read()
    except OSError as e:
        logger.warning('读取技能文件失败 %s: %s', path, e)
        return None
    if not text.startswith('---'):
        logger.warning('技能缺少 frontmatter: %s', path)
        return None
    parts = text.split('---', 2)
    if len(parts) < 3:
        logger.warning('技能 frontmatter 未闭合: %s', path)
        return None
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        logger.warning('技能 frontmatter 非法 YAML %s: %s', path, e)
        return None
    name = str(meta.get('name') or '').strip()
    description = str(meta.get('description') or '').strip()
    instructions = parts[2].strip()
    if not name or not description or not instructions:
        logger.warning('技能缺少 name/description/指令正文: %s', path)
        return None
    return Skill(name=name, description=description,
                 instructions=instructions,
                 dir_name=os.path.basename(os.path.dirname(path)))


def list_skills() -> list[Skill]:
    """全部已注册技能（按 name 排序）。目录 mtime 变化即重扫，未变走缓存。"""
    global _skills_cache, _cache_dir_mtime, _cache_at
    root = skills_dir()
    if not os.path.isdir(root):
        return []
    try:
        mtime = os.path.getmtime(root)
    except OSError:
        return []
    now = time.time()
    if (_skills_cache is not None
            and mtime == _cache_dir_mtime
            and now - _cache_at < _CACHE_TTL_S):
        return _skills_cache

    skills = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, 'SKILL.md')
        if os.path.isfile(path):
            skill = _parse_skill_md(path)
            if skill:
                skills.append(skill)
    _skills_cache = skills
    _cache_dir_mtime = mtime
    _cache_at = now
    return skills


def get_skill(name: str) -> Skill | None:
    for s in list_skills():
        if s.name == name:
            return s
    return None
