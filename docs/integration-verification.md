# 成员 C 联调记录 / Integration verification

## 环境

在 Windows PowerShell 上使用 Python 3.13.9、Flask 3.1.3、PyMySQL 1.2.4、MySQL Community Server 8.4.13 和 Chrome 158.0.8127.38。MySQL 使用临时数据目录和本机回环端口 `13307`，Flask 使用 `127.0.0.1:8000`。Chrome 使用独立测试配置，分别验证 1280 × 900 桌面和 390 × 844 移动视口。

按[项目启动文档](../README.md#powershell-commands)的本机 MySQL 路径创建空库，使用 `utf8mb4_0900_ai_ci` 并加载 A 的 schema。用只具备 `SELECT`、`INSERT`、`UPDATE` 权限的应用账号导入 6 种书目、13 份馆藏和 3 条演示借阅。导入后 SQL 统计得到 6 种书目、13 份馆藏、3 位读者、3 条借阅记录。

## 结果

| 用例 | 结果 |
| --- | --- |
| 首页与图书目录 | 首页、静态资源和图书 API 返回 200。默认展示 6 种书目。搜索 `合成书目：数据库` 返回 1 种书目，无匹配词显示空结果。 |
| 实体馆藏 | 可借、已借出、维护中和已撤藏均按状态显示。用临时库中的两份副本验证维护和撤藏状态，两者均无借书按钮。延迟的旧馆藏响应未覆盖新选择。 |
| 登录和键盘操作 | Tab 可到达跳转链接，切换页面后焦点到达标题，Esc 关闭登录框并返回触发按钮。错误令牌显示对应提示。取消等待中的登录后能立即重开，旧验证响应未覆盖新登录。退出后个人记录隐藏。 |
| 桌面端借还 | 读者一借出 `9780000000019-002` 后，副本显示已借出，个人历史新增记录并显示 14 天借期。归还后历史保留归还时间，副本恢复可借。 |
| 读者隔离与冲突 | 读者二从过时馆藏页面尝试借同一副本，收到冲突提示，馆藏刷新为已借出。读者二的历史中没有这条借阅，其归还该记录的 API 请求返回 404。 |
| 重复归还 | 对读者一的已还记录重复调用归还 API，返回 200、`already_returned: true` 和原归还时间。 |
| 读取失败和重试 | 在浏览器模拟图书查询返回 503，点击「重试」后恢复。实际归还成功后模拟借阅记录刷新失败，页面保留成功提示，读取成功后移除刷新失败提示。 |
| 写入结果不明确 | 真实借书提交后，在浏览器将响应替换为 500。等待响应期间借还按钮禁用。收到异常结果后，页面提示核对并刷新馆藏和历史，只发出一次借书请求。 |
| 英文和移动视口 | 在 390 像素 Chrome 视口完成英文借还，无页面横向溢出。刷新后保留英文偏好，恢复访客状态。搜索结果保留数据库中的中文书名。 |
| SQL 核查 | 按两个实际借阅编号查询数据库，确认读者和条码匹配、借期为 14 天、已写入归还时间且 `active_copy_id` 为 `NULL`。 |
| 离线检查 | 两个前端 JavaScript 模块通过语法检查，A 的 11 项离线数据脚本测试通过。 |

浏览器延迟和 HTTP 错误由测试端在读取正常响应时模拟，借还写入使用真实 Flask 和 MySQL。Docker Compose 保留为可选初始化方式，本轮实测使用本机 MySQL。移动端覆盖为 Chrome 视口模拟。

## 复现与 SQL 核查

1. 用演示读者一登录。在目录输入 `合成书目：数据库`，打开「合成书目：数据库系统实践」，借出条码 `9780000000019-002` 的副本。前往「我的借阅」，确认新记录的借出时间和应还时间。
2. 在另一 PowerShell 窗口读取同一个读者的 API 记录。记下最新一条相同条码的 `loan_id`。如需录屏展示数据流，可同时展示浏览器 Network 面板中的借书请求及其 JSON 响应。

```powershell
$demoHeaders = @{ Authorization = 'Bearer local-demo-reader-1' }
$demoLoans = Invoke-RestMethod 'http://127.0.0.1:8000/api/loans' -Headers $demoHeaders
$demoLoans.items |
    Where-Object { $_.barcode -eq '9780000000019-002' } |
    Sort-Object loan_id -Descending |
    Select-Object -First 1 loan_id, barcode, borrowed_at, due_at, returned_at
```

3. 用应用账号连接 `library_project`。执行下方 SQL，把示例编号 `4` 改为本次记录的编号。打开「我的借阅」归还副本，再执行同一查询。首次查询应显示 `returned_at` 为 `NULL` 且 `active_copy_id` 有值。归还后 `returned_at` 有值且 `active_copy_id` 为 `NULL`，馆藏页面恢复「可借」。

```sql
SET @verified_loan_id = 4;
SELECT l.loan_id,
       r.reader_no,
       c.barcode,
       l.borrowed_at,
       l.due_at,
       l.returned_at,
       l.active_copy_id
FROM loans AS l
JOIN readers AS r ON r.reader_id = l.reader_id
JOIN book_copies AS c ON c.copy_id = l.copy_id
WHERE l.loan_id = @verified_loan_id;
```

在实测空库中，桌面验收生成借阅 `4`，条码为 `9780000000019-002`。窄屏验收生成借阅 `5`，条码为 `9780000000019-003`。两个借阅均属于 `R-DEMO-001`，最终均已归还。

[项目启动文档](../README.md) · [后端 API](../backend/README.md) · [数据库样例查询](../database/sql/02_sample_queries.sql)
