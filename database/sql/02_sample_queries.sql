-- Execute after catalog import and demo fixture; no schema changes.
SET @title_prefix = '合成书目：数据库';
SET @reader_no = 'R-DEMO-001';
SET @as_of = '2026-11-26 12:00:00';

-- Q1: Prefix search (a leading wildcard would generally lose B-tree range access).
SELECT b.book_id, b.isbn, b.title, c.name AS category, p.name AS publisher
FROM books b JOIN categories c ON c.category_id=b.category_id
JOIN publishers p ON p.publisher_id=b.publisher_id
WHERE b.title LIKE CONCAT(@title_prefix, '%') ORDER BY b.title, b.book_id LIMIT 20;

-- Q2: Browse copies, deriving availability instead of maintaining a duplicate count.
SELECT b.isbn,b.title,bc.copy_id,bc.barcode,bc.shelf_code,
       CASE WHEN bc.status='IN_SERVICE' AND l.loan_id IS NULL THEN 'AVAILABLE'
            WHEN l.loan_id IS NOT NULL THEN 'ON_LOAN' ELSE bc.status END AS availability
FROM books b JOIN book_copies bc ON bc.book_id=b.book_id
LEFT JOIN loans l ON l.active_copy_id=bc.copy_id
WHERE b.isbn='9780000000019' ORDER BY bc.copy_id;

-- Q3: A reader's complete loan history with deterministic ordering.
SELECT l.loan_id,b.title,bc.barcode,l.borrowed_at,l.due_at,l.returned_at
FROM readers r JOIN loans l ON l.reader_id=r.reader_id
JOIN book_copies bc ON bc.copy_id=l.copy_id JOIN books b ON b.book_id=bc.book_id
WHERE r.reader_no=@reader_no ORDER BY l.borrowed_at DESC,l.loan_id DESC LIMIT 100;

-- Q4: Unreturned/overdue loans (the cutoff is a query parameter, not stored state).
SELECT l.loan_id,r.reader_no,r.name,b.title,l.due_at,
       TIMESTAMPDIFF(DAY,l.due_at,@as_of) AS overdue_days
FROM loans l JOIN readers r ON r.reader_id=l.reader_id
JOIN book_copies bc ON bc.copy_id=l.copy_id JOIN books b ON b.book_id=bc.book_id
WHERE l.returned_at IS NULL AND l.due_at < @as_of ORDER BY l.due_at,l.loan_id;

-- Q5: Counts by title; SUM uses CASE so a title without copies is counted as 0.
SELECT b.book_id,b.title,COUNT(bc.copy_id) AS total_copies,
       SUM(CASE WHEN bc.status='IN_SERVICE' AND l.loan_id IS NULL THEN 1 ELSE 0 END) AS available_copies
FROM books b LEFT JOIN book_copies bc ON bc.book_id=b.book_id
LEFT JOIN loans l ON l.active_copy_id=bc.copy_id
GROUP BY b.book_id,b.title ORDER BY b.book_id;

-- Q6: Popular titles in a half-open time window; no YEAR() on an indexed column.
SELECT b.book_id,b.title,COUNT(*) AS times_borrowed
FROM loans l JOIN book_copies bc ON bc.copy_id=l.copy_id JOIN books b ON b.book_id=bc.book_id
WHERE l.borrowed_at >= '2026-01-01' AND l.borrowed_at < '2027-01-01'
GROUP BY b.book_id,b.title ORDER BY times_borrowed DESC,b.book_id LIMIT 10;
