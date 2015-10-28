-- Table creation
CREATE TABLE filesenhanced
(
	FilePath TEXT					-- File full path
);

.separator '	'
.import filesenhanced.list filesenhanced

ALTER TABLE filesenhanced ADD COLUMN StringList TEXT;		-- String List
ALTER TABLE filesenhanced ADD COLUMN Md5sum VARCHAR(255);		-- File Md5

-- Load string functions extension
SELECT 1 WHERE load_extension('strings.so') is not null;

UPDATE filesenhanced SET StringList = LTRIM(RTRIM(REVERSE(SUBSTR(REVERSE(FilePath),0,CHARINDEX('\v\v\v\v\v\v', REVERSE(FilePath),0)))));
UPDATE filesenhanced SET Md5sum = LTRIM(RTRIM(SUBSTR(FilePath, 0, CHARINDEX('\v\v\v\v\v\v', FilePath, 0))))

ALTER TABLE filesenhanced DROP COLUMN FilePath 