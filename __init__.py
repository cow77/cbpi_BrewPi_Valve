# -*- coding: utf-8 -*-
import os, sys, getopt, struct
from subprocess import Popen, PIPE, call
from struct import *
from modules import cbpi, app
from modules.core.hardware import SensorPassive, SensorActive
import json
import re, threading, time
from flask import Blueprint, render_template, request
from modules.core.props import Property
from modules.core.hardware import ActorBase 
import Queue

q = Queue.Queue()
workerBP_set_stateLock = False
rs = ["","","","",""]

try:
    from contextlib import contextmanager
except Exception as e:
    cbpi.notify("Initialize BrewPiValve failed", "Please make sure to run: sudo apt-get install contextlib", type="danger", timeout=None)
    pass

@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass


try:
    from pyowfs import Connection
    root = Connection('localhost:4304')
except Exception as e:
    root = None
    pass


def TestBit(s,b):
    ## reverse test!
    r = None
    if b == 0: t = 1
    if b == 1: t = 2
    if b == 2: t = 4
    if b == 3: t = 8
    if b == 4: t = 16
    if b == 5: t = 32
    if b == 6: t = 64
    if b == 7: t = 128

    if (ord(s) & t): 
        r = False
    else:
        r = True
    ##cbpi.app.logger.info("TestBit: bit: %s => %s" % ( b, r ))
    return(r)


blueprint = Blueprint('one_wire_valve', __name__)


@cbpi.actor
class BrewPiValve(ActorBase):
    OWFS = False
   
    def getBPValves():
        try:
            arr = []
            for dirname in os.listdir('/sys/bus/w1/devices'):
                if (dirname.startswith("29")):
                    cbpi.app.logger.info("Device %s Found (Family: 29, Valve on w1, GPIO4)" % dirname)
                    arr.append(dirname)
        except:
            pass
        
        try:
            if root != None:
                for s in root.find (family="29"):
                    dirname = s.get("address")
                    if dirname in arr:
                        pass
                    else:
                        cbpi.app.logger.info("Device %s Found (Family: %s, ID: %s, Type: %s, Valve on owfs)" % ( s.get("address"), s.get("family"), s.get("id"), s.get("type") ))
                        arr.append(s.get("address"))
            return arr
        except:
            return []

    actor_name = Property.Select("1W-BP-Actor", options=getBPValves(), default_value=0, description="The BrewPi OneWire Valve Controller address.")
    actor_type = Property.Select("Type", options=["CR03","CR05"], description="The valve type (CR03 = two wires, CR05 = 5 wires with status-feedback).")
    port_name = Property.Select("Port", options=["A","B"], description="The BrewPi valve port.")
    inact_timeout = Property.Number("Timeout", configurable=True, default_value=10, description="Valve setting timeout.")
 
    if (actor_name == 0):
        cbpi.notify("BrewPiValve failed", "Please make sure BrewPiValve exist.", type="danger", timeout=None)


    def targetState(self, actor, port, state):
        OB = 8       ## 3
        CB = 4       ## 2
        OA = 128     ## 7
        CA = 64      ## 6

        st = 0
        if (port == "A"):
            rs = self.getBPstate(actor,"B")
            if (list(rs)[1] == "OPENED"):
                st = OB
            elif (list(rs)[1] == "OFF"):
                st = OB+CB
            elif (list(rs)[1] == "OFFLEDSON"):
                st = 0
            elif (list(rs)[1] == "CLOSED"):
                st = CB
            ##cbpi.app.logger.info("VALVE: %s, port: %s state (st): %d" % (actor, "B", st))
                    
            if (state == "OFF"):         ## default inactive state: 00fd = 1111 1101
                st = st + OA + CA
            elif (state == "OFFLEDSON"):
                st = st + 0
            elif (state == "OPEN"):
                st = st + OA       
            elif (state == "CLOSE"):
                st = st + CA       
            ##cbpi.app.logger.info("VALVE: %s, port: %s state (st): %d" % (actor, port, st))
        elif (port == "B"):
            rs = self.getBPstate(actor,"A")
            if (list(rs)[1] == "OPENED"):
                st = OA
            elif (list(rs)[1] == "OFF"):
                st = OA+CA
            elif (list(rs)[1] == "OFFLEDSON"):
                st = 0
            elif (list(rs)[1] == "CLOSED"):
                st = CA
            ##cbpi.app.logger.info("VALVE: %s, port: %s state (st): %d" % (actor, "A", st))

            if (state == "OFF"):         ## default inactive state: 00fd = 1111 1101
                st = st + OB + CB
            elif (state == "OFFLEDSON"):
                st = st + 0
            elif (state == "OPEN"):
                st = st + OB
            elif (state == "CLOSE"):
                st = st + CB
            ##cbpi.app.logger.info("VALVE: %s, port: %s state (st): %d" % (actor, port,st))
        return (st)


    def getBPstate(self, actor, port):
        b=0
        rss = "UNKNOWN"         ## unknown
        rsa = "OFFLEDSON"       ## inactive
        
        if root != None:
            s = root.find (address=actor)
            if s == None:
                self.OWFS = False
            else:
                self.OWFS = True
        else:
            self.OWFS = False 

        if self.OWFS == False:
            with ignored(Exception):
                with open('/sys/bus/w1/devices/w1_bus_master1/%s/state' % actor, 'rb') as cf:
                    b=cf.read(1)
            ##cbpi.app.logger.info("VALVE: %s, port: %s devices/w1_bus_master1/--actor--/state: %s" % (actor, port,b))
        elif self.OWFS == True:
            try:
                s = root.find(address=actor)[0]
                s.use_cache (0)

                key = "sensed.BYTE"
                if (s.has_key (key)):
                    x = s.get(key)
                l = list(x)
                if l == None:
                    return ( ["UNKNOWN", "INACTIVE"] )
                else:
                    ##cbpi.app.logger.info("VALVE: %s, port: %s sensed.BYTE: %s" % (actor, port, l))
                    b = struct.pack("=B",  int(''.join(map(str,[int(i) for i in l]))) )
            except Exception as e:
                ##notify actor not found            
                cbpi.notify("BrewPiValve failed", "Please make sure Actor exist.", type="danger", timeout=None)
                return ( ["UNKNOWN", "INACTIVE"] )

        ## content of switchState:
        ## bit 7-6: Valve A action: 01 = open, 10 = close, 11 = off, 00 = off but LEDS on
        ## bit 5-4: Valve A status: 01 = opened, 10 = closed, 11 = in between
        ## bit 3-2: Valve B action: 01 = open, 10 = close, 11 = off, 00 = off but LEDS on
        ## bit 1-0: Valve B status: 01 = opened, 10 = closed, 11 = in between
        if port == "B":
            ## bit 1-0: Valve B status: 01 = opened, 10 = closed, 11 = in between
            if (TestBit(b,1)==True and TestBit(b,0)==True):  
                rss = "INBETWEEN"          ## 11 = in between
            elif (TestBit(b,1)==True and TestBit(b,0)==False):
                rsa = "CLOSED"             ## port fully closed
            elif (TestBit(b,1)==False and TestBit(b,0)==True):
                rss = "OPENED"             ## port fully open
            else:
                rss = "UNKNOWN"         ## unknown

            ## bit 3-2: Valve B action: 01 = open, 10 = close, 11 = off, 00 = off but LEDS on
            if (TestBit(b,2)==False and TestBit(b,3)==True):
               rsa = "OPEN"             ## port opening
            elif (TestBit(b,2)==True and TestBit(b,3)==False):
               rsa = "CLOSE"            ## port closing
            elif (TestBit(b,2)==True and TestBit(b,3)==True):
                rsa = "OFF"             ## port off
            elif (TestBit(b,2)==False and TestBit(b,3)==False):
                rsa = "OFFLEDSON"       ## inactive
        elif port == "A":
            ## bit 5-4: Valve A status: 01 = opened, 10 = closed, 11 = in between
            if (TestBit(b,4)==False and TestBit(b,5)==True): 
                rss = "OPENED"          ## 01 = port fully opened
            elif (TestBit(b,4)==True and TestBit(b,5)==False):
                rss = "CLOSED"          ## 10 = port fully closed
            elif (TestBit(b,5)==True and TestBit(b,4)==True):
                rss = "INBETWEEN"       ## 11 = in between
            else:
                rss = "UNKNOWN"         ## unknown

            ## bit 6-7: Valve A action: 01 = open, 10 = close, 11 = off, 00 = off but LEDS on
            if (TestBit(b,6)==False and TestBit(b,7)==True):
                 rsa = "OPEN"           ## 01 = port opening
            elif (TestBit(b,6)==True and TestBit(b,7)==False):
                 rsa = "CLOSE"          ## 10 = port closing
            elif (TestBit(b,7)==True and TestBit(b,6)==True):
                rsa = "OFF"             ## 11 port off
            elif (TestBit(b,7)==False and TestBit(b,6)==False):
                rsa = "OFFLEDSON"       ## off but LEDS on
        ##cbpi.app.logger.info("GetBPState => VALVE: ??, port: %s, rss: %s, rsa: %s" % (port, rss, rsa))
        return ( [rss, rsa] )


    def setBPstate(self, actor, port, type, action, timeout):
        if action == "OFF" or action == "OFFLEDSON":
            self.writeBPstate(actor, port, action) ## direct write
        else:
            global q
            q.put([actor, port, type, action, int(timeout)])   ## write via queue

 
    @cbpi.backgroundtask(key="BP1W_set", interval=15)
    def workerBP_set_state(self):
        global workerBP_set_stateLock
        if workerBP_set_stateLock:
            ##cbpi.app.logger.info("VALVE Q-worker. There is a Q-worker already ACTIVE; this thread exits")
            return
        workerBP_set_stateLock = True
        cbpi.app.logger.info("VALVE Q-worker started")

        global q,rs
        try:
            while True:
                if q.empty():
                    ##cbpi.app.logger.info("VALVE Q-worker queue: EMPTY")
                    ##time.sleep(.5)
                    return
                else:
                    rs = q.get()
                    cbpi.app.logger.info("VALVE Q-worker got cmd %s from queue" % (list(rs)))
                    actor  = list(rs)[0]
                    port   = list(rs)[1]
                    type   = list(rs)[2]
                    action = list(rs)[3]
                    timeout= int(list(rs)[4])
                    self.writeBPstate(actor, port, action)
                    self.worker(actor, port, type, action, timeout)
                    ##q.task_done()
                    cbpi.app.logger.info("VALVE Q-worker ready again")
        except Exception as e:
            workerBP_set_stateLock = False
            t = threading.Thread(target=self.workerBP_set_state)
            t.daemon = True
            t.start()
        cbpi.app.logger.info("VALVE Q-worker exit")


    def writeBPstate(self, actor, port, state):
        with ignored(Exception):
            if root != None:
                if (root.find(address=actor)):
                    self.OWFS = True
                else:
                    self.OWFS = False
            else:
                self.OWFS = False
 
        rs = self.targetState(actor, port, state)
        cbpi.app.logger.info("SetBPState=> VALVE: %s, port: %s, targetstate: %i" % (actor, port, rs))

        if self.OWFS == False:
            with ignored(Exception):
                ##cbpi.app.logger.info("VALVE: %s, port: %s, %s Just before write." % (actor, port, state))
                with open('/sys/bus/w1/devices/%s/output' % (actor), 'wb') as fo:
                    fo.write(struct.pack("=B",rs))
        if self.OWFS == True:
            key="PIO.BYTE"
            try:
                s=root.find(address=actor)[0]
                if (s.has_key (key)):
                    ##cbpi.app.logger.info("SetBPState=> VALVE: %s, port: %s, stat: %c" % (actor, port, rs))
                    s.put(key,rs)
            except Exception as e:
                ##notify actor not found            
                cbpi.notify("BrewPiValve failed", "Please make sure Actor exist.", type="danger", timeout=None)
        ##cbpi.app.logger.info("VALVE: %s, port: %s, %x" % (actor, port, rs))


    def worker(self, actor_name, port_name, actor_type, action, timeout):
        if action == "OFF" or action == "OFFLEDSON":  ## direct action
            self.setBPstate(actor_name, port_name, self.actor_type, "OFF", int(timeout))
            return

        inact_timeout=int(timeout)+1
        
        cbpi.app.logger.info("WRITE ACTOR (VALVE) Inactive check STARTED,  device: %s, PORT: %s, TYPE: %s, timeout: %d" % (actor_name, port_name, actor_type, timeout))
        wstate = 0
        wsecs  = 1
        time.sleep(1)

        if actor_type == "CR05":
            while ((wstate == 0) and (wsecs < inact_timeout)):  
                rs=self.getBPstate(actor_name, port_name)
                cbpi.app.logger.info("WRITE ACTOR (VALVE) check getBPstate %s. Device: %s PORT: %s. Action: %s" % (list(rs), actor_name, port_name, action))
                ##if ( list(rs)[1] == action):
                if ( list(rs)[0] == "CLOSED" and action == 'CLOSE' ):
                    wstate=1
                elif ( list(rs)[0] == "OPENED" and action == 'OPEN' ):
                    wstate=1
                else:
                    time.sleep(1)
                wsecs = wsecs + 1
            self.setBPstate(actor_name, port_name, self.actor_type, "OFF", inact_timeout)
        else:
            while (wsecs < inact_timeout): 
                time.sleep(1)
                wsecs = wsecs + 1
        
            self.setBPstate(actor_name, port_name, self.actor_type, "OFF", inact_timeout)

        cbpi.app.logger.info("WRITE ACTOR (VALVE) Inactive check READY after %s sec. Device: %s PORT: %s" % (wsecs, actor_name, port_name))
        return


    def init(self):
        #init place for routines
        ## set valve in predef state ..., but how?
        t = threading.Thread(target=self.workerBP_set_state)
        if t.isAlive():
            return
        else:
           t.daemon = True
           t.start()


    def on(self,power):
        cbpi.app.logger.info("WRITE ACTOR %s OPEN (VALVE %s PORT: %s)" % (self.name, self.actor_name, self.port_name))
        if self.actor_name is None:
            return
        
        ##rs = self.getBPstate(self.actor_name, self.port_name)
        ##if (list(rs)[0] == "OPENED") or (list(rs)[1] == "OPENING"):
        ##    return
        
        ##while (list(rs)[1] == "CLOSING"):
        ##    time.sleep(1)
        ##    pass

        self.setBPstate(self.actor_name, self.port_name, self.actor_type, "OPEN", self.inact_timeout)
        ##t = threading.Thread(target=self.worker,kwargs={'power':power}).start()


    def off(self):
        cbpi.app.logger.info("WRITE ACTOR %s CLOSE (VALVE %s PORT: %s)" % (self.name, self.actor_name, self.port_name))
        if self.actor_name is None:
            return

        ##rs = self.getBPstate(self.actor_name, self.port_name)
        ##if (list(rs)[0] == "CLOSED") or (list(rs)[1] == "CLOSING"):
        ##    return
    
        ##while (list(rs)[1] == "OPENING"):
        ##    time.sleep(1)
        ##    pass

        self.setBPstate(self.actor_name, self.port_name, self.actor_type, "CLOSE", self.inact_timeout)
        ##t = threading.Thread(target=self.worker, kwargs={'power':100}).start()


    def stop(self):
        '''
        Stop the sensor. Is called when the sensor config is updated or the sensor is deleted
        :return: 
        '''
        cbpi.app.logger.info("VALVE %s STOPPED; Device: %s PORT: %s" % (self.name, actor_name, port_name))
        pass


    def set_power(self, power):
        
        '''
        Optional: Set the power of your actor
        :param power: int value between 0 - 100
        :return: 
        '''
        pass


    @classmethod
    def init_global(cls):
        print "GLOBAL %s ACTOR" % (cls.__name__)
        ##try:
        ##    call(["modprobe", "w1-gpio"])
        ##    call(["modprobe", "w1-ds2408"])
        ##except Exception as e:
        ##    pass

@cbpi.initalizer()
def init(cbpi):
    cbpi.app.register_blueprint(blueprint, url_prefix='/api/one_wire_valve')
