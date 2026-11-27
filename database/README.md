# Library Borrowing System - Part A 数据库交付包

对应课程 **Track 1: Database Application Development**。仅完成 A 的数据库职责，供 B 接后端、C 联调、D 汇总报告。当前尚未上传 GitHub；这个目录可以直接作为小组仓库的 `database/` 目录提交。

## 已交付

| 文件/目录 | 用途 | 交给谁 |
|---|---|---|
| sql/01_schema.sql | 8 张表、主外键、唯一约束、CHECK、索引、业务保护触发器 | B/C，GitHub |
| scripts/import_books.py + data/books_sample.csv | 可重复执行的原子 CSV 书目导入；6 本合成书目、13 份馆藏 | B/C，GitHub |
| scripts/generate_data.py | 固定随机种子生成合成数据、SQL 和校验清单 | B/D，GitHub |
| sql/02_sample_queries.sql | 搜索、馆藏状态、历史、逾期、可借统计、热门书 6 类查询 | B/D/E |
| sql/03_demo_loans.sql | 演示读者与已还、逾期、未到期借阅，单次导入 | B/C/E |
| docs/er-diagram.* | ER 源码、SVG、PNG 和独立矢量 PDF | D |
| docs/database-design.md / .pdf | 表结构、3NF、索引、约束、实验、边界说明 | D |
| docs/backend-handoff.md | 借还事务、字段和错误处理约定 | B/C |
| tests/ | 离线测试与真实数据库集成测试 | A/B |
| evaluation/ | 实测日志、环境、执行计划和索引原始数据 | D |

**所有示例与实验数据均为 synthetic（合成数据）**，并非真实出版物、读者或借阅流水。`978...`/`979...` 只是校验码合法的测试编号，不代表真实 ISBN 分配。

## 环境

- 推荐 MySQL 8.4，InnoDB，utf8mb4；SQL 兼容 MySQL 8.0。
- Python 3.10+；`python -m pip install -r requirements.txt`。
- 本包实际验证引擎为本机 **MySQL 8.0.12**；CHECK 从 8.0.16 才真正执行，因此关键规则另以触发器实现并已实测。MySQL 8.4 Docker 部署文件已提供，但本次没有 Docker 环境，不能把 8.4 运行记为已验证。建议小组最终部署后再执行同一组测试。
- 从仓库根目录执行 `cd database` 后，再在此目录运行以下 PowerShell 命令。`mysql` 需要在 PATH 中；也可以换成 mysql.exe 的完整路径。
- 日期统一为 Asia/Shanghai 的本地 DATETIME。实验基准固定 `2026-11-26 12:00:00`，不随运行当天变化。

## 方式一：已有 MySQL，约 5 分钟初始化演示库

1. 以 owner/root 登录并建一个**新的空数据库**：

```powershell
mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 --execute "CREATE DATABASE library_project CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 library_project --execute "source sql/01_schema.sql"
```

建表脚本不删除数据库、不重复建表；重复运行会报错。不要对已有小组数据执行初始化。请勿使用 mysql 的 `--force`（它会在出错后继续执行）。不要用 PowerShell `Get-Content ... | mysql`，以免中文编码被终端转换。

2. owner 创建后端账号；进入 mysql 交互界面运行以下示例，替换密码：

```sql
CREATE USER 'library_app'@'127.0.0.1' IDENTIFIED BY '替换为你设置的密码';
GRANT SELECT, INSERT, UPDATE ON library_project.* TO 'library_app'@'127.0.0.1';
```

3. 配置 Python 环境变量并导入：

```powershell
python -m pip install -r requirements.txt
$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '3306'
$env:DB_USER = 'library_app'
$env:DB_NAME = 'library_project'
$databaseSecret = Read-Host '输入数据库密码' -AsSecureString
$env:DB_PASSWORD = [System.Net.NetworkCredential]::new('', $databaseSecret).Password
python scripts/import_books.py data/books_sample.csv
```

首次预期 `books_inserted: 6, copies_inserted: 13`；再次执行预期 `books_inserted: 0, books_skipped: 6`。同一 ISBN 元数据/作者/馆藏数量或书架冲突会整体回滚，避免悄悄覆盖已有书目。程序只读取环境变量，**不自动加载 .env 文件**。

4. 导入演示借阅并执行样例查询（mysql 的 `-p` 会另行提示密码）：

```powershell
mysql -h 127.0.0.1 -P 3306 -u library_app -p --default-character-set=utf8mb4 library_project --execute "source sql/03_demo_loans.sql"
mysql -h 127.0.0.1 -P 3306 -u library_app -p --default-character-set=utf8mb4 library_project --execute "source sql/02_sample_queries.sql"
```

演示借阅只运行一次；重复会因读者编号唯一而报错。演示基准时刻应有 3 位读者、3 条借阅记录（1 条已还、1 条逾期未还、1 条未到期）。两条未还记录占用不同副本，其余在服馆藏仍可借。Q1 前缀为“合成书目：数据库”，与合成书名一致；Q2 查询第一本书，Q3 查询 R-DEMO-001。

## 方式二：Docker MySQL 8.4

先安装并启动 Docker。保持上述 DB_PASSWORD 环境变量，再设置 root 初始化密码：

```powershell
$rootSecret = Read-Host '设置 Docker MySQL root 密码' -AsSecureString
$env:MYSQL_ROOT_PASSWORD = [System.Net.NetworkCredential]::new('', $rootSecret).Password
docker compose up -d
docker compose ps
$env:DB_PORT = '3307'
```

等待 healthy。**仅在新 volume 第一次启动时**自动执行 01_schema.sql 和受限应用权限脚本；不需要再次手工建表。数据库名 library_project、用户 library_app、密码为 DB_PASSWORD。然后执行 Python CSV 导入，再使用上述 mysql 命令（端口改为 3307）导入演示借阅。若本机没有 mysql 客户端，可进入 `docker compose exec db mysql -u library_app -p library_project`，将演示 SQL 内容在交互客户端执行；不要在重复使用的 volume 中重放 schema。Docker 初始化环境变量只影响首次初始化，不会修改已有卷里的密码。

## 可复现测试

离线测试无需连接数据库：

```powershell
python -m unittest discover -s tests -p test_data_scripts.py -v
```

数据库测试必须另建空库 `library_test` 并加载 schema，使用该库的 owner 账号（并发测试需清理自身 fixture，普通应用账号没有 DELETE 权限）：

```powershell
# 先用 owner 创建 library_test 并加载 schema，方法同方式一。
$env:DB_NAME = 'library_test'
$env:DB_USER = 'root'
# 重新设置 DB_PASSWORD 为该 owner 的密码，然后：
python -m unittest discover -s tests -p test_database.py -v
```

导入集成测试单独运行：它只操作固定专用库 `library_importcheck`，需要具有 CREATE DATABASE、建表、TRIGGER 和清理测试数据权限的 owner 账号；首次自动建库并加载 schema。此库名必须保留作测试，不能用来保存真实数据。重复运行会精准清理匹配内容的 6 条合成示例书目；若被借阅历史引用则拒绝清理。

```powershell
$env:RUN_IMPORT_DB_TESTS = '1'
# mysql 不在 PATH 时，设置 MYSQL_BIN 为 mysql.exe 完整路径。
python tests/test_import_database.py
```

未设置 RUN_IMPORT_DB_TESTS=1 时，该测试会跳过，不能把 skip 记为通过。不要对真实馆藏库运行测试。实际结果见 evaluation/；本次 11 项离线 + 18 项数据库 + 9 项导入测试，合计 38 项全部实际通过。

## 10 万借阅记录索引实验

生成器只生成 SQL，不连接数据库。为实验**另建新的空库** `library_benchmark` 并加载 schema。不要向 CSV 演示库叠加此数据。

```powershell
python scripts/generate_data.py --books 2000 --readers 1000 --loans 100000 --seed 2026 --as-of 2026-11-26 --output data/generated.sql
mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 library_benchmark --execute "source data/generated.sql"
$env:DB_NAME = 'library_benchmark'
# benchmark 只读，设置此库可 SELECT 的账号/密码。
python scripts/benchmark.py --output evaluation/my-index-100k --repeats 21 --warmups 3 --seed 2026
```

`data/generated.manifest.json` 记录规模、固定参数、场景数量和 SQL SHA256。提交代码时可忽略可再生的 generated.sql，大文件无需上传 GitHub；随附 ZIP 保留本次数据方便复查。

实验比较正常优化器、IGNORE 指定读者索引、FORCE 指定索引，分记录多/少/无匹配 3 类读者，每类每变体预热 3 次、测量 21 次。输出每次耗时 CSV、完整 EXPLAIN JSON、结果摘要校验和、中位数及 p95。IGNORE 只排除这个索引，其他索引仍存在；FORCE 只是受控变体。计时含客户端往返和取数，是单客户端热缓存实验，不等于生产吞吐或完整扩展性证明。

## GitHub 与交接

小组建好空 GitHub 仓库后，将本目录内容上传（也可放在已有仓库的 database/）。保留 README、SQL、scripts、tests、data/books_sample.csv、docs 与 evaluation；不要上传密码、.env、.venv、__pycache__。生成大数据用命令重建即可。按小组确定的仓库许可证再添加 LICENSE，不凭空填写许可。

交 B：schema、CSV 导入、demo、backend-handoff；交 C：环境/初始化步骤和样例字段；交 D：设计 PDF、ER 图、实测证据与索引结果。D 仍需补真实组员姓名/本科专业、各人实际贡献、完整系统架构、前后端评估、GitHub 链接及 E 的视频链接，最终按老师要求命名 `XXXX-report.pdf`。本包不是整组最终报告，也未包含前后端或视频。

## 参考资料

SQL 实现与项目文件为本次编写；以下官方资料用于核对数据库行为，报告可引用：

- [MySQL 8.4 - CHECK constraints](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)
- [MySQL 8.0.16 引入 CHECK 执行](https://dev.mysql.com/blog-archive/mysql-8-0-16-introducing-check-constraint/)
- [MySQL 8.4 - UNIQUE index and NULL](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)
- [MySQL 8.4 - Range optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)
- [MySQL 8.4 - EXPLAIN](https://dev.mysql.com/doc/refman/8.4/en/using-explain.html)
- [MySQL 8.4 - Index hints](https://dev.mysql.com/doc/refman/8.4/en/index-hints.html)

组员应按课程关于辅助工具的具体规定披露使用情况，并理解、运行与说明自己负责的代码；不要将未运行的 8.4 部署、后端或视频描述成已完成。
