-- Table creation
CREATE TABLE files
(
	FilePath TEXT					-- File full path
);

.separator '	'
.import files.list files

ALTER TABLE files ADD COLUMN FullPath TEXT;
ALTER TABLE files ADD COLUMN FileExtension VARCHAR(255);		-- File extension
ALTER TABLE files ADD COLUMN FileName VARCHAR(255);			-- File name
ALTER TABLE files ADD COLUMN 'Md5sum' VARCHAR(255);		-- File Md5
ALTER TABLE files ADD COLUMN 'StringList/string' TEXT;		-- String List

-- Load string functions extension
SELECT 1 WHERE load_extension('strings.so') is not null;

ALTER TABLE files ADD COLUMN TempData TEXT;

UPDATE files SET TempData = LTRIM(RTRIM(REVERSE(SUBSTR(REVERSE(FilePath),0,CHARINDEX('#', REVERSE(FilePath),0)))));
UPDATE files SET FullPath = LTRIM(RTRIM(SUBSTR(FilePath, 0, CHARINDEX('#', FilePath, 0))))
UPDATE files SET FileName = LTRIM(RTRIM(REVERSE(SUBSTR(REVERSE(FullPath),0,CHARINDEX('\', REVERSE(FullPath),0)))));
UPDATE files SET FileExtension = LTRIM(RTRIM(REVERSE(SUBSTR(REVERSE(FullPath),0,CHARINDEX('.', REVERSE(FullPath),0)))));
UPDATE files SET StringList = LTRIM(RTRIM(REVERSE(SUBSTR(REVERSE(TempData),0,CHARINDEX('#', REVERSE(TempData),0)))));
UPDATE files SET Md5sum = LTRIM(RTRIM(SUBSTR(TempData, 0, CHARINDEX('#', TempData, 0))));

ALTER TABLE files DROP COLUMN TempData; 