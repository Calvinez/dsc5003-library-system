# 图书馆借阅系统：A 数据库设计说明

课程路线：Track 1。本文是交给 D 的数据库报告素材，不代替整组最终 `XXXX-report.pdf`。成员姓名、专业和实际贡献由 D 按真实情况汇总；本次不虚构这些信息。

## 1. 目标、业务范围与设计假设

本系统帮助读者检索馆藏、办理借还、查看历史，并帮助管理员查询逾期与可借数量。A 负责关系数据库、书目导入、模拟数据、ER 图、结构说明与索引实验；API、界面、权限认证及视频由对应成员完成。

一条书目代表一个 ISBN 出版版本，可有多份独立条码的实体馆藏；书目可以由多位作者共同创作。作者使用稳定 author_key 标识，同名不同人不合并。每书目本期只属一个类别、一个出版社。借阅对象是具体 copy_id，不是抽象书目。暂停读者不准新增借阅，但可以归还。维护/注销副本不能借出，且在借副本须先归还再改变状态。

技术：MySQL / InnoDB / utf8mb4，Python 3.10+ 和 PyMySQL。推荐部署 MySQL 8.4；实际验证使用本机 MySQL 8.0.12 的独立实例。关键约束通过触发器与唯一索引保护，以兼容旧版尚未执行 CHECK 的情况。未实测的 8.4 部署不计作通过。

## 2. ER 模型与关系

完整图见 er-diagram.svg / .png / .pdf；可编辑 Mermaid 源码为 er-diagram.mmd。

- categories 1 : 0..N books；每本书必须且只关联一个类别。
- publishers 1 : 0..N books；每本书必须且只关联一个出版社。
- books 与 authors 通过 book_authors 构成 M:N。桥表每行恰好对应一个书目和一个作者；联合主键防止重复关联。CSV 导入保证至少一位作者，DDL 本身不强制父表至少有一条桥表记录。
- books 1 : 0..N book_copies；每个副本恰属一个书目。CSV 导入要求至少一份，DDL 允许暂未采购副本的书目。
- readers 1 : 0..N loans，book_copies 1 : 0..N loans；借阅必须关联一个读者和一个副本。

“同一本实体最多一条当前借阅”属于条件唯一约束，在 ER 基数之外单独表达。

## 3. 表结构与数据字典

PK=主键，FK=外键，UQ=唯一；全部 ID 为 BIGINT UNSIGNED，实体主键自增。除明确注明 NULL 的字段外均 NOT NULL。实际完整定义以 sql/01_schema.sql 为准。

| 表 | 字段 | 类型与约束 | 含义 |
|---|---|---|---|
| categories | category_id; name | PK; VARCHAR(80) UQ | 图书分类 |
| publishers | publisher_id; name | PK; VARCHAR(160) UQ | 出版社/出版品牌 |
| authors | author_id; author_key; name | PK; VARCHAR(64) ASCII UQ; VARCHAR(120) | 稳定外部编号、显示姓名（可同名） |
| books | book_id; isbn; title | PK; CHAR(13) ASCII UQ; VARCHAR(255) | 出版版本及书名 |
| books | category_id; publisher_id | FK -> categories; FK -> publishers | 不重复存类别或出版社名称 |
| books | publication_year; description; created_at | SMALLINT UNSIGNED; TEXT NULL; DATETIME DEFAULT CURRENT_TIMESTAMP | 出版年、简介、建档时间 |
| book_authors | book_id; author_id | 联合 PK；分别 FK -> books/authors | 书目与作者关系，不记录顺序 |
| book_copies | copy_id; book_id; barcode | PK; FK -> books; VARCHAR(40) ASCII UQ | 独立实体馆藏和条码 |
| book_copies | shelf_code; status; acquired_at | VARCHAR(40); ENUM; DATE | 书架、馆藏状态、入藏日期 |
| readers | reader_id; reader_no; name | PK; VARCHAR(32) ASCII UQ; VARCHAR(100) | 读者内部 ID、学号/证号、姓名 |
| readers | email; status; created_at | VARCHAR(254) UQ NULL; ENUM; DATETIME DEFAULT CURRENT_TIMESTAMP | 可缺省邮箱、账户状态、登记时间 |
| loans | loan_id; reader_id; copy_id | PK; FK -> readers; FK -> book_copies | 每次借阅及其主体 |
| loans | borrowed_at; due_at; returned_at | DATETIME; DATETIME; DATETIME NULL | 借出、应还、实际归还；NULL 表示未还 |
| loans | active_copy_id | BIGINT UNSIGNED STORED GENERATED UQ NULL | 未还时=copy_id，已还时=NULL |

馆藏状态：IN_SERVICE、MAINTENANCE、WITHDRAWN。读者状态：ACTIVE、SUSPENDED。书目 title、分类/出版社/作者名、条码、书架和读者姓名/证号必须非空白。出版年为 1450..2100，ISBN 在数据库校验 13 位数字，导入器进一步验证 978/979 前缀及 ISBN-13 校验码。邮箱可以为 NULL，多位未提供邮箱的读者不会相互冲突。

人类可读名称采用 utf8mb4_0900_ai_ci（大小写/重音不敏感）。ISBN、author_key、barcode、reader_no 使用 ASCII ascii_bin，编号按字节区分大小写。导入器拒绝原文不同却被名称排序规则判等的分类/出版社，要求与既有记录拼写一致。

## 4. 主外键、约束和事务

所有表都有主键；7 条外键保证引用完整性。父记录默认 RESTRICT，避免删除读者、馆藏或书目时丢失借阅历史。只有 book_authors 对 books 的删除使用 CASCADE，删除没有馆藏等依赖的书目时同步清除纯关系行。

due_at 必须晚于 borrowed_at；returned_at 为空或不早于 borrowed_at。借阅插入触发器用 FOR UPDATE 锁定读者与副本，校验 ACTIVE / IN_SERVICE。副本维护更新也检查活动借阅。未归还借阅的 reader_id、copy_id、borrowed_at 不可修改；归还后记录不可 UPDATE。读者暂停不会阻止归还，合法延期只改变 due_at。

关键并发约束：

```sql
active_copy_id GENERATED ALWAYS AS
  (CASE WHEN returned_at IS NULL THEN copy_id ELSE NULL END) STORED
UNIQUE KEY uq_loans_active_copy(active_copy_id)
```

未还记录的生成值是 copy_id，唯一键拒绝重复；已还记录是 NULL，MySQL 唯一索引允许多个 NULL，因此保留历次借阅。不能使用 UNIQUE(copy_id,returned_at) 代替此方案，因为那样允许同一 copy_id 存在多条 NULL 未还记录。

借出操作必须在一个事务中完成读者/副本查验、活动借阅检查、INSERT 与 COMMIT；异常 ROLLBACK。还书先锁定 loan_id，检查授权，已还时返回幂等响应，否则更新 returned_at 后提交。不维护库存扣减或回补字段，因此失败时没有库存计数与流水不一致的问题。1213/1205 等并发错误由 B 回滚整事务并有限重试。完整示例见 backend-handoff.md。

普通应用账号仅授 SELECT/INSERT/UPDATE，不给 DELETE loans 或 DDL。数据库管理员仍有删除权限，触发器不是管理员审计系统。当前数据库不验证任意补录已还历史的所有时间区间是否重叠；生成数据保证不重叠，正常业务 API 按当前时间操作。

## 5. 规范化分析

逻辑模型按第三范式（3NF）设计。每列只保存一个原子值，作者不以逗号列表存入 books。各实体的名称及属性完全依赖其主键：book_id -> isbn,title,category_id,publisher_id,publication_year,description,created_at；copy_id -> book_id,barcode,shelf_code,status,acquired_at；loan_id -> reader_id,copy_id,borrowed_at,due_at,returned_at。候选键 isbn、barcode、reader_no 和 author_key 也唯一标识相应实体。

book_authors 只有联合键，无非键属性，因此不存在对联合键的部分依赖；其余实体主键为单列，满足 2NF。分类名、出版社名、作者名、读者姓名不复制进借阅表，也不把书名/ISBN复制进副本表，消除这些实体属性的传递依赖，减少更新、插入、删除异常。

active_copy_id 是**物理实现中的受控派生字段**，用于表达条件唯一性；它不是独立业务事实，数据库自动计算，应用不可写入。不能将包含这一冗余派生列的物理表笼统宣称为无任何冗余的严格 3NF。逻辑模型满足 3NF，物理实现明确包含此约束辅助列。

可借状态和可借数量由 status 与活动借阅联查计算；逾期由 returned_at IS NULL AND due_at < 截止时刻计算，不存随时间变化的 is_overdue，以避免过期状态。

## 6. 索引设计与查询

| 索引 | 支持的查询/规则 | 取舍 |
|---|---|---|
| uq_books_isbn(isbn) | ISBN 精确检索、导入去重 | 唯一业务键 |
| idx_books_title(title) | title LIKE '前缀%' | '%关键词%' 通常不能获相同 B-tree 范围收益；不声称已实现中文全文搜索 |
| idx_books_category(category_id,book_id); idx_books_publisher(publisher_id) | 分类/出版社筛选与 FK | 分类组合列可用于按书目 ID 继续浏览 |
| book_authors PK(book_id,author_id); idx_book_authors_author(author_id,book_id) | 双向作者/书目查询 | 作者 M:N，无重复关联 |
| uq_copies_barcode(barcode); idx_copies_book_status(book_id,status,copy_id) | 条码定位、按书目查看在服副本 | 外键与状态过滤复用 |
| uq_readers_no(reader_no); uq_readers_email(email) | 读者查找和去重 | email 可缺省 |
| uq_loans_active_copy(active_copy_id) | 活动借阅唯一性与可借查询 | 核心正确性索引，不能为了实验删除 |
| idx_loans_reader_open_due(reader_id,returned_at,due_at) | 某读者的未还/到期查询，也可按 reader_id 找全部历史 | 历史按 borrowed_at 排序仍可能 filesort，本期未另加排序索引 |
| idx_loans_copy_history(copy_id,borrowed_at) | 单副本历史与 FK | 保留副本级查询入口 |
| idx_loans_open_due(returned_at,due_at,reader_id) | 全馆逾期列表 | 等值未还条件后接日期范围 |

此外 categories.name、publishers.name、authors.author_key 有对应唯一索引。不对所有字段盲目建索引：索引占用存储并增加写入维护成本。热门书统计等分析查询未做专门聚合加速，是否增加索引应由真实负载决定。6 类可运行 SQL 已单独提供。

## 7. 导入、生成与数据质量

CSV 字段：isbn,title,authors,publisher,publication_year,category,copies,shelf_code,description。authors 格式 `key:姓名|key:姓名`，本期不保存作者排列顺序。导入先完整验证 UTF-8/BOM、表头、ISBN 校验码、字段长度、数值范围和重复冲突，再在单个事务中按依赖顺序写表。所有外部值通过驱动参数绑定，避免 SQL 注入。按 ISBN 幂等；完全相同跳过，元数据/作者/副本冲突则包含当前批次前面成功行在内全部回滚。此导入是保守的建档操作，既有馆藏移动书架/增副本后不再与原 CSV 完全相同，需单独走管理员维护流程。

模拟数据使用固定 seed=2026 与 as_of=2026-11-26，每书 3 份副本，含合著、同名异人、在服/维护/注销副本、已还/逾期/未到期记录。生成器只让在服副本产生借阅，每个副本活动借阅最多一条，已还区间无重叠；书目出版年不晚于入藏年。SQL 用 UTF-8 十六进制字面值，避免反斜杠转义模式差异。manifest 记录行数、场景和 SHA256。必须导入另一套空表，不能和演示 CSV 混用。

## 8. 验证、实验与结果使用

实际验证结果以 evaluation/validation-summary.md、各测试 JSON/TXT 和 index-100k/benchmark-summary.md 为准。测试覆盖完整性、日期、资格、历史更新、归还释放、事务回滚以及两个独立连接争抢同一副本。导入测试另验证重复执行、BOM、冲突整批回滚和恶意文本安全保存。

本次实际通过：离线数据脚本 11/11、数据库约束与并发 18/18、真实 CSV 导入 9/9，共 38 项。测试引擎 MySQL 8.0.12，Python 3.12.14，PyMySQL 1.1.2。7 项数据时序及一致性检查的违规数均为 0。

索引实验：2000 书目、6000 副本、1000 读者、100000 借阅。查询为 reader_id 过滤的最近 100 条历史，按 borrowed_at DESC,loan_id DESC 排序。分别选择记录较多、较少与无匹配读者，比较优化器默认、IGNORE INDEX(idx_loans_reader_open_due)、FORCE INDEX(idx_loans_reader_open_due)。每类每变体预热 3 次后交替测量 21 次，保留每次耗时、结果 SHA256 和完整 EXPLAIN JSON。

以中位数和 nearest-rank p95 描述耗时。计时含客户端通信与 fetchall；同一个只读一致性快照中确认三种结果相同。IGNORE 只排除指定索引，并非所有索引均不存在；FORCE 不代表优化器自动选择。单机、单规模、单客户端、热缓存和合成均匀读者分布限制了外推，不把此实验称作完整吞吐、冷缓存或并发扩展性评测。D 应引用真实数字并保留这些条件，不能用假设数字代替实测。

| 实测查询情形 | 正常优化器中位 ms | 排除指定索引中位 ms | 强制指定索引中位 ms |
|---|---|---|---|
| reader_id=829，125 条历史、返回 100 条 | 3.5907 | 33.5175 | 3.5010 |
| reader_id=800，73 条历史、返回 73 条 | 2.8482 | 33.3829 | 2.8371 |
| reader_id=1001，不存在的读者、返回 0 条 | 0.6507 | 30.4926 | 0.8550 |

默认与 FORCE 的实际执行计划为 ref 访问 idx_loans_reader_open_due；IGNORE 变体为 ALL 全表扫描，EXPLAIN 估计 99981 行（估计值不是实际行数）。较多记录场景的中位耗时比约 9.3，不能推断其他查询或环境必然同幅提升。每个情形内三种变体的查询结果一致，合计 189 次计时均通过校验。原始 p95、逐次耗时及完整环境见随附实验表。

此合成集包含 5545 条未还记录，2773 条在基准时刻逾期；仅 1 份在服副本可借，属于接近满借的情景，并非真实图书馆占用率估计。实验只研究读者历史查询，不能据此推断日常馆藏利用率。最终生成 SQL 的 SHA256 为 7424c40a695ea84221e19e091e2a77ad904ae885999eb87ff91f0bcc17417a02。

## 9. 挑战、经验与后续工作

主要挑战是区分书目与实体、在保留历史时限制唯一活动借阅、消除库存冗余，以及让数据导入遇冲突时仍保持原子性。以独立副本表、生成列唯一键、事务与保守幂等策略解决。旧版本 CHECK 静默忽略促使将关键业务校验同时放入触发器，并用反例测试验证真实执行行为。

尚需团队完成：B 的 API 与身份权限、C 的界面/联调、D 的组员与贡献及整体报告、E 的 5-8 分钟视频，以及 GitHub 仓库上传与链接。MySQL 8.4 最终部署复测也由运行环境就绪后执行。此说明不包含虚构成员、仓库链接、视频链接或未经测量的结果。

## 参考文献

[1] MySQL 8.4 Reference Manual: CHECK Constraints. https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html

[2] MySQL 8.0.16 Introducing CHECK constraint. https://dev.mysql.com/blog-archive/mysql-8-0-16-introducing-check-constraint/

[3] MySQL 8.4 Reference Manual: CREATE INDEX Statement (UNIQUE 与 NULL). https://dev.mysql.com/doc/refman/8.4/en/create-index.html

[4] MySQL 8.4 Reference Manual: Range Optimization. https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html

[5] MySQL 8.4 Reference Manual: Optimizing Queries with EXPLAIN. https://dev.mysql.com/doc/refman/8.4/en/using-explain.html

[6] MySQL 8.4 Reference Manual: Index Hints. https://dev.mysql.com/doc/refman/8.4/en/index-hints.html
