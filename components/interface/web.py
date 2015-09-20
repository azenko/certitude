#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
CERTitude: The Seeker of IOC
CERT-Solucom cert@solucom.fr
"""
if __name__ == "__main__" and __package__ is None:
    raise Exception('Erreur : lancez le script depuis main.py et non directement')

import os
import re #Regular expressions 
import subprocess, sys
import json
import time
import BaseHTTPServer
import SocketServer
import ssl
import base64
import urlparse
import logging
import datetime
import urllib
import sqlite3
from math import log
try:
    import win32event
    import win32security
except:
    pass

from flask import Flask, render_template, request, session, redirect, url_for, jsonify, Response, abort
from flask.ext.login import LoginManager, login_required, login_user, logout_user, flash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import DeclarativeMeta
from netaddr import IPNetwork

from config import IOC_MODE, DEBUG, PORT_API, CREDENTIALS_INTERFACE, USE_SSL, SSL_KEY_FILE, SSL_CERT_FILE, BASE_DE_DONNEES_QUEUE, PORTS, PREFIXES_IP_GROUPE, NOMBRE_MAX_IP_PAR_REQUETE, SECONDES_POUR_RESCAN, ADRESSE_STATIC, MODULES_CONSO, MODULES_VUES, TACHES_NOMBRE
from helpers.queue_models import Task
from helpers.results_models import Result, IOCDetection
from helpers.misc_models import User, ConfigurationProfile, WindowsCredential, XMLIOC, Batch, GlobalConfig
from helpers.helpers import resolve, hashPassword, checksum, verifyPassword
import helpers.crypto as crypto

import components.iocscan.openioc.openiocparser as openiocparser
import helpers.iocscan_modules as ioc_modules

results = []
for module in MODULES_CONSO:
    results.append(getattr(
        __import__(
            "modules." + module + '.models',
            fromlist=['Result']
        ), 'Result'))


try:
    chemin = path.join(path.dirname(path.abspath(__file__)), '..', '..')
except:
    chemin = "" # relatif

loggingserver = logging.getLogger('api')

engine = create_engine(BASE_DE_DONNEES_QUEUE, echo=False)
dbsession = sessionmaker(bind=engine)()


''' APPLICATION CONFIGURATION '''

app = Flask(__name__, static_folder = 'static')
app.secret_key = os.urandom(24)
app.config.update(CREDENTIALS_INTERFACE)

app.config['UPLOAD_FOLDER'] = 'upload'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 5*60
ALLOWED_EXTENSIONS = ['txt']
app.config['IOCS_FOLDER'] = os.path.join('components', 'iocscan', '.','ioc')
app.config['RESULT_FILE'] = os.path.join('components', 'interface', 'static','data','results.csv')
app.config['CERTITUDE_OUTPUT_FOLDER'] = 'results'
app.config['PROCESSED_FOLDER'] = 'processed'
RESULT_FILE_HEADER = 'Title:HostId,Title:Hostname,Lookup:Success,Lookup:IP,Lookup:Subnet,Malware,Compromise'

IP_REGEX = '(([0-9]|[1-9][0-9]|1[0-9]{2}|2([0-4][0-9]|5[0-5]))\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2([0-4][0-9]|5[0-5]))'

        #-############################-#
        # Pages routing and controlers #
        #-############################-#


    # INDEX

@app.route('/')
def index():

    if 'logged_in' in session:
        ret=redirect(url_for('scan'))
    else:
        ret=redirect(url_for('login'))

    return ret


    # SESSION MANAGEMENT

@app.route('/login', methods=['GET', 'POST'])
def login():

    error = ''
    if request.method == 'POST':

        userList = dbsession.query(User).filter_by(username = request.form['username']).limit(1)
        matchingUser = userList.first()

        if (matchingUser is not None) and (matchingUser.password == hashPassword(request.form['password'])):
            if matchingUser.active:
                session['logged_in'] = True
                session['user_id'] = matchingUser.id
                
                flash('Logged in')
                return redirect(url_for('index'))
            else:
                return render_template('session-login.html', error='User account is disabled')
        error = 'User might not exist or password is incorrect'
                
    return render_template('session-login.html', errors=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Logged out')
    return redirect(url_for('index'))


    # USER MANAGEMENT

@app.route('/users')
def users():
    if 'logged_in' in session:

        allUsers = dbsession.query(User).order_by('id ASC')

        return render_template('user-list.html', users = allUsers)
    else:
        return redirect(url_for('login'))


@app.route('/users/<int:userid>/switchactive')
def userSwitchActive(userid):
    if 'logged_in' in session:

        u = dbsession.query(User).filter_by(id = userid).first()

        if u is None:
            flash('This user does not exist')
            return redirect(url_for('users'))

        u.active = not u.active
        dbsession.commit()

        return redirect(url_for('users'))
    else:
        return redirect(url_for('login'))


@app.route('/user/add', methods=['GET', 'POST'])
def userAdd():
    if 'logged_in' in session:
        if request.method == 'GET':
            return render_template('user-add.html')
        else:
            success = True
            errors = []

            user_password = request.form['user_password']
            user = dbsession.query(User).filter_by(id=session['user_id']).first()
            
            if user is None or hashPassword(user_password) != user.password:
                success = False
                errors.append('Your password is incorrect')
            
            if success:
                mk_cksum = dbsession.query(GlobalConfig).filter_by(key = 'master_key_checksum').first()
                if not mk_cksum:
                    success = False
                    errors.append('Database is broken, please create a new one !')
                    
            if success:
                keyFromPassword = crypto.keyFromText(user_password)
                MASTER_KEY = crypto.decrypt(user.encrypted_master_key, keyFromPassword)
                
                
                if checksum(MASTER_KEY) != mk_cksum.value:
                    errors.append('MASTER_KEY may have been altered')
                    del MASTER_KEY
                    success = False
                
            if success:
                password1, password2 = request.form['password'], request.form['password2']
                if password1 != password2:
                    success = False
                    errors.append('New user passwords do not match')
            
            if success:
                if not verifyPassword(password1):
                    success = False
                    errors.append('Password is not complex enough (l > 12 and at least three character classes between lowercase, uppercase, numeric and special char)')
                
            if success:
                keyFromPassword = crypto.keyFromText(password1)
                emk = crypto.encrypt(MASTER_KEY, keyFromPassword)
                del MASTER_KEY
                
                u = User(
                        username = request.form['username'],
                        password = hashPassword(password1),
                        email = request.form['email'],
                        active = True,
                        encrypted_master_key = emk)

                dbsession.add(u)
                dbsession.commit()

            if success:
                return redirect(url_for('users'))
            else:
                return render_template('user-add.html', username=request.form['username'], email=request.form['email'], errors='\n'.join(errors))
    else:
        return redirect(url_for('login'))


@app.route('/user/<int:userid>/delete',)
def userDelete(userid):
    if 'logged_in' in session:
        u = dbsession.query(User).filter_by(id = userid).first()

        if u is None:
            flash('This user does not exist')
            return redirect(url_for('users'))

        dbsession.delete(u)
        dbsession.commit()

        return redirect(url_for('users'))
    else:
        return redirect(url_for('login'))


    # CONFIGURATION, IOCs & PROFILES MANAGEMENT

# @app.route('/url',)
# def fun():
    # if 'logged_in' in session:
        # return render_template('blank.html')
    # else:
        # return redirect(url_for('login'))
        
     
@app.route('/config',)
def config():
    if 'logged_in' in session:
    
        configuration_profiles = dbsession.query(ConfigurationProfile).order_by(ConfigurationProfile.name.asc())
        windows_credentials = dbsession.query(WindowsCredential).order_by(WindowsCredential.domain.asc(), WindowsCredential.login.asc())
        xmliocs = dbsession.query(XMLIOC).order_by(XMLIOC.date_added.desc())
    
        ref = {}
        for xmlioc in xmliocs:
            ref[str(xmlioc.id)] = xmlioc.name + ' - ' + str(xmlioc.date_added)
    
        iocdesclist = {}
        for cp in configuration_profiles:
            if len(cp.ioc_list)==0:
                iocdesclist[cp.id] = ''
                continue 
            iocdesclist[cp.id] = '||'.join([ref[str(id)] for id in cp.ioc_list.split(',')])
    
        return render_template('config-main.html', xmliocs = xmliocs, windows_credentials = windows_credentials, configuration_profiles = configuration_profiles, iocdesclist = iocdesclist)
    else:
        return redirect(url_for('login'))


        # DELETIONS
        
@app.route('/config/wincredz/<int:wincredid>/delete')
def wincredDelete(wincredid):
    if 'logged_in' in session:
    
        wc = dbsession.query(WindowsCredential).filter_by(id=wincredid).first()
        
        if wc is None:
            flash('This credential does not exist')
            return redirect(url_for('config'))
            
        dbsession.delete(wc)
        dbsession.commit()
    
        return redirect(url_for('config'))
    else:
        return redirect(url_for('login'))


@app.route('/config/xmlioc/<int:xmliocid>/delete')        
def xmliocDelete(xmliocid):
    if 'logged_in' in session:
    
        xi = dbsession.query(XMLIOC).filter_by(id=xmliocid).first()
        
        if xi is None:
            flash('This IOC does not exist')
            return redirect(url_for('config'))
            
        dbsession.delete(xi)
        dbsession.commit()
    
        return redirect(url_for('config'))
    else:
        return redirect(url_for('login'))


@app.route('/config/profile/<int:profileid>/delete')        
def profileDelete(profileid):
    if 'logged_in' in session:
    
        p = dbsession.query(ConfigurationProfile).filter_by(id=profileid).first()
        
        if p is None:
            flash('This profile does not exist')
            return redirect(url_for('config'))
            
        dbsession.delete(p)
        dbsession.commit()
    
        return redirect(url_for('config'))
    else:
        return redirect(url_for('login'))


        # ADDITIONS
        
@app.route('/config/wincredz/add',methods=['GET','POST'])
def wincredAdd():
    if 'logged_in' in session:
        if request.method == 'GET':
            return render_template('config-wincred-add.html')
        else:
            success = True
            errors = []

            user_password = request.form['user_password']
            user = dbsession.query(User).filter_by(id=session['user_id']).first()
            
            if user is None or hashPassword(user_password) != user.password:
                success = False
                errors.append('Your password is incorrect')
            
            if success:
                mk_cksum = dbsession.query(GlobalConfig).filter_by(key = 'master_key_checksum').first()
                if not mk_cksum:
                    success = False
                    errors.append('Database is broken, please create a new one !')
                    
            if success:
                keyFromPassword = crypto.keyFromText(user_password)
                MASTER_KEY = crypto.decrypt(user.encrypted_master_key, keyFromPassword)
                
                
                if checksum(MASTER_KEY) != mk_cksum.value:
                    errors.append('MASTER_KEY may have been altered')
                    del MASTER_KEY
                    success = False
                
            if success:
            
                account_password = request.form['password']
                encrypted_account_password = crypto.encrypt(account_password, MASTER_KEY)
                del MASTER_KEY
                
                wc = WindowsCredential(
                        domain = request.form['domain'],
                        login = request.form['login'],
                        encrypted_password = encrypted_account_password)

                dbsession.add(wc)
                dbsession.commit()

            if success:
                return redirect(url_for('config'))
            else:
                return render_template('config-wincred-add.html',
                                            errors = '\n'.join(errors),
                                            domain = request.form['domain'],
                                            login = request.form['login'],
                                            password = request.form['password'])
    else:
        return redirect(url_for('login'))
        
     
@app.route('/config/xmlioc/add',methods=['GET','POST'])
def xmliocAdd():
    if 'logged_in' in session:
        if request.method == 'GET':
            return render_template('config-xmlioc-add.html')
        else:
            success = True
            errors = []

            xml_content = request.files['xml_content'].stream.read()
            
            xi = XMLIOC(
                    name=request.form['name'],
                    xml_content = base64.b64encode(xml_content))
                    
            dbsession.add(xi)
            dbsession.commit()

            if success:
                return redirect(url_for('config'))
            else:
                flash('\n'.join(errors))
                return render_template('config-xmlioc-add.html', name = request.form['name'])
    else:
        return redirect(url_for('login'))
        
     
@app.route('/config/profile/add',methods=['GET','POST'])
def profileAdd():
    if 'logged_in' in session:
    
        xi = dbsession.query(XMLIOC).order_by(XMLIOC.name.asc())
    
        if request.method == 'GET':
            return render_template('config-profile-add.html', xmliocs = xi)
        else:
            success = True
            errors = []

            hc = True if 'host_confidential' in request.form else False
            
            cp = ConfigurationProfile(
                    name=request.form['name'],
                    host_confidential=hc,
                    ioc_list=','.join(request.form.getlist('ioc_list')))
                    
            dbsession.add(cp)
            dbsession.commit()
            
            if success:
                return redirect(url_for('config'))
            else:
                flash('\n'.join(errors))
                return render_template('config-profile-add.html', xmliocs = xi, name = request.form['name'], host_confidential = request.form['host_confidential'])
    else:
        return redirect(url_for('login'))
        
     
        # MISC. VIEWS
        
@app.route('/config/profile/<int:profileid>/popupview')
def profilePopupView(profileid):
    if 'logged_in' in session:
        return render_template('config-profile-popupview.html')
    else:
        return redirect(url_for('login'))


        # CAMPAIGN RESULTS

@app.route('/campaignvisualizations')
def campaignvisualizations():
    if 'logged_in' in session:
        batches = dbsession.query(Batch).order_by(Batch.name.asc())
        
        return render_template('campaign-visualizations.html', batches = batches)
    else:
        return redirect(url_for('login'))
        
@app.route('/campaignvisualizations/<int:batchid>')
def campaignvisualizationbatch(batchid):
    if 'logged_in' in session:
        batch = dbsession.query(Batch).filter_by(id = batchid).first()
        
        if batch is None:
            return redirect(url_for('campaignvisualizations'))
        else:
            return render_template('campaign-visualizations-batch.html', batch = batch)
    else:
        return redirect(url_for('login'))

        
@app.route('/ioc/<int:iocid>')
def iocvizu(iocid):
    if 'logged_in' in session:
        return render_template('ioc-vizualisation.html', iocid = iocid)
    else:
        return redirect(url_for('login'))


@app.route('/static/data/ioc.json/<int:iocid>')
def iocjson(iocid):
    # if 'logged_in' in session:
    
    response = ''
    
    ioc = dbsession.query(XMLIOC).filter_by(id = iocid).first()
    
    if ioc is None:
        return Response(status=404, response='This IOC does not exist', content_type='text/plain')

    FLAT_MODE = (IOC_MODE == 'flat')
    allowedElements = {}
    evaluatorList = ioc_modules.flatEvaluatorList if FLAT_MODE else ioc_modules.logicEvaluatorList

    for name, classname in evaluatorList.items():
        allowedElements[name] = classname.evalList

    content = base64.b64decode(ioc.xml_content)

    oip = openiocparser.OpenIOCParser(content, allowedElements, FLAT_MODE, fromString=True)
    oip.parse()
    
    tree = oip.getTree()
    
    return Response(status=200, response=json.dumps(tree.json2(), indent=4), content_type='application/json')
    # else:
        # return redirect(url_for('login'))


@app.route('/host-result/<int:hostid>')
def hostresult(hostid):
    if 'logged_in' in session:
        return render_template('host-result-vizualisation.html', hostid = hostid)
    else:
        return redirect(url_for('login'))

        
@app.route('/static/data/host.json/<int:hostid>')
def hostjson(hostid):
    # if 'logged_in' in session:
    
    response = ''
    
    task, result = dbsession.query(Task, Result).filter(Result.id==hostid).join(Result, Task.id == Result.tache_id).first()
    if task is None or result is None:
        return Response(status=404, response='This host does not exist', content_type='text/plain')
        
    if not result.smbreachable:
        tab = {'name':task.ip, 'infected':True, 'children':[{'name':'This host could not be joined', 'infected': True}]}
        return Response(status=200, response=json.dumps(tab), content_type='application/json')
    
    batch = dbsession.query(Batch).filter_by(id = task.batch_id).first()
    cp = dbsession.query(ConfigurationProfile).filter_by(id = batch.configuration_profile_id).first()
    ioc_list = [int(e) for e in cp.ioc_list.split(',')]
    
    ioc_detections = dbsession.query(IOCDetection).filter_by(result_id = result.id).all()
    guids = {}
    
    guids = {i:[] for i in ioc_list}
    
    for iocd in ioc_detections:
        # if not iocd.xmlioc_id in guids.keys():
            # guids[iocd.xmlioc_id] = []
            
        guids[iocd.xmlioc_id].append(iocd.indicator_id)
        
    tree = {'name':task.ip, 'children':[], 'infected': False}
    
    host_infected = False
    for iocid in ioc_list:
    
        ioc = dbsession.query(XMLIOC).filter_by(id = iocid).first()
    
        FLAT_MODE = (IOC_MODE == 'flat')
        allowedElements = {}
        evaluatorList = ioc_modules.flatEvaluatorList if FLAT_MODE else ioc_modules.logicEvaluatorList

        for name, classname in evaluatorList.items():
            allowedElements[name] = classname.evalList

        content = base64.b64decode(ioc.xml_content)

        oip = openiocparser.OpenIOCParser(content, allowedElements, FLAT_MODE, fromString=True)
        oip.parse()
        
        tmp = oip.getTree()
        tmp.infect(guids[iocid])
        tmp = tmp.json2()
        
        tmptree = {'name':ioc.name, 'children': [tmp], 'infected': tmp['infected']}
        tree['children'].append(tmptree)
        tree['infected'] |= tmp['infected']
    
    
    return Response(status=200, response=json.dumps(tree, indent=4), content_type='application/json')
    
        
def getInfosFromXML(content):

    c = base64.b64decode(content)
    r = {'guids':{}, 'totalguids':0}
    
    # <IndicatorItem id="b63cc380-b286-45b9-8009-a85d2be07236" condition="contains">
    #   <Context document="DnsEntryItem" search="DnsEntryItem/RecordName" type="mir"/>
    #   <Content type="string">outlookscansafe.net</Content>
    
    # <IndicatorItem id="54d1f329-a4bc-4e24-b047-5786950d2109" condition="is">
    #   <Context document="DnsEntryItem" search="DnsEntryItem/RecordName" type="mir" />
    #   <Content type="string">dieideenwerkstatt.at</Content>
    
    matches = re.findall(r'\<IndicatorItem[^>]+id="([^"]+)"[^>]*\>[^<]+\<Context ([^>]*)/\>[^<]+\<Content[^>]+\>([^<]*)\</Content\>', c)
    
    for match in matches:
        guid, context, content = match
        search = re.findall(r'search="([^"]+)"', context)[0]
        
        r['guids'][guid] = {'search':search, 'value':content}
        r['totalguids'] += 1
    
    return r
        
@app.route('/static/data/results.csv/<int:batchid>')
def resultscsv(batchid):
    #if 'logged_in' in session:
    response = 'Title:HostId,Title:Hostname-IP,Lookup:Success,Lookup:Subnet,Malware,Compromise'
    
    #Get Batch
    batch = dbsession.query(Batch).filter_by(id = batchid).first()
    if batch is None:
        return Response(status=404)
        
    #Get all IOCs
    cp = dbsession.query(ConfigurationProfile).filter_by(id = batch.configuration_profile_id).first()
    ioc_list = [int(e) for e in cp.ioc_list.split(',')]
    iocs = dbsession.query(XMLIOC).filter(XMLIOC.id.in_(ioc_list)).all()
    
    #Complete first line & assoc ioc.id => ioc
    all_iocs = {}
    for ioc in iocs:
        all_iocs[ioc.id] = ioc
        response += ',%s' % ioc.name
    response += '\n'
    
    all_tasks_results = dbsession.query(Task, Result).filter(Task.batch_id==batchid).join(Result, Task.id == Result.tache_id).all()

    # Get totak indicator items / IOC
    total_by_ioc = {}
    for ioc in iocs:
        infos = getInfosFromXML(ioc.xml_content)
        total_by_ioc[ioc.id] = infos['totalguids']
        
    
    for task, result in all_tasks_results:
        ioc_detections = dbsession.query(IOCDetection).filter_by(result_id = result.id).all()
        
        response += '%d,%s,%s,%s' % (result.id, task.ip, result.smbreachable, task.commentaire)
        result_for_host = {e:0 for e in ioc_list}
        
        # Sum IOC detections
        for ioc_detection in ioc_detections:
            result_for_host[ioc_detection.xmlioc_id] += 1
            
        # Compute n in [0,1] = % of detection
        result_for_host = {id: round(val*100./total_by_ioc[id])/100 for id,val in result_for_host.items()}
        
        # Get max
        mval, mid = 0, -1
        for id, val in result_for_host.items():
            if val>mval:
                mval, mid = val, id
        
        # Complete max compromise
        mname = "None" if mid==-1 else all_iocs[mid].name
        response += ',%s,%.2f' % (mname, mval)
        
        #Complete detection / IOC
        for id in all_iocs:
            response += ',%.2f' % result_for_host[id]
        response += '\n'     
    
    return Response(status=200, response=response, content_type='text/plain')
    #else:
        #return redirect(url_for('login'))


    # CAMPAIGN PLANIFICATION

@app.route('/scan/', methods=['GET',])
def scan():
    if 'logged_in' in session:
    
        batches = dbsession.query(Batch).order_by(Batch.name.asc())
        
        return render_template('scan-planification.html', batches = batches)
    else: #Not logged in
        return redirect(url_for('login'))
        
        
@app.route('/scan/batch/add', methods=['GET','POST'])
def scanbatchAdd():
    if 'logged_in' in session:
    
        cp = dbsession.query(ConfigurationProfile).order_by(ConfigurationProfile.name.asc())
        wc = dbsession.query(WindowsCredential).order_by(WindowsCredential.domain.asc(), WindowsCredential.login.asc())
    
        if request.method == 'GET':
            return render_template('scan-planification-batch-add.html', configuration_profiles = cp, windows_credentials = wc)
        else:
            success = True
            errors = []
            
            batch = Batch(
                    name=request.form['name'],
                    configuration_profile_id = request.form['profile'],
                    windows_credential_id = request.form['credential'])
                    
            dbsession.add(batch)
            dbsession.commit()
            
            if success:
                return redirect(url_for('scan'))
            else:
                flash('\n'.join(errors))
                return render_template('scan-planification-batch-add.html', configuration_profiles = cp, windows_credentials = wc)
    else: #Not logged in
        return redirect(url_for('login'))
        
    
@app.route('/scan/batch/<int:batchid>', methods=['GET',])
def scanbatch(batchid):
    if 'logged_in' in session:
            
        batch = dbsession.query(Batch).filter_by(id=batchid).first()
        cp = dbsession.query(ConfigurationProfile).filter_by(id = batch.configuration_profile_id).first()
        wc = dbsession.query(WindowsCredential).filter_by(id = batch.windows_credential_id).first()
        
            
        return render_template('scan-planification-batch.html', batch = batch, configuration_profile = cp, windows_credential = wc)
    else: #Not logged in
        return redirect(url_for('login'))


    # API

@app.route('/api/getdetections', methods=['GET',])
def api_get_detections():
    if 'logged_in' in session:
        jsonData = {'code': 501}
        statement = ('''
                SELECT result.json_result
                FROM host
                    LEFT JOIN result
                        ON host.host_id = result.host_id
                WHERE ''', 
                '''ORDER BY result.result_id DESC
                LIMIT 1''')
        if request.args.get('hostname', None) and len(request.args.get('hostname')) > 0:
            hostname = request.args.get('hostname')

            con = sqlite3.connect(ANALYSIS_DB)
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            jsonData = cur.execute(statement[0] + 'host.host_ip = ?' + statement[1], (hostname,)).fetchone()
            if not jsonData:
                jsonData = {'code': 500}
        elif request.args.get('id', None) and len(request.args.get('id')) > 0:
            id = request.args.get('id')

            con = sqlite3.connect(ANALYSIS_DB)
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            jsonData = cur.execute(statement[0] + 'host.host_id = ?' + statement[1], (id,)).fetchone()
            if not jsonData:
                jsonData = {'code': 500}
        return Response(jsonData, mimetype='application/json')

    else: # Not logged in
        return redirect(url_for('login'))


@app.route('/api/scan/')
@app.route('/api/infos/')
def api_old_interface():
    if 'logged_in' in session:
        try:
            user = None
            def getCible(param):
                param_list = param.get('ip_list')
                param_ip = param.get('ip')
                param_hostname = param.get('hostname')
                
                if param_list and len(param_list) > 0:
                    liste = param_list[0].replace('\r\n','\n')
                    ips = liste.split('\n')
                    ip = ips[0]
                    
                    return ip,ips
                else:                
                    if (param_ip and len(param_ip) > 0) or (param_hostname and len(param_hostname) > 0):
                        # Détermination de l'IP à scanner
                        if param_ip:
                            try:
                                ip = param_ip[0]
                                ips = IPNetwork(ip)
                            except:
                                return renvoitErreurJSON(400, 'Erreur dans le format de l\'IP fournie')
                        elif param_hostname:
                            try:
                                ip = resolve(param_hostname[0])
                                ips = IPNetwork(ip)
                            except:
                                return renvoitErreurJSON(400, 'Hote introuvable !')
                        return ip, ips

            def APIscan():
                return 'API de scan\nUsage: /scan/?(ip=0.0.0.0|hostname=MACHINE)[&priority=10][&essais=1][&force=0][&batch=...][&commentaire=...]\n'

            def APIconsult():
                return 'API de consultation\nUsage: /infos/?(ip=0.0.0.0|hostname=MACHINE)\n'

            def renvoitErreurJSON(code, message):
                reponse = {}
                reponse['code'] = code
                reponse['message'] = message
                return Response(status=200, response=json.dumps(reponse, indent=4), content_type='application/json')

            def new_alchemy_encoder():
                _visited_objs = []
                class AlchemyEncoder(json.JSONEncoder):
                    def default(self, obj):
                        if isinstance(obj.__class__, DeclarativeMeta):
                            # don't re-visit self
                            if obj in _visited_objs:
                                return None
                            _visited_objs.append(obj)

                            # an SQLAlchemy class
                            fields = {}
                            avoid = ['id', 'resultat', 'result_id', 'ports']
                            for field in [x for x in dir(obj) if not x.startswith('_') and x != 'metadata' and x not in avoid]:
                                data = obj.__getattribute__(field)
                                if type(data) == datetime.datetime:
                                    data = str(data)
                                try:
                                    data = unicode(data.decode('cp850'))
                                except:
                                    pass
                                fields[field] = data
                            # a json-encodable dict
                            return fields

                        return json.JSONEncoder.default(self, obj)
                return AlchemyEncoder

            loggingserver.info('Request from ' + request.remote_addr + ' with path ' + request.url)

            args = request.url.split('?', 1)

            # Passage en revue des modules de visualisation
            vue_a_afficher = False
            modules_vues_autorises = []
            for module in MODULES_VUES:
                autorisation = False
                module_vue = __import__(
                        "modules." + module + '.main',
                        fromlist=['name_in_path', 'has_right', 'view']
                    )
                autorisation = True
                modules_vues_autorises.append(module_vue)
                if request.path == '/vue/' + module_vue.name_in_path + '/':
                    if not autorisation:
                        abort(403)
                        loggingserver.warning('Cannot display view ' + module + ' for user ' + user)
                        return
                    [code, content_type, content] = module_vue.view(user, args, loggingserver, dbsession)
                    loggingserver.info('View module ' + module + ' displayed to user ' + user + ' with return code ' + str(code))
                    vue_a_afficher = True
                    break

            if vue_a_afficher:
                return Response(status=code if code > 0 else 200, response=content, content_type=content_type if len(content_type) > 0 else 'text/html')

            if request.path == '/api/scan/': # Ajout d'une cible
                loggingserver.debug('Scan request incoming ')
                if len(args) > 1:
                    param = urlparse.parse_qs(args[1])
                    # Détermination de l'IP à scanner
                    ip, ips = getCible(param)
                    if ip and ips and len(ips) > 0:

                        # Détermination de la priorité
                        try:
                            priority = int(param['priority'][0])
                        except:
                            priority = 10
                        if not priority > 0:
                            priority = 10

                        # Détermination des essais à effectuer
                        essais = param.get('retries_discovery')
                        if essais and len(essais) > 0:
                            try:
                                assert 0 < int(essais[0]) <= 10000
                                retries_left_discovery = int(essais[0])
                            except:
                                retries_left_discovery = 1
                        else:
                            retries_left_discovery = 1

                        essais = param.get('retries_ioc')
                        if essais and len(essais) > 0:
                            try:
                                assert 0 < int(essais[0]) <= 10000
                                retries_left_ioc = int(essais[0])
                            except:
                                retries_left_ioc = 1
                        else:
                            retries_left_ioc = 1
                            


                        # if len(filter(ip.startswith, PREFIXES_IP_GROUPE)) == 0:
                            # return renvoitErreurJSON(400, 'Scan de cette IP non autorise ; l\'API est limitee aux IPs internes au Groupe')
                        # if len(ips) > NOMBRE_MAX_IP_PAR_REQUETE:
                            # return renvoitErreurJSON(400, 'Erreur, trop d\'IP fournies (max : ' + str(NOMBRE_MAX_IP_PAR_REQUETE) + ', equivalent a un /' + str(int(32 - log(NOMBRE_MAX_IP_PAR_REQUETE, 2))) + ')')
                        # else:
                        subnet = param.get('subnet', None)
                        if subnet and subnet[0] > 0:
                            subnet = subnet[0]
                        batch = param.get('batch', None)
                        if batch and batch[0] > 0:
                            batch = batch[0]
                            
                        reponse = {}
                        reponse['code'] = 200
                        reponse['message'] = 'Scan de ' + str(len(ips)) + ' ip demande'

                        reponse['ips'] = {}
                        
                        # Ajout à la queue...
                        for ip in ips:
                            actualise = False

                            if not param.get('force'):
                                limite_avant_nouvel_essai = datetime.datetime.now() - datetime.timedelta(0, SECONDES_POUR_RESCAN)
                                if dbsession.query(Result).filter(Result.ip == str(ip), Result.finished >= limite_avant_nouvel_essai).count() > 0:
                                    reponse['ips'][str(ip)] = 'deja scannee il y a peu'
                                    continue
                                elif dbsession.query(Task).filter(Task.ip == str(ip), Task.batch_id == batch, Task.date_soumis >= limite_avant_nouvel_essai).count() > 0:
                                    reponse['ips'][str(ip)] = 'deja soumise il y a peu'
                                    continue
                                # if batch and len(batch) > 0:
                                    # if dbsession.query(Task).join(Result).filter(Task.ip == str(ip), Task.batch == batch, Task.retries_left_discovery == 0).count() > 0:
                                        # actualise = True
                                    # elif dbsession.query(Task).join(Result).filter(Task.ip == str(ip), Task.batch == batch, Result.up == 1).count() > 0:
                                        # reponse['ips'][str(ip)] = 'deja scannee dans le batch ' + batch
                                        # continue
                                    # elif dbsession.query(Task).filter(Task.ip == str(ip), Task.batch == batch).count() > 0:
                                        # reponse['ips'][str(ip)] = 'en attente dans le batch ' + batch
                                        # continue

                            try:
                                ip_int = int(ip)                                    
                            except ValueError,e:
                                try:
                                    ipn = IPNetwork(ip)
                                    ip_int = int(ipn[0])
                                except Exception, e:
                                    reponse['ips'][str(ip)] = 'IP non valide'
                                    continue
                                    
                            tache = Task(
                                ip=str(ip),
                                ip_int=ip_int,
                                priority=priority,
                                discovered=True, # change this when you want to reintegrate NMAP
                                reserved_discovery=False,
                                reserved_ioc=False,
                                ip_demandeur=request.remote_addr,
                                retries_left_discovery=retries_left_discovery,
                                retries_left_ioc=retries_left_ioc,
                                commentaire=subnet,
                                batch_id=batch
                            )
                            dbsession.add(tache)
                            if batch and len(batch) > 0 and not actualise:
                                reponse['ips'][str(ip)] = 'ajoutee au batch ' + batch + ' (' + str(retries_left_discovery) + ' essais discovery, ' + str(retries_left_ioc) + ' essais iocscan)'
                            elif batch and len(batch) > 0 and actualise:
                                reponse['ips'][str(ip)] = 'ajoutee au batch ' + batch + ' pour re-essai (' + str(retries_left_discovery) + ' essais discovery, ' + str(retries_left_ioc) + ' essais iocscan)'
                            else:
                                reponse['ips'][str(ip)] = 'ajoutee dans la queue (' + str(retries_left_discovery) + ' essais discovery, ' + str(retries_left_ioc) + ' essais iocscan)'
                            
                            dbsession.commit()
                        return Response(
                            status=200,
                            response=json.dumps(
                                reponse,
                                indent=4
                            ),
                            content_type='application/json'
                        )
                    else:
                        return APIscan()
                else:
                    return APIscan()
            elif request.path == '/api/infos/': # Lecture de la base
                if TYPE_AUTH == 'AD' and user not in ADMINS + DROIT_LECTURE:
                    abort(403)
                    return

                if len(args) > 1:
                    param = urlparse.parse_qs(args[1])

                    # Détermination de l'IP à scanner
                    ip, ips = getCible(param)
                    if ip:
                        reponse = {}

                        taches_en_cours = dbsession.query(Task).filter_by(ip=ip)
                        reponse['taches_terminees'] = taches_en_cours.filter_by(discovered=1, consolidated=1).count()
                        reponse['taches_abandonnees'] = taches_en_cours.filter_by(discovered=0, retries_left_discovery=0).count()
                        reponse['taches_en_cours'] = taches_en_cours.filter_by(consolidated=0, reserved_discovery=1).count()
                        reponse['taches_en_attente'] = taches_en_cours.filter_by(discovered=0, reserved_discovery=0).filter(Task.retries_left_discovery > 0).count()

                        # Récupération des scans associés
                        resultats = dbsession.query(Result).filter_by(ip=ip)
                        for Result_model in results:
                            resultats = resultats.outerjoin(Result_model)
                        #print resultats.count()
                        if resultats.count() > 0:
                            # On récupère le dernier résultat
                            resultat = resultats.order_by('resultats_id desc')[0]

                            # Affinage affichage ports ouverts
                            ports_reverse = {}
                            for entry in PORTS:
                                nom = entry[1] if len(entry) > 1 else ""
                                for entry_uniq in str(entry[0]).split(','):
                                    p = entry_uniq.split('-')
                                    if len(p)>1 and p[0] >= 0 and p[1] > p[0]:
                                        for port in xrange(int(p[0]), int(p[1])+1):
                                            ports_reverse[int(port)] = nom
                                    else:
                                        ports_reverse[int(entry_uniq)] = nom
                            resultat.ports_ouverts = {}
                            for p in resultat.ports:
                                if p.status == 'open':
                                    resultat.ports_ouverts[p.port] = ports_reverse[p.port]
                            reponse['dernier_scan'] = resultat

                        # Conversion en JSON et envoi
                        return Response(
                            status=200,
                            response=json.dumps(
                                reponse,
                                cls=new_alchemy_encoder(),
                                check_circular=False,
                                indent=4
                            ),
                            content_type='application/json'
                        )
                    else:
                        return APIconsult()
                else:
                    return APIconsult()

        except Exception, e:
            loggingserver.error('Unknown error !', exc_info=True)
            dbsession.rollback()
            time.sleep(1)
            abort(500)
    else: # Not logged in
        return redirect(url_for('login'))


    # SCAN PROGRESS

@app.route('/progress', methods=['GET',])
def progress():
    if 'logged_in' in session:
        headers = (
            'id',
            'ip',
            'ip_demandeur',
            'commentaire',
            'batch_id',
            'date_soumis',
            'date_debut',
            'discovered',
            'iocscanned',
            'priority',
            'reserved_discovery',
            'reserved_ioc',
            'consolidated',
            'retries_left_ioc',
            'retries_left_discovery',
            'last_retry',
        )
        tasks = dbsession.query(Task).order_by('id DESC').limit(TACHES_NOMBRE)
        tasks_data = [[getattr(t, h) for h in headers] for t in tasks]
        return render_template('scan-progress.html', headers=headers, tasks_data=tasks_data)
    else: #Not logged in
        return redirect(url_for('login'))


    # SERVER LAUNCH
    
def run_server():

    context = None
    
    if USE_SSL and os.path.isfile(SSL_KEY_FILE) and os.path.isfile(SSL_CERT_FILE):
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain(SSL_CERT_FILE, SSL_KEY_FILE)
        loggingserver.info('Using SSL, open interface in HTTPS')

    loggingserver.info('Web interface starting')
    app.run(
        host='127.0.0.1',
        debug=DEBUG,
        ssl_context = context
    )

if __name__ == '__main__':
    run_server()