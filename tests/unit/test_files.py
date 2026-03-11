from __future__ import annotations

from pathlib import Path

from dude.files import FileController, extract_path_argument


def test_extract_path_argument_supports_quotes() -> None:
    path = extract_path_argument('create file "notes/todo.txt"', ("create file",))
    assert path == "notes/todo.txt"


def test_file_controller_can_create_and_read_file(tmp_path: Path) -> None:
    controller = FileController()

    create_result = controller.create_file('create file "notes.txt"', tmp_path)
    read_result = controller.read_file('read file "notes.txt"', tmp_path)

    assert create_result.exit_code == 0
    assert (tmp_path / "notes.txt").exists()
    assert read_result.exit_code == 0
    assert read_result.stdout_text == ""


def test_file_controller_can_make_and_list_directory(tmp_path: Path) -> None:
    controller = FileController()
    (tmp_path / "alpha.txt").write_text("alpha", encoding="utf-8")
    folder_result = controller.make_directory('create folder "docs"', tmp_path)
    list_result = controller.list_directory("list files in .", tmp_path)

    assert folder_result.exit_code == 0
    assert (tmp_path / "docs").is_dir()
    assert "alpha.txt" in list_result.stdout_text


def test_file_controller_can_copy_move_and_delete(tmp_path: Path) -> None:
    controller = FileController()
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")

    copy_result = controller.copy_path(
        'copy "source.txt" to "copied.txt"',
        tmp_path,
    )
    assert copy_result.exit_code == 0
    assert (tmp_path / "copied.txt").exists()

    move_result = controller.move_path(
        'move "copied.txt" to "moved.txt"',
        tmp_path,
    )
    assert move_result.exit_code == 0
    assert (tmp_path / "moved.txt").exists()

    delete_result = controller.delete_path(
        'delete file "moved.txt"',
        tmp_path,
    )

    assert delete_result.exit_code == 0
    assert not (tmp_path / "moved.txt").exists()


def test_file_controller_can_find_and_search_text(tmp_path: Path) -> None:
    controller = FileController()
    target = tmp_path / "docs" / "notes.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("todo: ship dude\n", encoding="utf-8")

    find_result = controller.find_file('find file "notes"', tmp_path)
    search_result = controller.search_text('search for "ship dude" in files', tmp_path)

    assert "docs/notes.txt" in find_result.stdout_text
    assert "docs/notes.txt" in search_result.stdout_text
