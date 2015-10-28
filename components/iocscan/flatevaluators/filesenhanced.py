#!/usr/bin/python

import template

class Evaluator(template.EvaluatorInterface):

    evalList = ['Md5sum', 'StringList']

    def __init__(self, logger, ioc, remoteCommand, wd, keepFiles, confidential, dirname):
        template.EvaluatorInterface.__init__(self, logger, ioc, remoteCommand, wd, keepFiles, confidential, dirname)

        self.setEvaluatorParams(evalList=Evaluator.evalList, name='filesenhanced', command='collector getfilesenhanced')