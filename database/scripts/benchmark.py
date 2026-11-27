"""Read-only, reproducible index comparison. Run on a dedicated synthetic database."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path

from db import connect


VARIANTS = {
    "optimizer": "",
    "ignore_reader_index": "IGNORE INDEX (idx_loans_reader_open_due)",
    "force_reader_index": "FORCE INDEX (idx_loans_reader_open_due)",
}
QUERY = """SELECT loan_id, copy_id, borrowed_at, due_at, returned_at
FROM loans {hint}
WHERE reader_id = %s
ORDER BY borrowed_at DESC, loan_id DESC
LIMIT 100"""


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def digest(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def percentile95(values):
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def choose_cases(distribution, rng):
    populated = sorted((row for row in distribution if row["loan_count"]),
                       key=lambda row: (row["loan_count"], row["reader_id"]))
    if not populated:
        raise ValueError("数据库没有借阅记录，请先向独立空数据库导入生成数据。")
    width = min(10, max(1, len(populated) // 10))
    high = rng.choice(populated[-width:])
    low = rng.choice(populated[:width])
    empty = [row for row in distribution if not row["loan_count"]]
    if empty:
        missing = dict(rng.choice(empty), label="无借阅读者", reader_exists=True)
    else:
        missing = {"reader_id": max(row["reader_id"] for row in distribution) + 1,
                   "loan_count": 0, "label": "无匹配记录（不存在的 reader_id）",
                   "reader_exists": False}
    return [dict(high, label="记录较多的读者", reader_exists=True),
            dict(low, label="记录较少的读者", reader_exists=True), missing]


def run_benchmark(output: Path, repeats: int, warmups: int, seed: int):
    rng = random.Random(seed)
    conn = connect()
    started = datetime.now(timezone.utc).isoformat()
    records, summaries = [], []
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cur.execute("""SELECT VERSION() AS server_version, DATABASE() AS database_name,
                @@version_comment AS server_edition,
                @@innodb_buffer_pool_size AS innodb_buffer_pool_size,
                @@transaction_isolation AS transaction_isolation,
                @@sql_mode AS sql_mode, @@character_set_connection AS connection_charset""")
            environment = cur.fetchone()
            environment.update(python=sys.version.split()[0], pymysql=version("PyMySQL"),
                               platform=platform.platform(), processor=platform.processor(),
                               logical_cpu_count=os.cpu_count(),
                               started_at_utc=started, repeats=repeats, warmups=warmups, seed=seed,
                               timer="perf_counter_ns; includes client/server round trip and fetchall",
                               snapshot="one REPEATABLE READ read-only consistent snapshot",
                               p95_method="nearest-rank ceil(0.95 * n)")
            counts = {}
            for table in ("books", "book_copies", "readers", "loans"):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                counts[table] = cur.fetchone()["n"]
            environment["table_counts"] = counts
            cur.execute("""SELECT r.reader_id, COUNT(l.loan_id) AS loan_count
                FROM readers r LEFT JOIN loans l ON l.reader_id = r.reader_id
                GROUP BY r.reader_id ORDER BY r.reader_id""")
            distribution = cur.fetchall()
            if not distribution:
                raise ValueError("数据库没有读者，请先导入模拟数据。")
            environment["reader_loan_distribution"] = {
                "minimum": min(row["loan_count"] for row in distribution),
                "maximum": max(row["loan_count"] for row in distribution),
                "mean": statistics.mean(row["loan_count"] for row in distribution),
                "readers_without_loans": sum(not row["loan_count"] for row in distribution),
            }
            cases = choose_cases(distribution, rng)
            for number, case in enumerate(cases, start=1):
                case["case"] = f"reader_{number}"
                reader = (case["reader_id"],)
                expected_digest = None
                variant_results = {}
                for variant, hint in VARIANTS.items():
                    query = QUERY.format(hint=hint)
                    cur.execute("EXPLAIN FORMAT=JSON " + query, reader)
                    raw_plan = next(iter(cur.fetchone().values()))
                    cur.execute(query, reader)
                    rows = cur.fetchall()
                    row_digest = digest(rows)
                    if expected_digest is None:
                        expected_digest = row_digest
                    elif row_digest != expected_digest:
                        raise AssertionError("索引变体返回了不同结果，终止实验。")
                    variant_results[variant] = {
                        "sql": query, "params": list(reader), "explain": json.loads(raw_plan),
                        "result_rows": len(rows), "result_sha256": row_digest, "samples_ms": []}
                variants = list(VARIANTS)
                for warmup in range(warmups):
                    order = variants[warmup % 3:] + variants[:warmup % 3]
                    for variant in order:
                        cur.execute(QUERY.format(hint=VARIANTS[variant]), reader)
                        cur.fetchall()
                for repeat in range(repeats):
                    # Rotate, then reverse every second block to balance first/last positions.
                    order = variants[repeat % 3:] + variants[:repeat % 3]
                    if (repeat // 3) % 2:
                        order = list(reversed(order))
                    for position, variant in enumerate(order, start=1):
                        start = time.perf_counter_ns()
                        cur.execute(QUERY.format(hint=VARIANTS[variant]), reader)
                        rows = cur.fetchall()
                        milliseconds = (time.perf_counter_ns() - start) / 1_000_000
                        if digest(rows) != expected_digest:
                            raise AssertionError("重复执行结果变化，终止实验。")
                        variant_results[variant]["samples_ms"].append(milliseconds)
                        records.append({"case": case["case"], "reader_id": reader[0],
                                        "variant": variant, "repeat": repeat + 1,
                                        "order_position": position, "elapsed_ms": milliseconds,
                                        "result_rows": len(rows)})
                for variant, result in variant_results.items():
                    values = result["samples_ms"]
                    result.update(median_ms=statistics.median(values), p95_ms=percentile95(values),
                                  minimum_ms=min(values), maximum_ms=max(values))
                    summaries.append({"case": case["case"], "label": case["label"],
                                      "reader_id": reader[0], "loan_count": case["loan_count"],
                                      "variant": variant, "median_ms": result["median_ms"],
                                      "p95_ms": result["p95_ms"], "result_rows": result["result_rows"]})
                case["variants"] = variant_results
    finally:
        conn.rollback()
        conn.close()
    output.mkdir(parents=True, exist_ok=True)
    report = {"environment": environment, "query_template": QUERY, "cases": cases,
              "all_results_equal": True,
              "limitations": ["合成数据上的局部只读实验，不等同于生产负载或总体可扩展性证明。",
                              "耗时包含客户端往返和结果传输；使用预热后的缓存，不宣称冷缓存结果。",
                              "IGNORE INDEX 只排除指定索引，优化器仍可选择其他索引。",
                              "FORCE INDEX 是受控变体，不代表优化器自主选择。",
                              "EXPLAIN 行数为估计值；未使用 EXPLAIN ANALYZE。",
                              "当高/低组记录数接近时，不应解读为强烈的数据倾斜。"]}
    (output / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    with (output / "timings.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    lines = ["# 索引对比实验（实际运行结果）", "",
             f"- MySQL：{environment['server_version']}；数据库：{environment['database_name']}",
             f"- 行数：{json.dumps(counts, ensure_ascii=False)}",
             f"- 固定随机种子：{seed}；每变体预热 {warmups} 次、测量 {repeats} 次。",
             "- 指标：客户端 perf_counter_ns 测得的查询加完整取回耗时；中位数与 nearest-rank p95，单位 ms。",
             "- 三种变体结果按稳定排序做 SHA-256 校验，全部一致。", "",
             "| 情形 | reader_id | 该读者全部借阅数 | 变体 | 返回行数 | 中位数 ms | p95 ms |",
             "|---|---:|---:|---|---:|---:|---:|"]
    for row in summaries:
        lines.append(f"| {row['label']} | {row['reader_id']} | {row['loan_count']} | {row['variant']} | "
                     f"{row['result_rows']} | {row['median_ms']:.4f} | {row['p95_ms']:.4f} |")
    lines += ["", "## 结果解释与限制", ""] + [f"- {item}" for item in report["limitations"]]
    lines += ["", "本次只比较 reader_id 过滤的借阅历史查询（最多返回 100 行）。不删除索引、不修改业务数据，",
              "每轮轮换查询顺序；完整执行计划、环境、原始耗时见 benchmark.json 与 timings.csv。",
              "报告应根据实际中位数和执行计划讨论索引效果；不要保证每个情形都提速。", ""]
    (output / "benchmark-summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evaluation/benchmark"))
    parser.add_argument("--repeats", type=int, default=21)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.repeats < 15 or args.warmups < 1:
        parser.error("--repeats 至少 15，--warmups 至少 1。")
    run_benchmark(args.output, args.repeats, args.warmups, args.seed)
    print(f"已完成实际只读实验：{args.output.resolve()}")


if __name__ == "__main__":
    main()
