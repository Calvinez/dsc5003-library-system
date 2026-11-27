-- For the supplied Docker initialization ONLY. The entrypoint creates this user.
-- Run as owner/root. Standard manual installations should substitute their DB/user.
REVOKE ALL PRIVILEGES ON library_project.* FROM 'library_app'@'%';
GRANT SELECT, INSERT, UPDATE ON library_project.* TO 'library_app'@'%';
-- No DELETE, CREATE, DROP, ALTER or GRANT for the normal backend account.
-- Integration tests need a separate owner account on a dedicated TEST database.
