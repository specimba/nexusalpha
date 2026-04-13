"""
engine/skill_adapter.py — Skill Adapter Layer for Nexus OS

Bridges the z.ai platform skills ecosystem to the Hermes experience-based
model router. Each platform skill is represented as a SkillDefinition with
rich metadata (domain mapping, complexity range, token cost, regex pattern).
The SkillRegistry converts these definitions into Hermes SkillRecords for
fast-path routing and provides utilities for skill discovery, cost estimation,
and command generation.

Architecture:
  z.ai Platform Skills  ──►  SkillDefinition  ──►  SkillRegistry  ──►  HermesRouter
  (/home/z/my-project/skills/)    (rich metadata)   (catalog + search)   (fast-path)
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Valid complexity levels (must align with hermes.TaskComplexity)
COMPLEXITY_LEVELS = ("trivial", "standard", "complex", "critical")
COMPLEXITY_ORDER = {level: idx for idx, level in enumerate(COMPLEXITY_LEVELS)}

# Default model recommendation per Hermes domain
_DEFAULT_MODEL_PER_DOMAIN = {
    "code": "osman-coder",
    "analysis": "groq/gpt-oss-20b",
    "reasoning": "osman-reasoning",
    "creative": "groq/gpt-oss-20b",
    "operations": "osman-coder",
    "security": "osman-reasoning",
    "unknown": "osman-coder",
}

# Token cost multipliers per level
_TOKEN_COST_MULTIPLIERS = {
    "trivial": 0.5,
    "standard": 1.0,
    "complex": 2.0,
    "critical": 4.0,
}

# Base token costs per skill cost tier
_BASE_TOKEN_COSTS = {
    "low": 500,
    "medium": 2000,
    "high": 8000,
}


@dataclass
class SkillDefinition:
    """Rich metadata for a single platform skill.

    Encapsulates everything needed to match a task to a skill, estimate
    costs, and generate an execution command.
    """

    skill_id: str                          # e.g. "web-search"
    name: str                              # e.g. "Web Search"
    description: str                       # Human-readable description
    domains: List[str]                     # Matching Hermes domains: ["analysis", "reasoning"]
    complexity_range: Tuple[str, str]      # (min, max) complexity: ("trivial", "critical")
    capabilities: List[str]                # ["search", "real-time", "research"]
    token_cost: str                        # "low", "medium", "high"
    requires_api: bool                     # Whether it needs external API access
    execution_mode: str                    # "cli", "sdk", "api"
    pattern: str                           # Regex pattern for fast-path matching
    sdk_module: Optional[str] = None       # Python module path if applicable
    sdk_class: Optional[str] = None        # Class name for SDK invocation

    # ── Hermes integration fields (populated on conversion) ──
    hermes_task_type: str = "unknown"      # Primary Hermes task_type for routing
    hermes_recommended_model: str = "osman-coder"
    hermes_initial_execution_count: int = 5  # Bootstrap above Hermes min threshold of 3

    def __post_init__(self):
        """Validate fields and set hermes_task_type from domains."""
        # Validate complexity range
        min_c, max_c = self.complexity_range
        if min_c not in COMPLEXITY_LEVELS:
            raise ValueError(f"Invalid min complexity: {min_c!r}. Must be one of {COMPLEXITY_LEVELS}")
        if max_c not in COMPLEXITY_LEVELS:
            raise ValueError(f"Invalid max complexity: {max_c!r}. Must be one of {COMPLEXITY_LEVELS}")
        if COMPLEXITY_ORDER[min_c] > COMPLEXITY_ORDER[max_c]:
            raise ValueError(f"Min complexity {min_c!r} > max complexity {max_c!r}")

        # Validate token_cost
        if self.token_cost not in _BASE_TOKEN_COSTS:
            raise ValueError(f"Invalid token_cost: {self.token_cost!r}. Must be one of {list(_BASE_TOKEN_COSTS)}")

        # Validate execution_mode
        if self.execution_mode not in ("cli", "sdk", "api"):
            raise ValueError(f"Invalid execution_mode: {self.execution_mode!r}")

        # Validate regex compiles
        try:
            re.compile(self.pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern {self.pattern!r}: {e}")

        # Set hermes_task_type from first domain
        if self.domains and self.hermes_task_type == "unknown":
            self.hermes_task_type = self.domains[0]

        # Set recommended model from primary domain
        model = _DEFAULT_MODEL_PER_DOMAIN.get(self.hermes_task_type)
        if model and self.hermes_recommended_model == "osman-coder" and self.hermes_task_type != "code":
            self.hermes_recommended_model = model

    def complexity_matches(self, complexity: str) -> bool:
        """Check if a given complexity level falls within this skill's range."""
        if complexity not in COMPLEXITY_ORDER:
            return False
        min_idx = COMPLEXITY_ORDER[self.complexity_range[0]]
        max_idx = COMPLEXITY_ORDER[self.complexity_range[1]]
        return min_idx <= COMPLEXITY_ORDER[complexity] <= max_idx

    def domain_matches(self, domain: str) -> bool:
        """Check if a given Hermes domain is covered by this skill."""
        return domain in self.domains

    def matches_description(self, description: str) -> bool:
        """Check if a task description matches this skill's regex pattern."""
        return bool(re.search(self.pattern, description.lower()))


# ══════════════════════════════════════════════════════════════════════
# Pre-defined Skill Catalog
# ══════════════════════════════════════════════════════════════════════

SKILL_CATALOG: List[SkillDefinition] = [
    # ── Information Retrieval ──────────────────────────────────────────
    SkillDefinition(
        skill_id="web-search",
        name="Web Search",
        description="Search the internet for real-time information, news, and data. "
                    "Returns structured results with URLs, snippets, and metadata.",
        domains=["analysis", "reasoning"],
        complexity_range=("trivial", "complex"),
        capabilities=["search", "real-time", "research", "news"],
        token_cost="low",
        requires_api=True,
        execution_mode="cli",
        pattern=r"(search|find|look\s+up|google|query)\s+(the\s+)?(web|internet|online|for|about)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="analysis",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="web-reader",
        name="Web Page Reader",
        description="Extract content from web pages including text, metadata, and publication time. "
                    "Useful for scraping articles, documentation, and structured data extraction.",
        domains=["analysis", "operations"],
        complexity_range=("trivial", "standard"),
        capabilities=["scrape", "extract", "web-content", "metadata"],
        token_cost="low",
        requires_api=True,
        execution_mode="cli",
        pattern=r"(scrape|extract|read|fetch|crawl|parse)\s+(the\s+)?(web\s+)?(page|site|url|content|article)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="agent-browser",
        name="Agent Browser",
        description="Headless browser automation for navigating, clicking, typing, and "
                    "snapshotting pages via structured commands. Supports form filling, "
                    "screenshots, and multi-tab workflows.",
        domains=["operations", "code"],
        complexity_range=("standard", "critical"),
        capabilities=["browser", "automation", "navigation", "screenshot", "form-filling"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(browse|navigate|automat|screenshot|click|fill\s+form|headless|browser|web\s+automation)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    # ── AI / LLM Core ─────────────────────────────────────────────────
    SkillDefinition(
        skill_id="LLM",
        name="LLM Chat Completions",
        description="Large language model chat completions for conversational AI, "
                    "text generation, summarization, and multi-turn dialogue.",
        domains=["reasoning", "creative", "analysis", "code"],
        complexity_range=("trivial", "critical"),
        capabilities=["chat", "completions", "conversation", "text-generation", "summarization"],
        token_cost="medium",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(chat|convers|dialogue|ask|talk|respond|reply|answer|explain|summarize|generate\s+text)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="reasoning",
        hermes_recommended_model="osman-reasoning",
    ),

    SkillDefinition(
        skill_id="VLM",
        name="Vision Language Model",
        description="Vision-based AI for image analysis, visual content understanding, "
                    "and multimodal interactions with images.",
        domains=["analysis", "reasoning"],
        complexity_range=("standard", "complex"),
        capabilities=["vision", "image-analysis", "multimodal", "visual-understanding"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(analyze|describe|understand|examine|what\s+(is|are)\s+in|identify)\s+(the\s+)?(image|photo|picture|screenshot|visual)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="analysis",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    # ── Speech ─────────────────────────────────────────────────────────
    SkillDefinition(
        skill_id="TTS",
        name="Text-to-Speech",
        description="Convert text into natural-sounding speech audio files. "
                    "Supports multiple voices, adjustable speed, and various audio formats.",
        domains=["creative"],
        complexity_range=("trivial", "standard"),
        capabilities=["speech", "audio", "voice", "narration", "tts"],
        token_cost="medium",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(speak|narrate|read\s+aloud|text.to.speech|tts|voice|audio|pronounce)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="creative",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="ASR",
        name="Speech-to-Text",
        description="Automatic speech recognition to transcribe audio files into text. "
                    "Supports multiple audio formats and languages.",
        domains=["analysis"],
        complexity_range=("trivial", "standard"),
        capabilities=["transcription", "speech-recognition", "audio-processing", "asr"],
        token_cost="medium",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(transcribe|speech.to.text|asr|recognize\s+speech|convert\s+audio|dictation)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="analysis",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    # ── Media Generation ───────────────────────────────────────────────
    SkillDefinition(
        skill_id="image-generation",
        name="AI Image Generation",
        description="Generate images from text descriptions using AI. "
                    "Creates visual content, artwork, and design assets.",
        domains=["creative"],
        complexity_range=("standard", "complex"),
        capabilities=["image", "generation", "art", "design", "visual-creation"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(generate|create|make|draw|render|produce)\s+(an?\s+)?(image|picture|illustration|artwork|photo|graphic|logo)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="creative",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="video-generation",
        name="AI Video Generation",
        description="Generate videos from text prompts or images using AI. "
                    "Supports asynchronous task management with status polling.",
        domains=["creative"],
        complexity_range=("complex", "critical"),
        capabilities=["video", "generation", "animation", "motion"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(generate|create|make|produce)\s+(a\s+)?(video|animation|clip|movie|film)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="creative",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="video-understand",
        name="Video Understanding",
        description="Analyze video content including motion, temporal sequences, "
                    "and scene descriptions. Optimized for MP4, AVI, MOV formats.",
        domains=["analysis"],
        complexity_range=("complex", "critical"),
        capabilities=["video", "analysis", "scene-understanding", "temporal"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(analyze|understand|describe|summarize|watch|review)\s+(the\s+)?(video|clip|footage|movie|recording)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="analysis",
        hermes_recommended_model="osman-reasoning",
    ),

    # ── Data Visualization ─────────────────────────────────────────────
    SkillDefinition(
        skill_id="charts",
        name="Charts and Diagrams",
        description="Professional chart and diagram creation using matplotlib, seaborn, "
                    "ECharts, D3.js, or Mermaid. Covers data charts, structural diagrams, "
                    "dashboards, and flowcharts.",
        domains=["creative", "analysis", "code"],
        complexity_range=("standard", "complex"),
        capabilities=["charts", "diagrams", "visualization", "matplotlib", "echarts", "d3", "mermaid", "dashboard"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(chart|graph|diagram|plot|visualiz|dashboard|histogram|scatter|bar\s+chart|pie\s+chart|flowchart|mind\s*map)",
        hermes_task_type="creative",
        hermes_recommended_model="osman-coder",
    ),

    # ── Document Generation ────────────────────────────────────────────
    SkillDefinition(
        skill_id="pdf",
        name="PDF Creation",
        description="Create, manipulate, and convert PDF documents including "
                    "reports, academic papers, forms, and posters.",
        domains=["creative", "operations"],
        complexity_range=("standard", "critical"),
        capabilities=["pdf", "document", "typesetting", "forms", "reports"],
        token_cost="high",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(create|generate|make|build|write)\s+(a\s+)?(pdf|document|report|paper|poster|form)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="docx",
        name="Word Document Creation",
        description="Create and edit Word documents (.docx) with support for "
                    "tracked changes, comments, and professional formatting.",
        domains=["creative", "operations"],
        complexity_range=("standard", "complex"),
        capabilities=["word", "document", "docx", "editing", "formatting", "tracked-changes"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(create|edit|write|generate|modify)\s+(a\s+)?(word|docx|\.docx|document)\b",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="xlsx",
        name="Excel Spreadsheet Creation",
        description="Create, edit, and analyze Excel spreadsheets (.xlsx, .xlsm, .csv). "
                    "Supports data visualization, pivot tables, and financial analysis.",
        domains=["analysis", "operations"],
        complexity_range=("standard", "complex"),
        capabilities=["excel", "spreadsheet", "xlsx", "data-analysis", "pivot", "charts"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(create|edit|analyze|generate|make|build)\s+(an?\s+)?(excel|spreadsheet|xlsx|\.xlsx|csv|table|report)\b",
        hermes_task_type="analysis",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="pptx",
        name="PowerPoint Presentation Creation",
        description="Create, edit, and manage PowerPoint presentations (.pptx) "
                    "with layouts, speaker notes, and professional design.",
        domains=["creative", "operations"],
        complexity_range=("standard", "complex"),
        capabilities=["presentation", "slides", "pptx", "powerpoint", "deck"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(create|edit|make|build|generate|design)\s+(a\s+)?(presentation|slides?|pptx|powerpoint|deck)",
        hermes_task_type="creative",
        hermes_recommended_model="osman-coder",
    ),

    # ── Financial Analysis ─────────────────────────────────────────────
    SkillDefinition(
        skill_id="finance",
        name="Financial Data Analysis",
        description="Real-time and historical financial data analysis including "
                    "stock prices, market data, company financials, and investment analysis.",
        domains=["analysis", "reasoning"],
        complexity_range=("standard", "critical"),
        capabilities=["finance", "stocks", "market", "investment", "portfolio", "trading"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(stock|market|price|financial|invest|portfolio|trading|dividend|earnings|revenue|profit|sec\s+file|10-[kq])",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="analysis",
        hermes_recommended_model="osman-reasoning",
    ),

    # ── Code & Development ─────────────────────────────────────────────
    SkillDefinition(
        skill_id="coding-agent",
        name="Coding Agent",
        description="Code generation, review, and software development patterns. "
                    "Implements planning, execution, and verification workflows.",
        domains=["code", "reasoning"],
        complexity_range=("standard", "critical"),
        capabilities=["code", "generation", "review", "debugging", "refactoring", "testing"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(implement|write|generate|build|code|program|develop|debug|refactor|review)\s+(a\s+)?"
                r"(function|class|module|api|endpoint|service|component|feature|system|application|library)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="fullstack-dev",
        name="Full-Stack Web Development",
        description="Full-stack web application development with Next.js, TypeScript, "
                    "Tailwind CSS, shadcn/ui, and Prisma ORM.",
        domains=["code", "operations"],
        complexity_range=("complex", "critical"),
        capabilities=["web", "fullstack", "nextjs", "react", "typescript", "api", "database"],
        token_cost="high",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(build|create|scaffold|set\s+up|develop)\s+(a\s+)?"
                r"(web\s+app|fullstack|full-stack|next\.?js|react\s+app|saas|website|landing\s+page)",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),

    # ── Frontend Development (enriched from GitHub/Reddit research) ────────
    SkillDefinition(
        skill_id="shadcn-ui",
        name="shadcn/ui Component Builder",
        description="Generate and customize shadcn/ui components with Tailwind CSS. "
                    "Supports accessible, unstyled Radix primitives with Tailwind styling. "
                    "Reads components.json for project config and generates tailored code.",
        domains=["code", "creative"],
        complexity_range=("standard", "complex"),
        capabilities=["components", "ui", "shadcn", "tailwind", "radix", "accessible", "design-system"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(shadcn|component|ui\s+component|button|dialog|dropdown|toast|card|table|form)\s*(builder|generator|create|add|install)",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="screenshot-to-code",
        name="Screenshot to Code",
        description="Convert screenshots, designs, or wireframes into HTML, Tailwind CSS, "
                    "and React code. Supports responsive layout generation from visual input. "
                    "Based on abi/screenshot-to-code patterns.",
        domains=["code", "creative"],
        complexity_range=("complex", "critical"),
        capabilities=["screenshot", "design-to-code", "visual", "html", "tailwind", "react", "responsive"],
        token_cost="high",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(screenshot|image|design|wireframe|mockup|figma)\s*(to|into|convert|transform)\s*(code|html|react|component|tailwind)",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="playwright-testing",
        name="Playwright E2E Testing",
        description="Generate and run Playwright end-to-end tests with browser automation. "
                    "Supports multi-viewport testing, visual regression, and AI trace analysis. "
                    "Includes codegen for test generation from browser interactions.",
        domains=["code", "operations", "security"],
        complexity_range=("standard", "complex"),
        capabilities=["testing", "e2e", "browser", "playwright", "visual-regression", "codegen", "multi-viewport"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(playwright|e2e|end.to.end|browser\s*test|visual\s*regression|screenshot\s*test|cross.browser)\s*(test|write|generate|run|create)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="eslint-lint",
        name="ESLint Code Quality",
        description="Run ESLint for JavaScript/TypeScript code quality analysis. "
                    "Detects bugs, enforces coding standards, and provides auto-fix capabilities. "
                    "Supports flat config (eslint.config.js) for agent-managed configurations.",
        domains=["code", "security"],
        complexity_range=("trivial", "standard"),
        capabilities=["linting", "eslint", "code-quality", "bug-detection", "auto-fix", "standards"],
        token_cost="low",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(eslint|lint|code\s*quality|style\s*check|format\s*check|bug\s*detect)\s*(run|check|fix|analyze|scan)",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),

    # ── MCP Tools (Model Context Protocol integration) ───────────────────
    SkillDefinition(
        skill_id="mcp-filesystem",
        name="MCP Filesystem Tools",
        description="MCP server exposing file system operations: read, write, list, search. "
                    "Core tool for any code agent. Supports directory listing, file search, "
                    "and permission-aware access control via the Model Context Protocol.",
        domains=["operations", "code"],
        complexity_range=("trivial", "standard"),
        capabilities=["filesystem", "mcp", "file-ops", "directory", "search", "read-write"],
        token_cost="low",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(read|write|list|search|find|browse)\s+(file|directory|folder|path|filesystem)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="mcp-git",
        name="MCP Git Operations",
        description="MCP server for Git version control operations: diff, log, status, commit, "
                    "branch management, and blame. Enables agents to interact with git "
                    "repositories through standardized MCP tool protocol.",
        domains=["operations", "code"],
        complexity_range=("trivial", "standard"),
        capabilities=["git", "mcp", "version-control", "diff", "commit", "branch", "blame"],
        token_cost="low",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(git|commit|branch|merge|diff|log|blame|rebase|checkout|stash)\s*(operation|command|manage|run)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="mcp-semgrep",
        name="MCP Semgrep Security Scanner",
        description="Static application security testing via Semgrep through MCP protocol. "
                    "Scans code for vulnerabilities, custom security rules, and best practice "
                    "violations. Essential for security-hardened agentic code generation.",
        domains=["security", "code"],
        complexity_range=("standard", "complex"),
        capabilities=["security", "sast", "semgrep", "vulnerability", "scanning", "mcp", "rules"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(semgrep|security\s*scan|sast|vulnerability|code\s*audit|security\s*review|static\s*analysis)\s*(run|scan|check|analyze)",
        hermes_task_type="security",
        hermes_recommended_model="osman-reasoning",
    ),

    # ── Documentation & Review ───────────────────────────────────────────
    SkillDefinition(
        skill_id="doc-generator",
        name="Documentation Generator",
        description="Generate TSDoc, JSDoc, Python docstrings, API reference, and Markdown "
                    "documentation from source code. Supports inline docs, README generation, "
                    "and API spec generation from Zod/OpenAPI schemas.",
        domains=["creative", "operations"],
        complexity_range=("standard", "complex"),
        capabilities=["documentation", "docstring", "tsdoc", "jsdoc", "api-reference", "readme", "markdown"],
        token_cost="medium",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(document|docstring|tsdoc|jsdoc|readme|api\s*reference|comment)\s*(generate|write|create|build|add)",
        hermes_task_type="creative",
        hermes_recommended_model="groq/gpt-oss-20b",
    ),

    SkillDefinition(
        skill_id="code-review",
        name="AI Code Review",
        description="Automated code review analyzing diffs for bugs, security issues, "
                    "performance problems, and style violations. Provides actionable feedback "
                    "with severity ratings and fix suggestions.",
        domains=["code", "security"],
        complexity_range=("standard", "complex"),
        capabilities=["review", "pr-review", "diff-analysis", "security-audit", "best-practices", "feedback"],
        token_cost="medium",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(review|audit|analyze|inspect|critique|examine)\s+(code|pr|pull\s*request|diff|commit|changes?)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="code",
        hermes_recommended_model="osman-reasoning",
    ),

    # ── Performance & Monitoring ─────────────────────────────────────────
    SkillDefinition(
        skill_id="lighthouse-audit",
        name="Lighthouse Performance Audit",
        description="Run Google Lighthouse CI for automated performance, accessibility, "
                    "SEO, and PWA auditing. Provides scoring and actionable recommendations "
                    "for frontend optimization.",
        domains=["operations", "code"],
        complexity_range=("standard", "complex"),
        capabilities=["performance", "lighthouse", "accessibility", "seo", "pwa", "audit", "metrics"],
        token_cost="low",
        requires_api=False,
        execution_mode="cli",
        pattern=r"(lighthouse|performance\s*audit|accessibility|seo\s*audit|pwa\s*audit|page\s*speed|core\s*web\s*vitals)\s*(run|check|audit|analyze|measure)",
        hermes_task_type="operations",
        hermes_recommended_model="osman-coder",
    ),

    SkillDefinition(
        skill_id="test-generator",
        name="AI Test Generator",
        description="Generate unit tests, integration tests, and E2E tests from source code. "
                    "Supports pytest, Jest, Vitest, and Playwright. Uses TDD patterns: "
                    "generate tests first, then implement to pass.",
        domains=["code", "operations"],
        complexity_range=("standard", "complex"),
        capabilities=["testing", "test-generation", "unit-test", "integration-test", "tdd", "coverage", "pytest", "jest"],
        token_cost="medium",
        requires_api=True,
        execution_mode="sdk",
        pattern=r"(generate|write|create|add|build)\s+(test|spec|suite|coverage)\s*(for|from|based\s*on)\s*(this|the|code|function|module|component)",
        sdk_module="z_ai_web_dev_sdk",
        sdk_class="ZAI",
        hermes_task_type="code",
        hermes_recommended_model="osman-coder",
    ),
]


class SkillRegistry:
    """Registry of available skills with Hermes integration.

    Maps z.ai platform skills to Nexus OS task types. When Hermes classifies
    a task, the SkillRegistry provides the matching skill(s) for fast-path
    execution.

    Usage:
        registry = SkillRegistry()
        router = HermesRouter(db)

        for skill_record in registry.create_hermes_skill_records():
            router.register_skill(skill_record)

        decision = router.route("task-1", "Search the web for latest AI news")
        # decision.matched_skill == "web-search"
    """

    def __init__(self) -> None:
        """Initialize the registry and load the predefined skill catalog."""
        self._skills: Dict[str, SkillDefinition] = {}
        for skill in SKILL_CATALOG:
            self._skills[skill.skill_id] = skill
        logger.info("SkillRegistry initialized with %d catalog skills", len(self._skills))

    # ── Registration ───────────────────────────────────────────────────

    def register_skill(self, skill: SkillDefinition) -> None:
        """Register a new skill or update an existing one.

        Args:
            skill: The SkillDefinition to register.

        Raises:
            ValueError: If the skill_id is empty.
        """
        if not skill.skill_id:
            raise ValueError("skill_id must not be empty")
        self._skills[skill.skill_id] = skill
        logger.info("Registered skill: %s (%s)", skill.skill_id, skill.name)

    # ── Lookup ─────────────────────────────────────────────────────────

    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get a skill by its ID.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The SkillDefinition, or None if not found.
        """
        return self._skills.get(skill_id)

    def list_skills(self) -> List[SkillDefinition]:
        """Return all registered skills as a list."""
        return list(self._skills.values())

    def list_skill_ids(self) -> List[str]:
        """Return all registered skill IDs."""
        return list(self._skills.keys())

    # ── Task Matching ──────────────────────────────────────────────────

    def find_skills_for_task(
        self,
        description: str,
        domain: str,
        complexity: str,
    ) -> List[SkillDefinition]:
        """Find matching skills based on task description, domain, and complexity.

        Matching strategy (ordered by priority):
          1. Pattern match against description (regex)
          2. Domain overlap with skill's domain list
          3. Complexity falls within skill's range (only when pattern or domain matched)

        A skill must match on at least pattern OR domain to be included.
        Complexity alone is not sufficient — it only boosts the score of
        skills that already matched on content grounds.

        Results are sorted by match quality: pattern+domain+complexity > pattern+domain > pattern > domain.

        Args:
            description: The task description text.
            domain: The Hermes domain (code, analysis, reasoning, creative, operations, security).
            complexity: The task complexity (trivial, standard, complex, critical).

        Returns:
            List of matching SkillDefinition, sorted by relevance.
        """
        desc_lower = description.lower()
        scored: List[Tuple[int, SkillDefinition]] = []

        for skill in self._skills.values():
            pattern_match = skill.matches_description(desc_lower)
            domain_match = skill.domain_matches(domain)
            complexity_match = skill.complexity_matches(complexity)

            # A skill must match on pattern OR domain to qualify.
            # Complexity alone is not sufficient to avoid false positives.
            if not pattern_match and not domain_match:
                continue

            score = 0
            if pattern_match:
                score += 100  # Strongest signal
            if domain_match:
                score += 50
            if complexity_match:
                score += 25

            # Prefer skills with more matching capabilities
            if pattern_match and domain_match:
                score += 10  # Synergy bonus

            scored.append((score, skill))

        # Sort descending by score, break ties by skill_id for stability
        scored.sort(key=lambda pair: (-pair[0], pair[1].skill_id))
        return [skill for _, skill in scored]

    # ── Hermes Integration ─────────────────────────────────────────────

    def create_hermes_skill_records(self) -> List:
        """Convert registered skills to Hermes SkillRecord format.

        Each SkillDefinition is transformed into a SkillRecord that can be
        registered with HermesRouter.register_skill(). The execution_count
        is bootstrapped above Hermes's minimum threshold of 3 so that
        newly registered skills participate in fast-path routing immediately.

        Returns:
            List of SkillRecord instances ready for Hermes registration.
        """
        from nexus_os.engine.hermes import SkillRecord

        now = time.time()
        records = []

        for skill in self._skills.values():
            record = SkillRecord(
                skill_id=skill.skill_id,
                name=skill.name,
                task_type=skill.hermes_task_type,
                pattern=skill.pattern,
                recommended_model=skill.hermes_recommended_model,
                success_rate=0.85,  # Default confidence for catalog skills
                execution_count=skill.hermes_initial_execution_count,
                created_at=now,
                last_used=now,
            )
            records.append(record)

        logger.info("Created %d Hermes skill records", len(records))
        return records

    # ── Cost Estimation ────────────────────────────────────────────────

    def estimate_token_cost(self, skill_id: str, task_description: str) -> int:
        """Estimate token usage for a skill+task combination.

        Calculation:
          base_cost(token tier) × complexity_multiplier × description_length_factor

        The description_length_factor accounts for longer tasks requiring more
        input tokens: factor = 1 + (len(description) / 2000), capped at 3.0.

        Args:
            skill_id: The skill to estimate for.
            task_description: The task description to factor into the estimate.

        Returns:
            Estimated total token count (input + output).

        Raises:
            KeyError: If the skill_id is not registered.
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"Unknown skill: {skill_id!r}")

        base = _BASE_TOKEN_COSTS.get(skill.token_cost, 1000)

        # Use the midpoint of the skill's complexity range as a default multiplier
        min_idx = COMPLEXITY_ORDER[skill.complexity_range[0]]
        max_idx = COMPLEXITY_ORDER[skill.complexity_range[1]]
        mid_idx = (min_idx + max_idx) / 2.0
        # Map midpoint to complexity key: 0->trivial, 1->standard, 2->complex, 3->critical
        mid_key = COMPLEXITY_LEVELS[int(round(mid_idx))]
        complexity_mult = _TOKEN_COST_MULTIPLIERS.get(mid_key, 1.0)

        # Description length factor: longer tasks need more tokens
        desc_factor = 1.0 + min(len(task_description) / 2000.0, 2.0)

        estimated = int(base * complexity_mult * desc_factor)
        return estimated

    # ── Command Generation ─────────────────────────────────────────────

    def get_execution_command(self, skill_id: str, task_params: dict) -> List[str]:
        """Generate the shell command to execute a skill.

        The command format depends on the skill's execution_mode:
          - "cli": z-ai function --name <skill_id> --args '<json>'
          - "sdk": python -m <sdk_module>.<sdk_class> <params>
          - "api": curl -X POST <skill_id endpoint> -d '<json>'

        Args:
            skill_id: The skill to execute.
            task_params: Dictionary of parameters for the skill invocation.

        Returns:
            List of command arguments suitable for subprocess.run().

        Raises:
            KeyError: If the skill_id is not registered.
            ValueError: If required parameters are missing.
        """
        import json

        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"Unknown skill: {skill_id!r}")

        if not task_params:
            raise ValueError("task_params must not be empty")

        params_json = json.dumps(task_params)

        if skill.execution_mode == "cli":
            return ["z-ai", "function", "--name", skill.skill_id, "--args", params_json]
        elif skill.execution_mode == "sdk":
            if skill.sdk_module:
                return ["python", "-m", skill.sdk_module, params_json]
            else:
                # Fallback to z-ai CLI when no SDK module specified
                return ["z-ai", "function", "--name", skill.skill_id, "--args", params_json]
        elif skill.execution_mode == "api":
            return [
                "curl", "-X", "POST",
                f"https://api.z.ai/v1/skills/{skill.skill_id}/invoke",
                "-H", "Content-Type: application/json",
                "-d", params_json,
            ]
        else:
            return ["z-ai", "function", "--name", skill.skill_id, "--args", params_json]

    # ── Platform Skill Discovery ───────────────────────────────────────

    def discover_platform_skills(self, skills_dir: str) -> List[SkillDefinition]:
        """Scan the platform skills directory and auto-discover skills.

        Reads SKILL.md files from the given directory to extract skill metadata.
        Discovered skills that are not already in the registry are added.

        Each SKILL.md file should have YAML frontmatter with at minimum:
          name: skill-name
          description: Skill description

        Args:
            skills_dir: Path to the skills directory (e.g. /home/z/my-project/skills/).

        Returns:
            List of newly discovered SkillDefinition instances.

        Raises:
            FileNotFoundError: If skills_dir does not exist.
        """
        if not os.path.isdir(skills_dir):
            raise FileNotFoundError(f"Skills directory not found: {skills_dir!r}")

        discovered: List[SkillDefinition] = []

        for entry in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, entry)
            skill_md_path = os.path.join(skill_path, "SKILL.md")

            if not os.path.isdir(skill_path):
                continue
            if not os.path.isfile(skill_md_path):
                continue

            # Skip already registered skills
            if entry in self._skills:
                logger.debug("Skipping already-registered skill: %s", entry)
                continue

            # Parse SKILL.md frontmatter
            try:
                skill_def = self._parse_skill_md(entry, skill_md_path)
                if skill_def:
                    self._skills[skill_def.skill_id] = skill_def
                    discovered.append(skill_def)
                    logger.info("Discovered platform skill: %s", skill_def.skill_id)
            except Exception as e:
                logger.warning("Failed to parse SKILL.md for %s: %s", entry, e)

        logger.info("Discovered %d new platform skills from %s", len(discovered), skills_dir)
        return discovered

    @staticmethod
    def _parse_skill_md(skill_id: str, md_path: str) -> Optional[SkillDefinition]:
        """Parse a SKILL.md file and extract metadata from YAML frontmatter.

        Args:
            skill_id: The skill ID (derived from directory name).
            md_path: Path to the SKILL.md file.

        Returns:
            A SkillDefinition, or None if parsing fails.
        """
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read(8000)  # Read first 8KB for frontmatter
        except (OSError, UnicodeDecodeError):
            return None

        # Extract YAML frontmatter between --- delimiters
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return None

        frontmatter = frontmatter_match.group(1)

        # Parse name and description
        name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
        desc_match = re.search(r"^description:\s*(.+?)(?:\n\s|\n\w|\n$)", frontmatter, re.DOTALL)

        if not name_match:
            return None

        name = name_match.group(1).strip().strip("'\"")
        description = desc_match.group(1).strip() if desc_match else f"Platform skill: {skill_id}"

        # Infer domains from description keywords
        desc_lower = description.lower()
        domains = ["unknown"]
        domain_hints = {
            "code": ["code", "implement", "debug", "function", "api", "program"],
            "analysis": ["analyz", "data", "metric", "report", "statistics", "research"],
            "creative": ["write", "create", "design", "content", "image", "video"],
            "operations": ["automat", "configure", "deploy", "setup", "install"],
            "reasoning": ["reason", "logic", "solve", "plan", "strategy", "decision"],
        }
        for domain, keywords in domain_hints.items():
            if any(kw in desc_lower for kw in keywords):
                domains = [domain]
                break

        # Derive a basic pattern from the name
        name_words = re.findall(r"[a-z]+", name.lower())
        if name_words:
            pattern = r"|".join(re.escape(w) for w in name_words if len(w) > 2)
        else:
            pattern = re.escape(skill_id)

        return SkillDefinition(
            skill_id=skill_id,
            name=name,
            description=description,
            domains=domains,
            complexity_range=("standard", "complex"),
            capabilities=[skill_id],
            token_cost="medium",
            requires_api=False,
            execution_mode="cli",
            pattern=pattern,
        )

    # ── Introspection ──────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, object]:
        """Return registry statistics.

        Returns:
            Dictionary with counts by domain, execution mode, and token cost.
        """
        skills = list(self._skills.values())
        domain_counts: Dict[str, int] = {}
        mode_counts: Dict[str, int] = {}
        cost_counts: Dict[str, int] = {}

        for skill in skills:
            for d in skill.domains:
                domain_counts[d] = domain_counts.get(d, 0) + 1
            mode_counts[skill.execution_mode] = mode_counts.get(skill.execution_mode, 0) + 1
            cost_counts[skill.token_cost] = cost_counts.get(skill.token_cost, 0) + 1

        return {
            "total_skills": len(skills),
            "by_domain": domain_counts,
            "by_execution_mode": mode_counts,
            "by_token_cost": cost_counts,
        }

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def __iter__(self):
        return iter(self._skills.values())
