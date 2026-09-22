from __future__ import annotations

import unittest

from tests.helpers import project_root, required_project_files


class ProjectStructureTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        root = project_root()
        missing = [relative for relative in required_project_files() if not (root / relative).is_file()]
        self.assertFalse(
            missing,
            "Archivos requeridos ausentes:\n- " + "\n- ".join(missing),
        )

    def test_sensitive_local_paths_are_not_required(self) -> None:
        root = project_root()
        self.assertFalse((root / ".env.example").is_dir())
        self.assertFalse((root / "research" / "data_lake").exists())


if __name__ == "__main__":
    unittest.main()
