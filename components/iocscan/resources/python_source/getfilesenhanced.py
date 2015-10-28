#!/usr/bin/python

import os, re, win32api, win32file, sys, base64

def getFilesEnhanced():

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
		resultline += os.popen('md5 -n ' +tfile).read() + "\v\v\v\v\v\v"
		resultline += os.popen('strings ' +tfile).read()
		#resultline += base64.b64encode(os.popen('strings ' +tfile).read())
		print resultline
	 

def main():

	getFilesEnhanced()

if __name__=='__main__':
    main()