# 图书借阅系统 / Library Borrowing System

DSC5003 课程项目 · Track 1 数据库应用开发  
DSC5003 course project · Track 1 database application development

[中文](#中文) · [English](#english) · [PowerShell commands](#powershell-commands)

## 中文

访客可以按书名前缀搜索并查看实体馆藏。演示读者登录后可以借书、还书，并查看个人借阅记录。Flask 同时提供网页和 API，业务数据写入 MySQL。演示书目、读者及借阅记录均为合成数据。

### 启动指南

1. 准备 Python 3.10+、PowerShell 和现代浏览器。数据库二选一。已有 MySQL 8.0/8.4 时使用本机 MySQL 和 `mysql` 命令行客户端。也可使用已启动的 Docker Desktop 或 Docker Engine 与 Compose v2，由 Compose 提供 MySQL 8.4。
2. 解压并进入含此 README 的 `library-system` 根目录。从同一个 PowerShell 窗口执行[共用命令](#powershell-commands)的 A 部分，再选择 B1（本机 `3306`）或 B2（Docker `3307`）。按 C 部分导入书目和演示借阅，再按 D 部分启动 Flask。在应用密码提示处输入之前为 `library_app` 设置的密码。
3. 打开 [图书借阅系统](http://127.0.0.1:8000/)。首次初始化后应有 6 种书目、13 份馆藏和 3 条演示借阅。也可打开 [图书查询 API](http://127.0.0.1:8000/api/books) 检查返回的 `items`。
4. 初始化时请使用新空库或首次启动的 Docker 数据卷。演示借阅 SQL 只导入一次。以后重启可跳过建表和导入，重新设置数据库连接环境变量和演示令牌后直接启动 Flask。需要停止应用时按 `Ctrl+C`，使用 Docker 时可在数据库目录运行 `docker compose stop`。

### 演示与交接

点击「读者登录」，输入演示令牌。刷新页面或退出后需重新登录。右上角可切换中英文，借阅时间按上海时区显示。

| 演示读者 | 本地令牌 |
| --- | --- |
| R-DEMO-001 | `local-demo-reader-1` |
| R-DEMO-002 | `local-demo-reader-2` |

- E 录屏可用读者一搜索 `合成书目：数据库`，展开「合成书目：数据库系统实践」，借出 `9780000000019-002`。打开「我的借阅」，核对新增记录和应还时间后还书。回到馆藏确认该副本恢复可借。需要展示数据库写入时，按联调记录中的 SQL 查询同一条 `loan_id`。 [联调记录和 SQL 核查](docs/integration-verification.md)
- D 写报告可使用数据库设计、ER 图、样例查询、联调记录及索引实验。索引实验使用 10 万条借阅记录的独立数据库，其运行方式见数据库说明。 [数据库设计](database/docs/database-design.md) · [ER 图](database/docs/er-diagram.png) · [样例查询](database/sql/02_sample_queries.sql) · [联调记录](docs/integration-verification.md) · [索引实验结果](database/evaluation/index-100k/benchmark-summary.md) · [数据库说明](database/README.md)

## English

Visitors can search by title prefix and inspect physical copies. Signed-in demo readers can borrow and return copies and view their own loan history. Flask serves the website and API on the same origin and stores the application data in MySQL. All demo books, readers, and loans are synthetic.

### Run locally

1. Install Python 3.10+ and use PowerShell and a modern browser. Either run MySQL 8.0/8.4 locally with the `mysql` client on PATH, or start Docker Desktop or Docker Engine with Compose v2 to run MySQL 8.4.
2. Extract the ZIP and open PowerShell in the `library-system` directory containing this README. Run section A of the [shared commands](#powershell-commands), then choose B1 for native MySQL on port `3306` or B2 for Docker on port `3307`. In the same shell, import the catalog and demo loans in section C and start Flask in section D. At the application password prompt, use the password you set for `library_app`.
3. Open the [Library Borrowing System](http://127.0.0.1:8000/). A fresh demo contains 6 titles, 13 physical copies, and 3 seeded loans. The [books API](http://127.0.0.1:8000/api/books) returns an `items` list.
4. Initialize an empty schema or a fresh Docker volume. Run the demo loan import once. On a subsequent run, set the database connection variables and demo tokens and start Flask directly. Use `Ctrl+C` to stop Flask. From the database directory, `docker compose stop` stops the Docker service and retains its data.

### Demo and handoff

Use the sign-in form with the demo tokens in the table above. Sign in again after refreshing the page or signing out. The language switch is in the header, and loan times are shown in the Asia/Shanghai timezone.

- For the video, sign in as reader one and search for `合成书目：数据库`. Expand the matching title, borrow copy `9780000000019-002`, open My Loans to check the new record and due time, and return it. Open the catalog again to confirm the copy is available. Use the same `loan_id` to show the database write. [Verification and SQL walkthrough](docs/integration-verification.md)
- For the report, use the database design, ER diagram, sample queries, and integration results. The index experiment uses a separate database with 100,000 loan records. [Design](database/docs/database-design.md) · [ER diagram](database/docs/er-diagram.png) · [Sample queries](database/sql/02_sample_queries.sql) · [Verification](docs/integration-verification.md) · [Index results](database/evaluation/index-100k/benchmark-summary.md) · [Database guide](database/README.md)

## PowerShell commands

### A. 安装依赖 / Install dependencies

从项目根目录执行 / Run from the project root.

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -r database/requirements.txt
Set-Location database
$env:DB_HOST = '127.0.0.1'
$env:DB_NAME = 'library_project'
$env:DB_USER = 'library_app'
```

### B1. 本机 MySQL / Native MySQL

选择 B1 后直接进入 C / After B1 continue to C.

```powershell
$env:DB_PORT = '3306'
mysql -h $env:DB_HOST -P $env:DB_PORT -u root -p --default-character-set=utf8mb4 --execute "CREATE DATABASE library_project CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql -h $env:DB_HOST -P $env:DB_PORT -u root -p --default-character-set=utf8mb4 $env:DB_NAME --execute "source sql/01_schema.sql"
mysql -h $env:DB_HOST -P $env:DB_PORT -u root -p
```

在刚打开的 MySQL 客户端中执行下面的 SQL，将占位文本换成实际密码。然后执行 `exit` 返回 PowerShell。  
In the MySQL client, replace the placeholder with the application password and run the SQL. Enter `exit` to return to PowerShell.

```sql
CREATE USER 'library_app'@'127.0.0.1' IDENTIFIED BY 'replace_with_your_app_password';
GRANT SELECT, INSERT, UPDATE ON library_project.* TO 'library_app'@'127.0.0.1';
```

```powershell
$appSecret = Read-Host 'library_app password' -AsSecureString
$env:DB_PASSWORD = [System.Net.NetworkCredential]::new('', $appSecret).Password
```

### B2. Docker MySQL 8.4

首次启动时 Compose 自动建表和创建应用账号。等待 `docker compose ps` 显示 `healthy` 后继续。  
Compose sets up the schema and application account on first start. Wait until `docker compose ps` shows `healthy`.

```powershell
$env:DB_PORT = '3307'
$appSecret = Read-Host 'Set the Docker application password' -AsSecureString
$env:DB_PASSWORD = [System.Net.NetworkCredential]::new('', $appSecret).Password
$rootSecret = Read-Host 'Set the Docker root password' -AsSecureString
$env:MYSQL_ROOT_PASSWORD = [System.Net.NetworkCredential]::new('', $rootSecret).Password
docker compose up -d
docker compose ps
```

### C. 导入样例数据 / Import sample data

```powershell
& ..\.venv\Scripts\python.exe scripts/import_books.py data/books_sample.csv
```

本机 MySQL 用下方第一种方式，Docker 用第二种。密码为应用账号密码。  
Use the first option for native MySQL or the second for Docker. Enter the application account password when prompted.

```powershell
# Native MySQL
mysql -h $env:DB_HOST -P $env:DB_PORT -u $env:DB_USER -p --default-character-set=utf8mb4 $env:DB_NAME --execute "source sql/03_demo_loans.sql"
```

```powershell
# Docker
docker compose cp ./sql/03_demo_loans.sql db:/tmp/library-demo-loans.sql
docker compose exec db mysql -h 127.0.0.1 -u library_app -p --default-character-set=utf8mb4 library_project --execute "source /tmp/library-demo-loans.sql"
```

### D. 启动应用 / Start the application

```powershell
Set-Location ../backend
$env:LIBRARY_READER_TOKENS = '{"local-demo-reader-1":"R-DEMO-001","local-demo-reader-2":"R-DEMO-002"}'
& ..\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 8000
```

## 项目结构 / Project layout

| 路径 / Path | 内容 / Contents |
| --- | --- |
| `frontend/` | 浏览器界面与双语文案 / Browser UI and translations |
| `backend/` | Flask API、借还事务、数据库连接 / Flask API, loan transactions, MySQL connection |
| `database/` | Schema、样例数据、脚本、测试和索引实验 / Schema, fixtures, scripts, tests, and index experiment |
| `docs/` | 整体联调记录 / End-to-end verification |

[后端 API / Backend API](backend/README.md)
