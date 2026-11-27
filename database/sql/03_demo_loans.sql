-- Run ONCE after importing data/books_sample.csv into a fresh database.
-- Synthetic demonstration identities; all timestamps use Asia/Shanghai wall time.
-- As-of: 2026-11-26 12:00:00. Deliberately fails on a duplicate run.
START TRANSACTION;
INSERT INTO readers(reader_no,name,email,status) VALUES
('R-DEMO-001','演示读者一','demo1@example.invalid','ACTIVE'),
('R-DEMO-002','演示读者二','demo2@example.invalid','ACTIVE'),
('R-DEMO-003','暂停借阅读者','demo3@example.invalid','SUSPENDED');

-- Completed history followed by one current overdue borrowing of the same copy.
-- Resolve IDs before INSERT: the INSERT trigger uses locking reads on parent
-- tables, so INSERT ... SELECT from those same parents is deliberately avoided.
SELECT reader_id INTO @demo_r1 FROM readers WHERE reader_no='R-DEMO-001';
SELECT reader_id INTO @demo_r2 FROM readers WHERE reader_no='R-DEMO-002';
SELECT copy_id INTO @demo_c1 FROM book_copies WHERE barcode='9780000000019-001';
SELECT copy_id INTO @demo_c2 FROM book_copies WHERE barcode='9780000000026-001';
INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at,returned_at)
VALUES (@demo_r1,@demo_c1,'2026-10-01 09:00:00','2026-10-15 09:00:00','2026-10-10 10:00:00');
INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at,returned_at)
VALUES (@demo_r1,@demo_c1,'2026-11-01 09:00:00','2026-11-15 09:00:00',NULL);

-- A current loan that has not reached its due date at the fixed cutoff.
INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at,returned_at)
VALUES (@demo_r2,@demo_c2,'2026-11-20 09:00:00','2026-12-04 09:00:00',NULL);
COMMIT;
