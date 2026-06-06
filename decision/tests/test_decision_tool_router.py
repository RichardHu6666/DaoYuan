import unittest

from decision.models import ToolRecord
from decision.tool_router import match_tool


class ToolRouterTests(unittest.TestCase):
    def test_match_jw_tool(self) -> None:
        tools = [
            ToolRecord(name="教务系统", website="https://jw.example.com", description="成绩和课表"),
            ToolRecord(name="图书馆", website="https://lib.example.com", description="馆藏"),
        ]
        tool = match_tool("我想查成绩", tools)
        self.assertIsNotNone(tool)
        assert tool is not None
        self.assertEqual(tool.name, "教务系统")


if __name__ == "__main__":
    unittest.main()
