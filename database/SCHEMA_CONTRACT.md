# A 数据库接口约定

目标数据库：MySQL 8.4（SQL 同时兼容 MySQL 8.0）；InnoDB，utf8mb4。
数据库名称由执行者指定，建表脚本不含 CREATE DATABASE、DROP DATABASE 或 USE。
以下名称为交给 B、C、D 的统一约定。

## 表与字段

- categories(category_id BIGINT UNSIGNED PK AUTO_INCREMENT, name VARCHAR(80) UNIQUE NOT NULL)
- publishers(publisher_id BIGINT UNSIGNED PK AUTO_INCREMENT, name VARCHAR(160) UNIQUE NOT NULL)
- authors(author_id BIGINT UNSIGNED PK AUTO_INCREMENT, author_key VARCHAR(64) UNIQUE NOT NULL, name VARCHAR(120) NOT NULL)
- books(book_id BIGINT UNSIGNED PK AUTO_INCREMENT, isbn CHAR(13) ASCII UNIQUE NOT NULL, title VARCHAR(255) NOT NULL, category_id BIGINT UNSIGNED FK NOT NULL, publisher_id BIGINT UNSIGNED FK NOT NULL, publication_year SMALLINT UNSIGNED NOT NULL, description TEXT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
- book_authors(book_id BIGINT UNSIGNED FK, author_id BIGINT UNSIGNED FK, PRIMARY KEY(book_id, author_id))
- book_copies(copy_id BIGINT UNSIGNED PK AUTO_INCREMENT, book_id BIGINT UNSIGNED FK NOT NULL, barcode VARCHAR(40) UNIQUE NOT NULL, shelf_code VARCHAR(40) NOT NULL, status ENUM('IN_SERVICE','MAINTENANCE','WITHDRAWN') NOT NULL DEFAULT 'IN_SERVICE', acquired_at DATE NOT NULL)
- readers(reader_id BIGINT UNSIGNED PK AUTO_INCREMENT, reader_no VARCHAR(32) UNIQUE NOT NULL, name VARCHAR(100) NOT NULL, email VARCHAR(254) UNIQUE NULL, status ENUM('ACTIVE','SUSPENDED') NOT NULL DEFAULT 'ACTIVE', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
- loans(loan_id BIGINT UNSIGNED PK AUTO_INCREMENT, reader_id BIGINT UNSIGNED FK NOT NULL, copy_id BIGINT UNSIGNED FK NOT NULL, borrowed_at DATETIME NOT NULL, due_at DATETIME NOT NULL, returned_at DATETIME NULL, active_copy_id BIGINT UNSIGNED GENERATED ALWAYS AS (CASE WHEN returned_at IS NULL THEN copy_id ELSE NULL END) STORED, UNIQUE(active_copy_id))

所有 FK 使用 RESTRICT；book_authors 的 book_id 可 ON DELETE CASCADE。借阅历史不得级联删除。
日期规则：due_at > borrowed_at；returned_at IS NULL OR returned_at >= borrowed_at。
出版年范围 1450..2100；ISBN 固定 13 位数字，CSV 导入另外验证 ISBN-13 校验码。
只有 ACTIVE 读者可新增借阅，只有 IN_SERVICE 馆藏可借出。已有借阅可正常归还；归还后不得重开或修改历史；借阅对象及借出时间不可修改，due_at 可在日期合法前提下调整。
一本书目可有多份实体馆藏；一本实体同一时刻最多一条未归还记录。可借状态由馆藏状态及未归还借阅计算，不另存 available_count。
不实现登录、预约、罚款、限借数量；由团队后续按需扩展，不宣称已支持。

## CSV 书目导入契约

UTF-8 / UTF-8 BOM；表头：isbn,title,authors,publisher,publication_year,category,copies,shelf_code,description。
authors 格式：`a001:作者甲|a002:作者乙`；author_key 稳定且不可改名，同名不同作者用不同 key。
copies 为 1..1000 整数；新书生成 barcode=`ISBN-001`、`ISBN-002`...；acquired_at 固定导入当日。
按 ISBN 幂等：完全一致重复行跳过，不覆盖；元数据、作者集合、copies 或 shelf_code 冲突应使整个导入事务回滚并报告行号。
对同一文件内重复 ISBN，完全一致跳过，冲突回滚。全部文件先验证后事务写入。
仅接受 CSV，不依赖外部 API。示例书目和模拟数据必须标明 synthetic，不冒充真实馆藏。

## Python 脚本共享连接约定

Python 3.10+；依赖 PyMySQL>=1.1,<2、cryptography>=42（8.4 caching_sha2_password 本地 TCP 连接所需）。
scripts/db.py: `connect()` 从 DB_HOST(default 127.0.0.1), DB_PORT(default 3306), DB_USER(default library_app), DB_PASSWORD(required), DB_NAME(default library_project) 读取；charset=utf8mb4, autocommit=False, DictCursor。密码不写命令行/代码/日志。
连接函数可用空密码（仅隔离验证实例）；若变量不存在则报错。所有 SQL 值用参数绑定。
`python scripts/import_books.py data/books_sample.csv`
`python scripts/generate_data.py --books 1000 --readers 500 --loans 10000 --seed 2026 --as-of 2026-11-26 --output data/generated.sql` 仅生成 SQL，不连接数据库，目标必须是空表。
生成器为每书 3 个副本；包含可借、未归还、逾期和已归还情景。已归还历史不得在同一 copy 上时间重叠；历史全部早于活动借阅开始，活动借阅每 copy 最多 1 条。输出事务、显式列名，避开 active_copy_id，配 manifest.json。不要 SET FOREIGN_KEY_CHECKS=0 或修改 schema。
性能实验用独立空数据库导入 generated.sql；不得和 sample import 混用。

## 核心索引

books: uq_books_isbn(isbn), idx_books_title(title), idx_books_category(category_id, book_id), idx_books_publisher(publisher_id)
book_authors: PRIMARY(book_id,author_id), idx_book_authors_author(author_id,book_id)
book_copies: uq_copies_barcode(barcode), idx_copies_book_status(book_id,status,copy_id)
readers: uq_readers_no(reader_no), uq_readers_email(email)
loans: uq_loans_active_copy(active_copy_id), idx_loans_reader_open_due(reader_id,returned_at,due_at), idx_loans_copy_history(copy_id,borrowed_at), idx_loans_open_due(returned_at,due_at,reader_id)

实验：同一条读者借阅历史查询，比较正常优化器选择、IGNORE INDEX(idx_loans_reader_open_due)、FORCE INDEX(idx_loans_reader_open_due)。保留原始耗时、EXPLAIN FORMAT=JSON、结果相等校验；不物理删索引，不把强制用索引描述成优化器自动结果。独立连接测量，预热后交替顺序，多次统计中位数和 p95；说明含客户端往返。只报告真实测量。
