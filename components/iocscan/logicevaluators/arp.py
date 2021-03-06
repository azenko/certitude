#!/usr/bin/python

import template

class Evaluator(template.EvaluatorInterface):

	evalList = ['Interface', 'IPv4Address', 'PhysicalAddress', 'CacheType']

	def __init__(self, iocTree, remoteCommand, wd, keepFiles, confidential, dirname):
		template.EvaluatorInterface.__init__(self, iocTree, remoteCommand, wd, keepFiles, confidential, dirname)
		
		self.setEvaluatorParams(evalList=Evaluator.evalList, name='arp', ext='bat')