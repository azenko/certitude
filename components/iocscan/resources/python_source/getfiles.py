#!/usr/bin/python

import os, re, win32api, win32file, sys

def getFiles():

	ret = []
	
    # List logical drives
	drives = win32api.GetLogicalDriveStrings().split('\x00')
	drives.pop()
	
    # Only get local dries
	drives = [ d for d in drives if win32file.GetDriveType(d)==win32file.DRIVE_FIXED ]
	
	files = ""

    # List files
	for drive in drives:
		files += os.popen('dir /s /b '+drive).read()

	files = files.split("\n")

	for tfile in files:
		resultline = ""
		resultline = tfile + "#"
		resultline += os.popen('md5 -n ' +tfile).read()
		if resultline[-1] == "#":
			resultline = resultline + "#"
		else:
			resultline = resultline[:-1] + "#"
		resultline += os.popen('strings -nh -raw ' +tfile).read()
		#resultline += base64.b64encode(os.popen('strings ' +tfile).read())
		print resultline
	
def main():

	getFiles()

if __name__=='__main__':
    main()