-- Library borrowing system / Track 1 / Part A.
-- Run against a NEW, explicitly selected MySQL database. No destructive reset.
-- Tested with strict SQL mode; compatible with MySQL 8.0 and 8.4.
SET NAMES utf8mb4;
SET SESSION time_zone = '+08:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

CREATE TABLE categories (
    category_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(80) NOT NULL,
    PRIMARY KEY (category_id), UNIQUE KEY uq_categories_name (name),
    CHECK (CHAR_LENGTH(TRIM(name)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE publishers (
    publisher_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(160) NOT NULL,
    PRIMARY KEY (publisher_id), UNIQUE KEY uq_publishers_name (name),
    CHECK (CHAR_LENGTH(TRIM(name)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE authors (
    author_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    author_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(120) NOT NULL,
    PRIMARY KEY (author_id), UNIQUE KEY uq_authors_key (author_key),
    CHECK (CHAR_LENGTH(TRIM(name)) > 0),
    CHECK (CHAR_LENGTH(TRIM(author_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE books (
    book_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    isbn CHAR(13) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    title VARCHAR(255) NOT NULL,
    category_id BIGINT UNSIGNED NOT NULL,
    publisher_id BIGINT UNSIGNED NOT NULL,
    publication_year SMALLINT UNSIGNED NOT NULL,
    description TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (book_id), UNIQUE KEY uq_books_isbn (isbn),
    KEY idx_books_title (title),
    KEY idx_books_category (category_id, book_id),
    KEY idx_books_publisher (publisher_id),
    CONSTRAINT fk_books_category FOREIGN KEY (category_id) REFERENCES categories(category_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_books_publisher FOREIGN KEY (publisher_id) REFERENCES publishers(publisher_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK (publication_year BETWEEN 1450 AND 2100),
    CHECK (CHAR_LENGTH(TRIM(title)) > 0),
    CHECK (CHAR_LENGTH(isbn) = 13)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE book_authors (
    book_id BIGINT UNSIGNED NOT NULL,
    author_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (book_id, author_id),
    KEY idx_book_authors_author (author_id, book_id),
    CONSTRAINT fk_book_authors_book FOREIGN KEY (book_id) REFERENCES books(book_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_book_authors_author FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE book_copies (
    copy_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    book_id BIGINT UNSIGNED NOT NULL,
    barcode VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    shelf_code VARCHAR(40) NOT NULL,
    status ENUM('IN_SERVICE','MAINTENANCE','WITHDRAWN') NOT NULL DEFAULT 'IN_SERVICE',
    acquired_at DATE NOT NULL,
    PRIMARY KEY (copy_id), UNIQUE KEY uq_copies_barcode (barcode),
    KEY idx_copies_book_status (book_id, status, copy_id),
    CONSTRAINT fk_copies_book FOREIGN KEY (book_id) REFERENCES books(book_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK (CHAR_LENGTH(TRIM(barcode)) > 0),
    CHECK (CHAR_LENGTH(TRIM(shelf_code)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE readers (
    reader_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reader_no VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(254) NULL,
    status ENUM('ACTIVE','SUSPENDED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reader_id), UNIQUE KEY uq_readers_no (reader_no),
    UNIQUE KEY uq_readers_email (email),
    CHECK (CHAR_LENGTH(TRIM(reader_no)) > 0),
    CHECK (CHAR_LENGTH(TRIM(name)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE loans (
    loan_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reader_id BIGINT UNSIGNED NOT NULL,
    copy_id BIGINT UNSIGNED NOT NULL,
    borrowed_at DATETIME NOT NULL,
    due_at DATETIME NOT NULL,
    returned_at DATETIME NULL,
    active_copy_id BIGINT UNSIGNED GENERATED ALWAYS AS
        (CASE WHEN returned_at IS NULL THEN copy_id ELSE NULL END) STORED,
    PRIMARY KEY (loan_id), UNIQUE KEY uq_loans_active_copy (active_copy_id),
    KEY idx_loans_reader_open_due (reader_id, returned_at, due_at),
    KEY idx_loans_copy_history (copy_id, borrowed_at),
    KEY idx_loans_open_due (returned_at, due_at, reader_id),
    CONSTRAINT fk_loans_reader FOREIGN KEY (reader_id) REFERENCES readers(reader_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_loans_copy FOREIGN KEY (copy_id) REFERENCES book_copies(copy_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK (due_at > borrowed_at),
    CHECK (returned_at IS NULL OR returned_at >= borrowed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- CHECK is enforced starting with MySQL 8.0.16. Triggers also enforce
-- critical checks so older 8.0 lab installations cannot silently bypass them.
DELIMITER $$
CREATE TRIGGER categories_bi BEFORE INSERT ON categories FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='category name required'; END IF;
END$$
CREATE TRIGGER categories_bu BEFORE UPDATE ON categories FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='category name required'; END IF;
END$$
CREATE TRIGGER publishers_bi BEFORE INSERT ON publishers FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='publisher name required'; END IF;
END$$
CREATE TRIGGER publishers_bu BEFORE UPDATE ON publishers FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='publisher name required'; END IF;
END$$
CREATE TRIGGER authors_bi BEFORE INSERT ON authors FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 OR CHAR_LENGTH(TRIM(NEW.author_key)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='author key and name required'; END IF;
END$$
CREATE TRIGGER authors_bu BEFORE UPDATE ON authors FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.name)) = 0 OR CHAR_LENGTH(TRIM(NEW.author_key)) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='author key and name required'; END IF;
END$$
CREATE TRIGGER books_bi BEFORE INSERT ON books FOR EACH ROW
BEGIN
    IF NEW.isbn NOT REGEXP '^[0-9]{13}$' OR CHAR_LENGTH(TRIM(NEW.title)) = 0 OR NEW.publication_year NOT BETWEEN 1450 AND 2100 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid ISBN, title or publication year';
    END IF;
END$$
CREATE TRIGGER books_bu BEFORE UPDATE ON books FOR EACH ROW
BEGIN
    IF NEW.isbn NOT REGEXP '^[0-9]{13}$' OR CHAR_LENGTH(TRIM(NEW.title)) = 0 OR NEW.publication_year NOT BETWEEN 1450 AND 2100 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid ISBN, title or publication year';
    END IF;
END$$
CREATE TRIGGER readers_bi BEFORE INSERT ON readers FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.reader_no)) = 0 OR CHAR_LENGTH(TRIM(NEW.name)) = 0 OR NEW.status NOT IN ('ACTIVE','SUSPENDED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid reader';
    END IF;
END$$
CREATE TRIGGER readers_bu BEFORE UPDATE ON readers FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.reader_no)) = 0 OR CHAR_LENGTH(TRIM(NEW.name)) = 0 OR NEW.status NOT IN ('ACTIVE','SUSPENDED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid reader';
    END IF;
END$$
CREATE TRIGGER copies_bi BEFORE INSERT ON book_copies FOR EACH ROW
BEGIN
    IF CHAR_LENGTH(TRIM(NEW.barcode)) = 0 OR CHAR_LENGTH(TRIM(NEW.shelf_code)) = 0 OR NEW.status NOT IN ('IN_SERVICE','MAINTENANCE','WITHDRAWN') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid copy';
    END IF;
END$$
CREATE TRIGGER copies_bu BEFORE UPDATE ON book_copies FOR EACH ROW
BEGIN
    DECLARE active_loan BIGINT UNSIGNED DEFAULT NULL;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET active_loan = NULL;
    IF CHAR_LENGTH(TRIM(NEW.barcode)) = 0 OR CHAR_LENGTH(TRIM(NEW.shelf_code)) = 0 OR NEW.status NOT IN ('IN_SERVICE','MAINTENANCE','WITHDRAWN') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid copy';
    END IF;
    -- An existing copy cannot be re-associated with another bibliographic work.
    IF NEW.book_id <> OLD.book_id THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='copy book_id is immutable'; END IF;
    IF NEW.status <> 'IN_SERVICE' THEN
        SELECT loan_id INTO active_loan FROM loans WHERE active_copy_id = OLD.copy_id LIMIT 1 FOR UPDATE;
        IF active_loan IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='return active loan before changing copy status'; END IF;
    END IF;
END$$
CREATE TRIGGER loans_bi BEFORE INSERT ON loans FOR EACH ROW
BEGIN
    DECLARE reader_state VARCHAR(16) DEFAULT NULL;
    DECLARE copy_state VARCHAR(16) DEFAULT NULL;
    DECLARE CONTINUE HANDLER FOR NOT FOUND BEGIN END;
    IF NEW.due_at <= NEW.borrowed_at OR (NEW.returned_at IS NOT NULL AND NEW.returned_at < NEW.borrowed_at) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid loan dates';
    END IF;
    -- Current locking reads serialize new loans with suspension/status changes.
    SELECT status INTO reader_state FROM readers WHERE reader_id=NEW.reader_id FOR UPDATE;
    SELECT status INTO copy_state FROM book_copies WHERE copy_id=NEW.copy_id FOR UPDATE;
    IF reader_state IS NULL OR copy_state IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reader or copy does not exist'; END IF;
    IF reader_state <> 'ACTIVE' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='reader suspended'; END IF;
    IF copy_state <> 'IN_SERVICE' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='copy not in service'; END IF;
END$$
CREATE TRIGGER loans_bu BEFORE UPDATE ON loans FOR EACH ROW
BEGIN
    IF OLD.returned_at IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='returned loan history is immutable'; END IF;
    IF NEW.copy_id <> OLD.copy_id OR NEW.reader_id <> OLD.reader_id OR NEW.borrowed_at <> OLD.borrowed_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='loan identity and borrowed_at are immutable';
    END IF;
    IF NEW.due_at <= NEW.borrowed_at OR (NEW.returned_at IS NOT NULL AND NEW.returned_at < NEW.borrowed_at) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid loan dates';
    END IF;
END$$
DELIMITER ;
