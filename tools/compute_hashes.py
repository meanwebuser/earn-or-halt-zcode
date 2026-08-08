"""Compute SHA-256 sums for all source files in the project."""
import hashlib
import os
from pathlib import Path

SKIP_DIRS = {
    ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    "build", "dist", ".git", ".venv", "venv", "env",
    "earn_or_halt.egg-info", "*.egg-info", "data", "logs",
}
SKIP_FILES = {".DS_Store", "Thumbs.db", "earn_or_halt.db"}


def should_skip(p: Path) -> bool:
    parts = set(p.parts)
    for skip in SKIP_DIRS:
        if skip in parts:
            return True
    if p.name in SKIP_FILES:
        return True
    return False


def main() -> int:
    root = Path(__file__).parent.parent
    files: list[Path] = []
    for ext in (".py", ".md", ".sol", ".toml", ".json", ".txt", ".yml",
                ".yaml", "Dockerfile", ".gitignore", "LICENSE"):
        if ext == "Dockerfile":
            files.extend(root.rglob("Dockerfile"))
        elif ext == ".gitignore":
            files.extend(root.rglob(".gitignore"))
        elif ext == "LICENSE":
            files.extend(root.rglob("LICENSE"))
        else:
            files.extend(root.rglob(f"*{ext}"))

    files = sorted({f for f in files if f.is_file() and not should_skip(f)})
    out_lines: list[str] = []
    for f in files:
        rel = f.relative_to(root)
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        out_lines.append(f"{digest}  {rel}")

    out_path = root / "FILE_SHA256SUMS.txt"
    out_path.write_text("\n".join(out_lines) + "\n")
    print(f"wrote {out_path} with {len(out_lines)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
