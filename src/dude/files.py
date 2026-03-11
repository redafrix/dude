from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileToolResult:
    executor: str
    command: list[str]
    exit_code: int
    stdout_text: str
    stderr_text: str


def extract_path_argument(request_text: str, keywords: tuple[str, ...]) -> str | None:
    quoted_match = re.search(r"[\"']([^\"']+)[\"']", request_text)
    if quoted_match:
        return quoted_match.group(1).strip()
    lowered = request_text.lower()
    for keyword in keywords:
        if keyword in lowered:
            start = lowered.index(keyword) + len(keyword)
            candidate = request_text[start:].strip().rstrip(".")
            return candidate or None
    return None


class FileController:
    def execute_request(
        self,
        tool_name: str,
        request_text: str,
        working_dir: Path,
    ) -> FileToolResult:
        if tool_name == "file_read":
            return self.read_file(request_text, working_dir)
        if tool_name == "file_mkdir":
            return self.make_directory(request_text, working_dir)
        if tool_name == "file_touch":
            return self.create_file(request_text, working_dir)
        if tool_name == "file_list_dir":
            return self.list_directory(request_text, working_dir)
        if tool_name == "file_copy":
            return self.copy_path(request_text, working_dir)
        if tool_name == "file_move":
            return self.move_path(request_text, working_dir)
        if tool_name == "file_delete":
            return self.delete_path(request_text, working_dir)
        if tool_name == "file_find":
            return self.find_file(request_text, working_dir)
        if tool_name == "file_search_text":
            return self.search_text(request_text, working_dir)
        raise RuntimeError(f"Unsupported file tool: {tool_name}")

    def read_file(self, request_text: str, working_dir: Path) -> FileToolResult:
        target = self._resolve_target(
            request_text,
            working_dir,
            ("read file", "show file", "open file", "cat "),
        )
        if not target.exists():
            return FileToolResult("files", [], 1, "", f"File does not exist: {target}")
        if not target.is_file():
            return FileToolResult("files", [], 1, "", f"Target is not a file: {target}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return FileToolResult("files", ["read", str(target)], 0, text, "")

    def make_directory(self, request_text: str, working_dir: Path) -> FileToolResult:
        target = self._resolve_target(
            request_text,
            working_dir,
            ("create directory", "make directory", "create folder", "make folder", "mkdir "),
        )
        target.mkdir(parents=True, exist_ok=True)
        return FileToolResult(
            "files",
            ["mkdir", "-p", str(target)],
            0,
            f"Created directory {target}.",
            "",
        )

    def create_file(self, request_text: str, working_dir: Path) -> FileToolResult:
        target = self._resolve_target(
            request_text,
            working_dir,
            ("create file", "make file", "touch "),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        return FileToolResult(
            "files",
            ["touch", str(target)],
            0,
            f"Created file {target}.",
            "",
        )

    def list_directory(self, request_text: str, working_dir: Path) -> FileToolResult:
        raw_target = extract_path_argument(
            request_text,
            ("list files in", "show files in", "list directory", "show directory"),
        )
        target = working_dir if raw_target is None else self._resolve_path(raw_target, working_dir)
        if not target.exists():
            return FileToolResult("files", [], 1, "", f"Directory does not exist: {target}")
        if not target.is_dir():
            return FileToolResult("files", [], 1, "", f"Target is not a directory: {target}")
        entries = sorted(path.name for path in target.iterdir())
        stdout_text = "\n".join(entries) if entries else "(empty directory)"
        return FileToolResult("files", ["ls", str(target)], 0, stdout_text, "")

    def copy_path(self, request_text: str, working_dir: Path) -> FileToolResult:
        source, destination = self._resolve_source_destination(request_text, working_dir)
        if not source.exists():
            return FileToolResult("files", [], 1, "", f"Source does not exist: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        return FileToolResult(
            "files",
            ["cp", "-r", str(source), str(destination)],
            0,
            f"Copied {source} to {destination}.",
            "",
        )

    def move_path(self, request_text: str, working_dir: Path) -> FileToolResult:
        source, destination = self._resolve_source_destination(request_text, working_dir)
        if not source.exists():
            return FileToolResult("files", [], 1, "", f"Source does not exist: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return FileToolResult(
            "files",
            ["mv", str(source), str(destination)],
            0,
            f"Moved {source} to {destination}.",
            "",
        )

    def delete_path(self, request_text: str, working_dir: Path) -> FileToolResult:
        target = self._resolve_target(
            request_text,
            working_dir,
            ("delete file", "remove file", "delete folder", "remove folder", "delete ", "remove "),
        )
        if not target.exists():
            return FileToolResult("files", [], 1, "", f"Target does not exist: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return FileToolResult(
            "files",
            ["rm", "-rf", str(target)],
            0,
            f"Deleted {target}.",
            "",
        )

    def find_file(self, request_text: str, working_dir: Path) -> FileToolResult:
        query = extract_path_argument(
            request_text,
            ("find file", "locate file", "search file named"),
        )
        if not query:
            raise RuntimeError(f"Could not determine a filename query from: {request_text}")
        query_lower = query.lower()
        matches: list[str] = []
        for path in working_dir.rglob("*"):
            if any(part.startswith(".") for part in path.parts):
                continue
            if path.is_file() and query_lower in path.name.lower():
                matches.append(str(path.relative_to(working_dir)))
            if len(matches) >= 50:
                break
        stdout_text = "\n".join(matches) if matches else "(no files matched)"
        return FileToolResult("files", ["find", query], 0, stdout_text, "")

    def search_text(self, request_text: str, working_dir: Path) -> FileToolResult:
        pattern = extract_path_argument(
            request_text,
            ("search for", "find text", "grep "),
        )
        if not pattern:
            raise RuntimeError(f"Could not determine a text search pattern from: {request_text}")
        if shutil.which("rg"):
            command = ["rg", "-n", pattern, str(working_dir)]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout_text = completed.stdout.strip() or "(no matches)"
            stderr_text = completed.stderr.strip()
            exit_code = 0 if completed.returncode in {0, 1} else completed.returncode
            return FileToolResult("files", command, exit_code, stdout_text, stderr_text)
        matches: list[str] = []
        for path in working_dir.rglob("*"):
            if not path.is_file() or any(part.startswith(".") for part in path.parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines, start=1):
                if pattern.lower() in line.lower():
                    matches.append(f"{path.relative_to(working_dir)}:{index}:{line.strip()}")
            if len(matches) >= 100:
                break
        stdout_text = "\n".join(matches) if matches else "(no matches)"
        return FileToolResult("files", ["search", pattern], 0, stdout_text, "")

    def _resolve_target(
        self,
        request_text: str,
        working_dir: Path,
        keywords: tuple[str, ...],
    ) -> Path:
        raw_target = extract_path_argument(request_text, keywords)
        if raw_target is None:
            raise RuntimeError(f"Could not determine a path from request: {request_text}")
        return self._resolve_path(raw_target, working_dir)

    def _resolve_path(self, raw_target: str, working_dir: Path) -> Path:
        path = Path(raw_target).expanduser()
        if not path.is_absolute():
            path = (working_dir / path).resolve()
        return path

    def _resolve_source_destination(
        self,
        request_text: str,
        working_dir: Path,
    ) -> tuple[Path, Path]:
        quoted = re.findall(r"[\"']([^\"']+)[\"']", request_text)
        if len(quoted) >= 2:
            return (
                self._resolve_path(quoted[0], working_dir),
                self._resolve_path(quoted[1], working_dir),
            )

        match = re.search(
            r"(?:copy|move)\s+(.+?)\s+to\s+(.+)$",
            request_text.strip(),
            flags=re.IGNORECASE,
        )
        if match is None:
            raise RuntimeError(
                "Could not determine source and destination paths. "
                "Use quoted paths for copy and move requests."
            )
        return (
            self._resolve_path(match.group(1).strip().rstrip("."), working_dir),
            self._resolve_path(match.group(2).strip().rstrip("."), working_dir),
        )
