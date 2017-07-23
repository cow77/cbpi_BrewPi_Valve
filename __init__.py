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

##from contextlib2 import suppress
from contextlib import contextmanager

@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass


blueprint = Blueprint('one_wire_bp', __name__)

def getBPValves():
    try:
        arr = []
        for dirname in os.listdir('/sys/bus/w1/devices'):
            if (dirname.startswith("29")):
                arr.append(dirname)
        return arr
    except:
        return []


def setBPstate(actor, state):
    with ignored(Exception):
        with open('/sys/bus/w1/devices/%s/output' % (actor), 'wb') as fo:
            fo.write(struct.pack("=B",state))
            ##return True
    ##return False


def getBPstate(actor):
    b = None
    with ignored(Exception):
        with open('/sys/bus/w1/devices/w1_bus_master1/%s/state' % actor, 'rb') as cf:
            b=cf.read(1)
    return b


@cbpi.actor
class BrewPiValve(ActorBase):
    actor_name = None
    port_name  = None
    power      = None
    curr_act   = False  ## porta and b off

    a_closed   = False
    a_open     = False
    a_closing  = False
    a_opening  = False 

    b_closed   = False
    b_open     = False
    b_closing  = False
    b_opening  = False 

    a_closing_tar =False
    a_opening_tar =False
    a_inactive_tar=False
    b_closing_tar =False
    b_opening_tar =False
    b_inactive_tar=False

    lastm  = 0

    actor_name = Property.Select("1W-BP-Actor", options=getBPValves(), description="The BrewPi OneWire Valve Controller address.")
    port_name = Property.Select("Port", options=["A","B"], description="The BrewPi valve port.")
    
    def worker(self, power=100):
        cbpi.app.logger.info("WRITE ACTOR (VALVE) Inactive check STARTED ON %s PORT: %s" % (self.actor_name, self.port_name))
        wstate=0
        wsecs=10
        while wstate == 0 and wsecs >> 0:  
            time.sleep(1)
            wsecs=wsecs-1
            self.curr_state()
            if self.port_name == "A":
                if self.a_closing == True:
                    if self.a_closed == True:
                        wstate=1
			a_inactive_tar=True
                        self.inactive()
                        break
                elif self.a_opening == True:
                    if self.a_open == True:
                        wstate=1
			a_inactive_tar=True
                        self.inactive()
                        break
            else:
                if self.b_closing == True:
                    if self.b_closed == True:
                        wstate=1
                        b_inactive_tar=False
                        self.inactive()
                        break
                elif self.b_opening == True:
                    if self.b_open == True:
                        wstate=1
                        b_inactive_tar=False
                        self.inactive()
                        break
        if wsecs == 0:
             self.inactive()
             pass
        cbpi.app.logger.info("WRITE ACTOR (VALVE) Inactive check READY after %s sec. ON %s PORT: %s" % (10-wsecs, self.actor_name, self.port_name))

 
    def curr_state(self):
        b=getBPstate(self.actor_name)
                
        # find status port A + B
        if b:
            if b:
                ##iostate=1
                if (ord(b) & 1):
                    self.b_closed = False     ## portb fully closed
                else:
                    self.b_closed = True    ## portb NOT closed

                if (ord(b) & 2):
                    self.b_open = False       ## portb fully open
                else:
                    self.b_open = True      ## portb NOT open

                if (ord(b) & 4):
                    self.b_closing = False    ## portb closing
                else:
                    self.b_closing = True   ## portb NOT closing

                if (ord(b) & 8):
                    self.b_opening = False    ## portb opening
                else:
                    self.b_opening = True   ## portb4 NOT opening

                if (ord(b) & 16):
                    self.a_closed = False    ## porta fully closed
                else:
                    self.a_closed = True    ## porta NOT fully closed

                if (ord(b) & 32):
                    self.a_open = False       ## porta fully open
                else:
                    self.a_open = True      ## porta NOT fully open

                if (ord(b) & 64):
                    self.a_closing = False    ## porta closing
                else:
                    self.a_closing = True   ## porta NOT closing

                if (ord(b) & 128):
                    self.a_opening = False    ## porta opening
                else:
                    self.a_opening = True   ## porta4 NOT opening

        r = 255-self.b_closed+(2*self.b_open)+(4*self.b_closing)+(8*self.b_opening)+(16*self.a_closed)+(32*self.a_open)+(64*self.a_closing)+(128*self.a_opening)
        cbpi.app.logger.info("STATE ACTOR ON (VALVE %s PORT: %s) %04x" % (self.actor_name, self.port_name, r))
        cbpi.app.logger.info("  Port a: closed %s; closing: %s; open: %s; opening: %s" % (self.a_closed, self.a_closing, self.a_open, self.a_opening))
        cbpi.app.logger.info("  Port b: closed %s; closing: %s; open: %s; opening: %s" % (self.b_closed, self.b_closing, self.b_open, self.b_opening))
        return r
 

    def target_state_inactive(self):
        if self.port_name == "A":
            self.b_closing_tar=self.b_closing
            self.b_opening_tar=self.b_opening
            self.a_closing_tar=False
            self.a_opening_tar=False
        elif self.port_name == "B":
            self.a_closing_tar=self.a_closing
            self.a_opening_tar=self.a_opening
            self.b_closing_tar=False
            self.b_opening_tar=False

        r = 255-((4*self.b_closing_tar)+(8*self.b_opening_tar)+(64*self.a_closing_tar)+(128*self.a_opening_tar))
        ##cbpi.app.logger.info("STATE TARGET-INACTIVE ACTOR ON (VALVE %s PORT: %s) %04x" % (self.actor_name, self.port_name, r))
        return r


    def target_state_on(self):
        if self.port_name == "A":
            self.b_closing_tar=self.b_closing
            self.b_opening_tar=self.b_opening
            self.a_closing_tar=False
            self.a_opening_tar=True
        elif self.port_name == "B":
            self.a_closing_tar=self.a_closing
            self.a_opening_tar=self.a_opening
            self.b_closing_tar=False
            self.b_opening_tar=True
        r = 255-((4*self.b_closing_tar)+(8*self.b_opening_tar)+(64*self.a_closing_tar)+(128*self.a_opening_tar))
        ##cbpi.app.logger.info("STATE TARGET-ON ACTOR (VALVE %s PORT: %s) %02x" % (self.actor_name, self.port_name, r))
        return r


    def target_state_off(self):
        if self.port_name == "A":
            self.b_closing_tar=self.b_closing
            self.b_opening_tar=self.b_opening
            self.a_closing_tar=True
            self.a_opening_tar=False
        elif self.port_name == "B":
            self.a_closing_tar=self.a_closing
            self.a_opening_tar=self.a_opening
            self.b_closing_tar=True
            self.b_opening_tar=False
        r = 255-((4*self.b_closing_tar)+(8*self.b_opening_tar)+(64*self.a_closing_tar)+(128*self.a_opening_tar))
        ##cbpi.app.logger.info("STATE TARGET-OFF ACTOR (VALVE %s PORT: %s) %02x" % (self.actor_name, self.port_name, r))
        return r


    def init(self):
        #init place for routines
        ##cbpi.app.logger.info("INIT BrewPiValve %s ON %s PORT: %s" % (self.name, self.actor_name, self.port_name))
        ##self.inactive()
        pass


    def on(self,power):
        ##cbpi.app.logger.info("WRITE ACTOR %s ON (VALVE %s PORT: %s)" % (self.name, self.actor_name, self.port_name))
        if self.actor_name is None:
            return
        
        n_cur = self.curr_state()

        if self.port_name == "A" and self.a_open == True:
            return()
        if self.port_name == "B" and self.b_open == True:
            return()
    
        n = self.target_state_on()
        
        setBPstate(self.actor_name,n)

        t = threading.Thread(target=self.worker,kwargs={'power':power}).start()


    def off(self):
        ##cbpi.app.logger.info("WRITE ACTOR %s OFF (VALVE %s PORT: %s)" % (self.name. self.actor_name, self.port_name))
        if self.actor_name is None:
            return

        n_cur = self.curr_state()

        if self.port_name == "A" and self.a_closed == True:
            return()
        if self.port_name == "B" and self.b_closed == True:
            return()

        n = self.target_state_off()
        
        setBPstate(self.actor_name,n)

        t = threading.Thread(target=self.worker, kwargs={'power':100}).start()


    def inactive(self):
        ##cbpi.app.logger.info("VALVE %s INACTIVE %s PORT: %s" % (self.name, self.actor_name, self.port_name))
        if self.actor_name is None:
            return

        n_cur = self.curr_state()  ## default inactive state: 00fd = 1111 1101
        n = self.target_state_inactive()
        
        setBPstate(self.actor_name,n)


    @classmethod
    def init_global(cls):
        print "GLOBAL %s ACTOR" % (cls.__name__)
        try:
            call(["modprobe", "w1-gpio"])
            call(["modprobe", "w1-ds2408"])
        except Exception as e:
            pass


