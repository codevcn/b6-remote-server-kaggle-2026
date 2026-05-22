import os


def print_tree(root_path, file_handle, prefix="", exclude_dirs=None):
    if exclude_dirs is None:
        exclude_dirs = []

    entries = sorted(os.listdir(root_path))
    entries = [
        e
        for e in entries
        if os.path.isdir(os.path.join(root_path, e))
        or os.path.isfile(os.path.join(root_path, e))
    ]

    for i, entry in enumerate(entries):
        path = os.path.join(root_path, entry)
        connector = "└── " if i == len(entries) - 1 else "├── "

        # Loại trừ thư mục không muốn in
        if os.path.isdir(path) and entry in exclude_dirs:
            continue

        file_handle.write(f"{prefix}{connector}{entry}\n")

        if os.path.isdir(path):
            extension = "    " if i == len(entries) - 1 else "│   "
            print_tree(path, file_handle, prefix + extension, exclude_dirs)


# Ví dụ sử dụng
if __name__ == "__main__":
    root_directory = "."  # Thư mục gốc cần duyệt
    excluded = [
        "node_modules",
        "__pycache__",
        ".git",
        ".husky",
        ".vscode",
        "dist",
        "migrations",
    ]  # Các thư mục cần loại trừ
    output_file = "project_tree.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Tree view of: {os.path.abspath(root_directory)}\n\n")
        print_tree(root_directory, f, exclude_dirs=excluded)

    print(f"Cây thư mục đã được ghi vào file: {output_file}")
