"""app.compiler 的单元测试（仅依赖标准库，可直接 `python -m unittest discover`）。"""

from __future__ import annotations

import unittest

from app.compiler import START, CompileError, compile_commands, preview_change


def cmd(cid, channel, anchor=START, offset=0, duration=1000):
    return {
        "id": cid,
        "channel": channel,
        "anchor": anchor,
        "offset_ms": offset,
        "duration_ms": duration,
    }


def ids_of(timeline):
    return [entry["id"] for entry in timeline]


class TimelineTests(unittest.TestCase):
    def test_empty_input(self):
        result = compile_commands([])
        self.assertEqual(result, {"timeline": [], "conflicts": []})

    def test_single_start_item_and_defaults(self):
        result = compile_commands([{"id": "a", "channel": "cam", "duration_ms": 500}])
        self.assertEqual(len(result["timeline"]), 1)
        entry = result["timeline"][0]
        self.assertEqual(entry["start_ms"], 0)
        self.assertEqual(entry["end_ms"], 500)

    def test_chain_relative_to_anchor_end(self):
        # a: [0, 1000)；b 相对 a 结束时刻 +200，时长 300 -> [1200, 1500)
        result = compile_commands(
            [
                cmd("a", "cam", START, 0, 1000),
                cmd("b", "cam", "a", 200, 300),
            ]
        )
        by_id = {e["id"]: e for e in result["timeline"]}
        self.assertEqual((by_id["a"]["start_ms"], by_id["a"]["end_ms"]), (0, 1000))
        self.assertEqual((by_id["b"]["start_ms"], by_id["b"]["end_ms"]), (1200, 1500))

    def test_negative_offset_keeps_start_non_negative(self):
        # a: [1000, 2000)；b 相对 a 结束 -1500 -> [500, 600)
        result = compile_commands(
            [
                cmd("a", "cam", START, 1000, 1000),
                cmd("b", "cam", "a", -1500, 100),
            ]
        )
        by_id = {e["id"] for e in result["timeline"]}
        self.assertEqual(by_id, {"a", "b"})
        entries = {e["id"]: e for e in result["timeline"]}
        self.assertEqual(entries["b"]["start_ms"], 500)

    def test_sorted_by_start_then_id(self):
        # b 先开始；c 与 a 同起点，按 id 排序
        result = compile_commands(
            [
                cmd("a", "c1", START, 100, 100),
                cmd("b", "c1", START, 0, 100),
                cmd("c", "c1", START, 100, 100),
            ]
        )
        self.assertEqual(ids_of(result["timeline"]), ["b", "a", "c"])


class ConflictTests(unittest.TestCase):
    def test_touching_intervals_do_not_conflict(self):
        # a [0,1000)、b [1000,1200) 首尾相接
        result = compile_commands(
            [cmd("a", "cam", START, 0, 1000), cmd("b", "cam", "a", 0, 200)]
        )
        self.assertEqual(result["conflicts"], [])

    def test_overlap_pair_ordered_by_id_within_and_between_pairs(self):
        # c 与 a 重叠（c<a 字典序，对内应为 a,c）
        items = [
            cmd("a", "cam", START, 0, 1000),
            cmd("b", "cam", START, 2000, 100),
            cmd("c", "cam", START, 500, 100),
        ]
        result = compile_commands(items)
        pairs = [(c["a"], c["b"]) for c in result["conflicts"]]
        self.assertEqual(pairs, [("a", "c")])

    def test_multiple_pairs_sorted(self):
        # a[0,1000) b[100,200) c[150,300)：重叠对 (a,b)(a,c)(b,c)
        result = compile_commands(
            [
                cmd("a", "cam", START, 0, 1000),
                cmd("b", "cam", START, 100, 100),
                cmd("c", "cam", START, 150, 150),
            ]
        )
        pairs = [(c["a"], c["b"]) for c in result["conflicts"]]
        self.assertEqual(pairs, [("a", "b"), ("a", "c"), ("b", "c")])

    def test_different_channels_never_conflict(self):
        result = compile_commands(
            [
                cmd("a", "cam1", START, 0, 1000),
                cmd("b", "cam2", START, 0, 1000),
            ]
        )
        self.assertEqual(result["conflicts"], [])

    def test_conflict_payload_intervals_and_channel(self):
        result = compile_commands(
            [
                cmd("a", "cam", START, 0, 100),
                cmd("b", "cam", START, 50, 100),
            ]
        )
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["channel"], "cam")
        self.assertEqual(conflict["a_interval"], [0, 100])
        self.assertEqual(conflict["b_interval"], [50, 150])

    def test_break_early_when_reaching_non_overlapping_later_start(self):
        # a[0,100)，其后 b[100,200) 相接，c[100,200) 与 b 重叠、与 a 不重叠
        result = compile_commands(
            [
                cmd("a", "cam", START, 0, 100),
                cmd("b", "cam", START, 100, 100),
                cmd("c", "cam", START, 100, 100),
            ]
        )
        pairs = [(c["a"], c["b"]) for c in result["conflicts"]]
        self.assertEqual(pairs, [("b", "c")])


class ErrorTests(unittest.TestCase):
    def test_duplicate_id(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands(
                [cmd("a", "cam"), cmd("b", "cam"), cmd("a", "cam")]
            )
        self.assertEqual(ctx.exception.code, "DUPLICATE_ID")
        self.assertEqual(ctx.exception.details["duplicates"], ["a"])

    def test_reserved_and_empty_id(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("START", "cam")])
        self.assertEqual(ctx.exception.code, "INVALID_ID")
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("", "cam")])
        self.assertEqual(ctx.exception.code, "INVALID_ID")

    def test_empty_channel(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("a", "")])
        self.assertEqual(ctx.exception.code, "INVALID_CHANNEL")

    def test_non_positive_duration(self):
        for bad in (0, -1):
            with self.assertRaises(CompileError) as ctx:
                compile_commands([cmd("a", "cam", duration=bad)])
            self.assertEqual(ctx.exception.code, "INVALID_DURATION")

    def test_missing_anchor(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("a", "cam", anchor="ghost")])
        self.assertEqual(ctx.exception.code, "MISSING_ANCHOR")
        self.assertEqual(ctx.exception.details["ids"], ["a"])
        self.assertEqual(ctx.exception.details["anchors"], ["ghost"])

    def test_self_dependency_cycle(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("a", "cam", anchor="a")])
        self.assertEqual(ctx.exception.code, "DEPENDENCY_CYCLE")
        self.assertEqual(ctx.exception.details["cycle"], ["a", "a"])

    def test_two_node_cycle(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands(
                [cmd("a", "cam", anchor="b"), cmd("b", "cam", anchor="a")]
            )
        self.assertEqual(ctx.exception.code, "DEPENDENCY_CYCLE")
        cycle = ctx.exception.details["cycle"]
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"a", "b"})

    def test_cycle_with_unrelated_prefix_already_resolved(self):
        # a -> b 是已解析的独立前缀链；x -> z -> y -> x 构成环
        items = [
            cmd("a", "cam", START, 0, 10),
            cmd("b", "cam", "a", 0, 10),
            cmd("x", "cam", anchor="z", duration=10),
            cmd("y", "cam", anchor="x", duration=10),
            cmd("z", "cam", anchor="y", duration=10),
        ]
        with self.assertRaises(CompileError) as ctx:
            compile_commands(items)
        self.assertEqual(ctx.exception.code, "DEPENDENCY_CYCLE")
        cycle = ctx.exception.details["cycle"]
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"x", "y", "z"})

    def test_negative_start_from_start_anchor(self):
        with self.assertRaises(CompileError) as ctx:
            compile_commands([cmd("a", "cam", START, -10, 100)])
        self.assertEqual(ctx.exception.code, "NEGATIVE_START")

    def test_negative_start_through_chain(self):
        # a [100, 200)；b 相对 a 结束 -300 -> -100，非法
        with self.assertRaises(CompileError) as ctx:
            compile_commands(
                [
                    cmd("a", "cam", START, 100, 100),
                    cmd("b", "cam", "a", -300, 10),
                ]
            )
        self.assertEqual(ctx.exception.code, "NEGATIVE_START")
        self.assertEqual(ctx.exception.details["id"], "b")
        self.assertEqual(ctx.exception.details["start_ms"], -100)

    def test_negative_start_reported_only_after_cycle_check(self):
        # 存在环时优先报环，避免对环上节点产生无意义时间
        with self.assertRaises(CompileError) as ctx:
            compile_commands(
                [
                    cmd("a", "cam", anchor="b", offset=-10, duration=10),
                    cmd("b", "cam", anchor="a", offset=-10, duration=10),
                ]
            )
        self.assertEqual(ctx.exception.code, "DEPENDENCY_CYCLE")


class PreviewTests(unittest.TestCase):
    def base_items(self):
        # a[0,1000) b[1000,1500) e[1500,1600)（e 锚定 b）
        # f[1400,1600) c[2000,2500)，均在 main 通道
        return [
            cmd("a", "main", START, 0, 1000),
            cmd("b", "main", "a", 0, 500),
            cmd("e", "main", "b", 0, 100),
            cmd("f", "main", START, 1400, 200),
            cmd("c", "main", START, 2000, 500),
        ]

    def test_changed_ids_include_anchor_propagation(self):
        # b 时长 500 -> 1500：b 变为 [1000,2500)；锚定 b 的 e 随动为 [2500,2600)
        result = preview_change(self.base_items(), {"id": "b", "duration_ms": 1500})
        self.assertEqual(result["changed_ids"], ["b", "e"])

    def test_added_and_removed_conflicts_with_corresponding_intervals(self):
        result = preview_change(self.base_items(), {"id": "b", "duration_ms": 1500})
        added = [(x["channel"], x["a"], x["b"]) for x in result["added_conflicts"]]
        removed = [(x["channel"], x["a"], x["b"]) for x in result["removed_conflicts"]]
        # b 拉长后与 c 重叠（新增）；e 随动后不再与 f 重叠（消失）
        self.assertEqual(added, [("main", "b", "c")])
        self.assertEqual(removed, [("main", "e", "f")])
        # 新增对携带改动后版本的区间
        self.assertEqual(result["added_conflicts"][0]["a_interval"], [1000, 2500])
        self.assertEqual(result["added_conflicts"][0]["b_interval"], [2000, 2500])
        # 消失对携带改动前版本的区间
        self.assertEqual(result["removed_conflicts"][0]["a_interval"], [1500, 1600])
        self.assertEqual(result["removed_conflicts"][0]["b_interval"], [1400, 1600])

    def test_offset_change_only(self):
        # b 偏移 0 -> -500：b[500,1000) 与 a[0,1000) 重叠（新增）；
        # e 随动为 [1000,1100)，原 (b,f)(e,f) 冲突均消失
        result = preview_change(self.base_items(), {"id": "b", "offset_ms": -500})
        self.assertEqual(result["changed_ids"], ["b", "e"])
        added = [(x["a"], x["b"]) for x in result["added_conflicts"]]
        removed = [(x["a"], x["b"]) for x in result["removed_conflicts"]]
        self.assertEqual(added, [("a", "b")])
        self.assertEqual(removed, [("b", "f"), ("e", "f")])

    def test_change_both_fields(self):
        result = preview_change(
            self.base_items(), {"id": "b", "offset_ms": 0, "duration_ms": 1500}
        )
        self.assertEqual(result["changed_ids"], ["b", "e"])

    def test_noop_change_yields_empty_diff(self):
        result = preview_change(
            self.base_items(), {"id": "b", "offset_ms": 0, "duration_ms": 500}
        )
        self.assertEqual(
            result,
            {"changed_ids": [], "added_conflicts": [], "removed_conflicts": []},
        )

    def test_input_items_are_not_mutated(self):
        items = self.base_items()
        preview_change(items, {"id": "b", "duration_ms": 1500})
        self.assertEqual(items, self.base_items())

    def test_change_does_not_override_other_fields(self):
        # e 仍锚定 b（否则 e 不会随 b 的时长改动而移动），其他字段原样保留
        result = preview_change(self.base_items(), {"id": "b", "duration_ms": 1500})
        self.assertEqual(result["changed_ids"], ["b", "e"])

    def test_pair_present_in_both_versions_is_not_diffed(self):
        # (b,c) 在两个版本中都存在、仅区间平移，不应计入新增/消失
        items = [
            cmd("a", "main", START, 0, 1000),
            cmd("b", "main", "a", 0, 500),   # [1000,1500)
            cmd("c", "main", START, 1200, 500),  # [1200,1700)
        ]
        result = preview_change(items, {"id": "a", "duration_ms": 800})
        self.assertEqual(result["added_conflicts"], [])
        self.assertEqual(result["removed_conflicts"], [])
        self.assertEqual(result["changed_ids"], ["a", "b"])

    def test_multiple_added_pairs_sorted_by_a_b_channel(self):
        # t 改动后 [50,550)，同时与 q、r、s 重叠
        items = [
            cmd("q", "main", START, 0, 100),    # [0,100)
            cmd("r", "main", START, 200, 100),  # [200,300)
            cmd("s", "main", START, 400, 100),  # [400,500)
            cmd("t", "main", "q", 0, 50),       # [100,150)，原本与谁都不冲突
        ]
        result = preview_change(
            items, {"id": "t", "offset_ms": -50, "duration_ms": 500}
        )
        pairs = [(c["a"], c["b"]) for c in result["added_conflicts"]]
        self.assertEqual(pairs, [("q", "t"), ("r", "t"), ("s", "t")])
        self.assertEqual(result["removed_conflicts"], [])
        self.assertEqual(result["changed_ids"], ["t"])

    def test_unknown_change_id(self):
        with self.assertRaises(CompileError) as ctx:
            preview_change(self.base_items(), {"id": "ghost", "offset_ms": 1})
        self.assertEqual(ctx.exception.code, "UNKNOWN_CHANGE_ID")
        self.assertEqual(ctx.exception.details["id"], "ghost")

    def test_reserved_id_is_unknown_change_target(self):
        with self.assertRaises(CompileError) as ctx:
            preview_change(self.base_items(), {"id": START, "offset_ms": 1})
        self.assertEqual(ctx.exception.code, "UNKNOWN_CHANGE_ID")

    def test_change_without_any_value(self):
        with self.assertRaises(CompileError) as ctx:
            preview_change(self.base_items(), {"id": "b"})
        self.assertEqual(ctx.exception.code, "INVALID_CHANGE")

    def test_zero_is_a_valid_new_value(self):
        # offset_ms=0 是显式提供的新值，不得被当成“未提供”
        result = preview_change(self.base_items(), {"id": "b", "offset_ms": 0})
        self.assertEqual(
            result,
            {"changed_ids": [], "added_conflicts": [], "removed_conflicts": []},
        )

    def test_base_array_errors_take_precedence(self):
        items = self.base_items() + [cmd("b", "main")]  # 重复 id
        with self.assertRaises(CompileError) as ctx:
            preview_change(items, {"id": "b", "offset_ms": 1})
        self.assertEqual(ctx.exception.code, "DUPLICATE_ID")

    def test_modified_compile_errors_are_reused(self):
        with self.assertRaises(CompileError) as ctx:
            preview_change(self.base_items(), {"id": "b", "duration_ms": 0})
        self.assertEqual(ctx.exception.code, "INVALID_DURATION")
        with self.assertRaises(CompileError) as ctx:
            preview_change(self.base_items(), {"id": "a", "offset_ms": -1})
        self.assertEqual(ctx.exception.code, "NEGATIVE_START")


class LongChainTests(unittest.TestCase):
    def test_deep_chain_does_not_recurse(self):
        # 迭代 DFS 应能处理远超默认递归深度的依赖链
        n = 5000
        items = [cmd("c0", "cam", START, 0, 1)]
        for i in range(1, n):
            items.append(cmd(f"c{i}", "cam", f"c{i-1}", 0, 1))
        result = compile_commands(items)
        self.assertEqual(len(result["timeline"]), n)
        last = result["timeline"][-1]
        self.assertEqual(last["id"], f"c{n-1}")
        self.assertEqual(last["start_ms"], n - 1)


if __name__ == "__main__":
    unittest.main()
